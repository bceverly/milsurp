"""On-disk store for downloaded listing photos.

Photos live outside the web root in a directory created mode 0700, and are never
exposed as static files. The API streams them through an authenticated endpoint
that resolves a stored relative path against the configured root, so a photo is
only reachable by a signed-in user.

Every photo is kept at **two resolutions**, both produced here while the scan
runs rather than on the vendor's side or in the browser:

* the original download, used by the item detail view;
* a down-sized thumbnail, used by the list/grid view so a page of fifty
  listings is a few hundred kilobytes instead of tens of megabytes -- which is
  what makes the grid usable on a phone.

Filenames are content-addressed (SHA-256 of the source URL) and sharded into
256 subdirectories per site, which keeps any single directory small even after
tens of thousands of listings.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import logging
import mimetypes
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from typing import NamedTuple
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import Image as PILImage

from ..config import Config
from ..logsafe import scrub
from . import cooldown

log = logging.getLogger("milsurp.images")

#: Only these types are written to disk; anything else is discarded.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
}

#: Refuse anything larger than this; vendor photos are far smaller.
MAX_IMAGE_BYTES = 20 * 1024 * 1024

#: How many times to re-ask for one photograph after a 429.
#:
#: A shop that rate-limits its pages rate-limits its uploads directory too, and
#: this downloader used to treat that as "photo missing, never mind" — silently,
#: with no log line. Checkpoint Charlie's is how it was found: 23 photographs
#: whose URLs each returned 200 to a single curl and 429 to a run of them, and
#: an item page with no picture on it.
PHOTO_ATTEMPTS = 3

#: Wait at least this long after a 429 before asking that host again, and never
#: longer than the cap however insistent the Retry-After.
MIN_PHOTO_BACKOFF = 5.0
MAX_PHOTO_BACKOFF = 60.0

#: HTTP 429, named rather than spelled, to match the scrapers.
TOO_MANY_REQUESTS = 429

#: Statuses that will still be true tomorrow.
#:
#: This decides whether a failure counts against a photograph's retry budget. A
#: 404 is a property of the URL and will not improve, so it is worth giving up
#: on. A 429 or a 503 is a property of the *moment* — and a rate-limit burst
#: that burned three attempts would strand every photograph it touched,
#: permanently, for a shop that was merely busy. Bounding those is the host
#: cooldown's job, not this counter's.
#:
#: 403 is here despite being arguable: it is usually a real block rather than a
#: passing one, and `make photos-retry` exists for the cases where it clears.
PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 405, 410, 414, 415, 451})


def _is_permanent(status: int | None) -> bool:
    """Whether a failure at this status is worth giving up on."""
    return status is not None and status in PERMANENT_STATUSES


def _photo_backoff(response: requests.Response, current: float) -> float:
    """How long to wait after a 429, honoring Retry-After when it is given."""
    stated = 0.0
    header = (response.headers.get("Retry-After") or "").strip()
    if header.isdigit():
        stated = float(header)
    return min(max(current * 2, stated, MIN_PHOTO_BACKOFF), MAX_PHOTO_BACKOFF)


#: Pillow's decompression-bomb guard, in pixels.
MAX_IMAGE_PIXELS = 64_000_000


#: Longest edge of a generated thumbnail, in pixels. 640 covers a 2x-density
#: phone grid cell and a desktop card without looking soft.
class Thumbnail(NamedTuple):
    """What :meth:`ImageStore.write_thumbnail` produced."""

    #: Where the thumbnail is, which for an image already small enough is the
    #: original itself rather than a second copy of the same picture.
    relative: str
    #: Its size in bytes, or None when it *is* the original.
    size: int | None
    #: The source image's dimensions, read while it was open anyway.
    width: int
    height: int


THUMBNAIL_MAX_EDGE = 640
THUMBNAIL_QUALITY = 82

FILE_MODE = 0o600
DIR_MODE = 0o700

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageStoreError(RuntimeError):
    pass


@dataclass
class StoredImage:
    """Result of downloading and processing one photo."""

    filename: str
    content_type: str
    bytes: int
    thumb_filename: str | None = None
    thumb_bytes: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class FetchResult:
    """What came back from asking for one photograph.

    ``image`` and ``reason`` are mutually exclusive: exactly one is set. The
    reason is a short sentence rather than a traceback, because it is stored on
    the photo row and read by a person wondering where the picture went.
    """

    image: StoredImage | None
    reason: str | None
    #: True when the failure is a property of the URL rather than the moment,
    #: so it is worth counting against the photograph's retry budget.
    permanent: bool = False
    #: True when nothing was actually tried, because the host is being left
    #: alone. The caller must not count this as a failed attempt — a cooldown
    #: would otherwise burn a photograph's whole retry budget without a single
    #: request being made.
    resting: bool = False


class UrlVerdict(NamedTuple):
    """Whether a URL may be fetched, and whether the answer will hold."""

    allowed: bool
    reason: str | None = None
    #: True when the refusal is a property of the URL rather than of the
    #: moment. See _check_url() for why that distinction is load-bearing.
    permanent: bool = False


#: Hostnames already resolved and found to be public, for the life of the
#: process. A scan of four hundred photographs from one CDN asked the resolver
#: four hundred times for the same name, and that volume is what provoked the
#: failures this exists to prevent: one SARCO scan had 151 photographs refused
#: as "not a public HTTP(S) URL", every one of them an ordinary
#: cdn11.bigcommerce.com address that resolves perfectly well.
#:
#: Only successes are remembered. A refusal is re-checked, so a host that was
#: briefly unresolvable is not written off, and one that has genuinely moved to
#: a private address is caught the next time it is asked about.
_PUBLIC_HOSTS: set[str] = set()


def _check_url(url: str) -> UrlVerdict:  # noqa: PLR0911 - one return per way a
    #                        URL can be refused, each with its own explanation
    """Reject anything that is not a plain public HTTP(S) URL.

    Image URLs come from third-party markup, so fetching one is a server-side
    request driven by untrusted input -- textbook SSRF. Only http/https to a
    publicly routable address is allowed, which keeps a malicious listing from
    making the scanner probe localhost, link-local metadata endpoints
    (169.254.169.254) or anything else on the internal network.

    **Failing to resolve a name is not the same as resolving it to somewhere
    forbidden**, and the two used to come back identically: both as "not a
    public HTTP(S) URL", both marked permanent, which spends one of the
    photograph's three attempts. A private address is a fact about the URL and
    will be just as true tomorrow. A resolver that gave up is a fact about the
    last half-second. Reported as such, and the message says which happened --
    "not a public HTTP(S) URL" sends whoever reads the log looking at a URL
    that turns out to be fine.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return UrlVerdict(False, "malformed URL", permanent=True)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return UrlVerdict(False, "not an HTTP(S) URL", permanent=True)

    host = parsed.hostname
    if host in _PUBLIC_HOSTS:
        return UrlVerdict(True)
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        # Transient by default. The name may be gone for good, in which case
        # the fetch that follows would fail anyway and the retry budget runs
        # out on its own terms.
        return UrlVerdict(False, f"could not resolve {host} ({exc.strerror or exc})")
    except UnicodeError:
        return UrlVerdict(False, "hostname is not encodable", permanent=True)

    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return UrlVerdict(False, "unreadable address", permanent=True)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return UrlVerdict(False, f"{host} resolves to a non-public address", permanent=True)
    _PUBLIC_HOSTS.add(host)
    return UrlVerdict(True)


class ImageStore:
    def __init__(self, config: Config) -> None:
        self.root = config.images_path
        self.config = config
        #: Hosts that have asked us to slow down, and the pace they asked for.
        #: Kept for the life of the store, so the photographs after the first
        #: refusal are paced rather than each discovering the limit again.
        self._slowed: dict[str, float] = {}
        self._last_request_at: dict[str, float] = {}

    # -- path handling ------------------------------------------------------
    def _relative_path(
        self, site_slug: str, source_url: str, extension: str, variant: str = ""
    ) -> str:
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        # Shard on the first two hex characters: 256 buckets per site.
        return f"{site_slug}/{digest[:2]}/{digest}{variant}{extension}"

    def absolute_path(self, relative: str) -> Path:
        """Resolve a stored relative path, refusing anything outside the root.

        The value comes from the database rather than from a request, but it is
        still validated: a traversal sequence that ever reached a row must not
        become an arbitrary file read.
        """
        root = self.root.resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ImageStoreError(f"refusing to resolve {relative!r} outside the image root")
        return candidate

    def exists(self, relative: str | None) -> bool:
        if not relative:
            return False
        try:
            return self.absolute_path(relative).is_file()
        except ImageStoreError:
            return False

    # -- writing ------------------------------------------------------------
    def _get_photo(
        self, session: requests.Session, source_url: str
    ) -> tuple[requests.Response | None, str | None, bool]:
        """GET one photograph, waiting out a 429 rather than giving up on it.

        The scraper has a whole apparatus for being told to slow down and this
        had none of it, which is defensible for a picture — a missing photo is
        not a missing listing — right up until a shop rate-limits its uploads
        directory and every photograph in the queue is thrown away in a burst.
        """
        host = urlparse(source_url).hostname or ""

        # Another process may already have been told to go away by this host.
        # Photographs are the most skippable thing the application fetches, so
        # this reports and moves on rather than sleeping through it.
        resting = cooldown.paused_for(source_url)
        if resting > 0:
            reason = f"{host} is resting for another {resting:.0f}s"
            log.info("Skipping %s: %s.", scrub(source_url), reason)
            return None, reason, False

        for attempt in range(PHOTO_ATTEMPTS):
            self._wait_for(host)
            try:
                response = session.get(
                    source_url,
                    timeout=self.config.scraping.request_timeout,
                    stream=True,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                # A connection that could not be made says nothing about the
                # URL, so it is never permanent.
                log.warning("Could not fetch %s: %s", scrub(source_url), scrub(exc))
                return None, str(exc), False

            self._last_request_at[host] = time.monotonic()
            if response.status_code != TOO_MANY_REQUESTS:
                try:
                    response.raise_for_status()
                except requests.RequestException as exc:
                    status = response.status_code
                    response.close()
                    log.warning("Could not fetch %s: %s", scrub(source_url), scrub(exc))
                    return None, str(exc), _is_permanent(status)
                cooldown.succeeded(source_url)
                return response, None, False

            wait = _photo_backoff(response, self._slowed.get(host, 0.0))
            self._slowed[host] = wait
            response.close()
            if attempt < PHOTO_ATTEMPTS - 1:
                log.info(
                    "%s asked us to slow down; waiting %.0fs before the next photo.", host, wait
                )
                time.sleep(wait)

        reason = f"{TOO_MANY_REQUESTS} after {PHOTO_ATTEMPTS} attempts"
        log.warning("Gave up on %s: the host kept answering %s.", scrub(source_url), reason)
        # Exhausted, so this is the host refusing rather than asking us to slow
        # down — and worth telling every other process about, which is the
        # whole point: a scan starting in a minute should not walk into it too.
        cooldown.refused(source_url, f"{TOO_MANY_REQUESTS} on photographs")
        return None, reason, False

    def _wait_for(self, host: str) -> None:
        """Honor the pace a host has already asked for."""
        pace = self._slowed.get(host)
        if not pace:
            return
        since = time.monotonic() - self._last_request_at.get(host, 0.0)
        if since < pace:
            time.sleep(pace - since)

    def download(
        self, session: requests.Session, site_slug: str, source_url: str
    ) -> StoredImage | None:
        """The image, or None. Use :meth:`fetch` when the reason matters."""
        return self.fetch(session, site_slug, source_url).image

    def fetch(self, session: requests.Session, site_slug: str, source_url: str) -> FetchResult:
        """Fetch one image, store it, and generate its thumbnail.

        Returns the reason alongside the result rather than only ``None``. A
        missing photo is never worth failing a scan over, but the queue is a
        table of rows with no file yet — so without a reason a URL that can
        never work is indistinguishable from one not reached yet, and gets
        retried on every scan forever.
        """
        verdict = _check_url(source_url)
        if not verdict.allowed:
            log.warning("Refusing to fetch %s: %s.", scrub(source_url), verdict.reason)
            return FetchResult(None, verdict.reason, permanent=verdict.permanent)

        response, error, permanent = self._get_photo(session, source_url)
        if response is None:
            return FetchResult(
                None, error, resting=cooldown.paused_for(source_url) > 0, permanent=permanent
            )

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        extension = ALLOWED_CONTENT_TYPES.get(content_type)
        if extension is None:
            # Some hosts serve images as application/octet-stream; fall back to
            # the URL's own extension, but only if it is one we accept.
            guessed = mimetypes.guess_type(source_url)[0]
            extension = ALLOWED_CONTENT_TYPES.get(guessed or "")
            if extension is None:
                response.close()
                reason = f"unsupported content type {content_type or 'none'}"
                log.warning("Skipping %s: %s.", scrub(source_url), reason)
                # What the server serves at this URL, not a passing condition.
                return FetchResult(None, reason, permanent=True)
            content_type = guessed or "image/jpeg"

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
            response.close()
            reason = f"image is {int(declared):,} bytes, over the {MAX_IMAGE_BYTES:,} limit"
            log.warning("Skipping %s: %s.", scrub(source_url), reason)
            return FetchResult(None, reason, permanent=True)

        relative = self._relative_path(site_slug, source_url, extension)
        target = self.absolute_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            target.parent.chmod(DIR_MODE)

        # Write to a temporary file first so an interrupted download never
        # leaves a truncated image that later looks cached and complete.
        #
        # The temporary name carries a process id and a random token, because
        # the final name does not distinguish writers: it is a hash of the
        # source URL, so two processes fetching the same photograph — the
        # scheduler mid-scan and a `make photos` draining the same queue — chose
        # the same ".part" path. One finished and renamed it away; the other
        # then chmod'd or renamed a file that no longer existed and reported
        # "No such file or directory" for a download that had in fact worked.
        temp = target.with_name(f"{target.name}.{os.getpid()}.{token_hex(4)}.part")
        written = 0
        try:
            with temp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_IMAGE_BYTES:
                        # Caught below with the other write failures; the point
                        # is to stop reading, not to report anything special.
                        raise ImageStoreError(  # noqa: TRY301
                            "image exceeds the maximum allowed size"
                        )
                    handle.write(chunk)
            temp.chmod(FILE_MODE)
            temp.replace(target)
        except (OSError, ImageStoreError, requests.RequestException) as exc:
            temp.unlink(missing_ok=True)
            log.warning("Could not store %s: %s", scrub(source_url), scrub(exc))
            return FetchResult(None, str(exc))
        finally:
            response.close()

        stored = StoredImage(filename=relative, content_type=content_type, bytes=written)
        self._make_thumbnail(stored, site_slug, source_url)
        return FetchResult(stored, None)

    def store_bytes(
        self, site_slug: str, key: str, data: bytes, extension: str = ".png"
    ) -> StoredImage | None:
        """Store an image a scraper produced itself, rather than downloaded.

        Most vendors publish photographs at a URL. Hunter's Lodge publishes a
        single scanned flyer and nothing else, so each listing's picture is a
        crop this application cuts out of that scan — bytes that exist only in
        memory and have no URL to fetch. Everything downstream (thumbnails,
        serving, pruning) is identical once the file is on disk, so this shares
        the same layout and the same naming as :meth:`download`.

        ``key`` stands in for the source URL when naming the file, so it must be
        stable for a given crop: the same flyer and the same region must give
        the same path on every scan, or every run would orphan the last one's
        files.
        """
        if len(data) > MAX_IMAGE_BYTES:
            log.warning("Generated image for %s is too large to store.", key)
            return None
        relative = self._relative_path(site_slug, key, extension)
        target = self.absolute_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".part")
        try:
            temp.write_bytes(data)
            temp.chmod(FILE_MODE)
            temp.replace(target)
        except OSError:
            temp.unlink(missing_ok=True)
            log.exception("Could not write the generated image for %s", key)
            return None

        content_type = "image/png" if extension == ".png" else "image/jpeg"
        stored = StoredImage(filename=relative, content_type=content_type, bytes=len(data))
        self._make_thumbnail(stored, site_slug, key)
        return stored

    def _make_thumbnail(self, stored: StoredImage, site_slug: str, source_url: str) -> None:
        """Down-size the stored image, filling in the thumbnail fields in place.

        A failure here is not fatal: the full image is already on disk, and the
        UI falls back to it when there is no thumbnail.
        """
        thumb_relative = self._relative_path(site_slug, source_url, ".jpg", variant="_t")
        made = self.write_thumbnail(stored.filename, thumb_relative)
        if made is None:
            return
        stored.width, stored.height = made.width, made.height
        stored.thumb_filename = made.relative
        stored.thumb_bytes = stored.bytes if made.relative == stored.filename else made.size

    def write_thumbnail(self, source_relative: str, thumb_relative: str) -> Thumbnail | None:
        """Write a down-sized copy of a stored image, and describe the result.

        Separate from :meth:`_make_thumbnail` so a thumbnail can be rebuilt
        from the original already on disk. That is not hypothetical: thumbnails
        were absent from the set of files ``prune-images`` considered
        referenced, so a prune deleted every one of them while leaving the
        originals it derived them from untouched.

        Returns None when the source cannot be read at all.
        """
        source = self.absolute_path(source_relative)
        thumb_path = self.absolute_path(thumb_relative)

        try:
            with Image.open(source) as opened:
                # Honor the EXIF orientation tag, otherwise phone photos from
                # vendor listings come out rotated in the grid.
                image: PILImage = ImageOps.exif_transpose(opened) or opened
                width, height = image.size

                if max(image.size) <= THUMBNAIL_MAX_EDGE:
                    # Already small: point the thumbnail at the original rather
                    # than writing a second, larger copy of the same picture.
                    return Thumbnail(source_relative, None, width, height)

                image.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
                # Flatten to RGB: JPEG has no alpha channel, and PNGs/WebPs with
                # transparency would otherwise fail to save.
                if image.mode not in ("RGB", "L"):
                    background = Image.new("RGB", image.size, (255, 255, 255))
                    alpha = image.convert("RGBA").split()[-1]
                    background.paste(image.convert("RGB"), mask=alpha)
                    image = background

                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                temp = thumb_path.with_suffix(".part")
                image.save(
                    temp,
                    format="JPEG",
                    quality=THUMBNAIL_QUALITY,
                    optimize=True,
                    progressive=True,
                )
                temp.chmod(FILE_MODE)
                temp.replace(thumb_path)
        except (UnidentifiedImageError, OSError, ValueError):
            # Corrupt, truncated or hostile image data. Keep the original file;
            # the UI simply has no thumbnail for it.
            thumb_path.with_suffix(".part").unlink(missing_ok=True)
            return None

        try:
            size = thumb_path.stat().st_size
        except OSError:
            size = None
        return Thumbnail(thumb_relative, size, width, height)

    def delete(self, relative: str | None) -> None:
        if not relative:
            return
        with contextlib.suppress(ImageStoreError, OSError):
            self.absolute_path(relative).unlink(missing_ok=True)

    # -- maintenance --------------------------------------------------------
    def usage_bytes(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def prune_orphans(self, known: set[str]) -> int:
        """Delete files on disk that no ``item_photos`` row points at."""
        removed = 0
        root = self.root.resolve()
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix == ".part":
                continue
            relative = str(path.relative_to(root))
            if relative not in known:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed
