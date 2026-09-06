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
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import Image as PILImage

from ..config import Config

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


def _is_public_url(url: str) -> bool:
    """Reject anything that is not a plain public HTTP(S) URL.

    Image URLs come from third-party markup, so fetching one is a server-side
    request driven by untrusted input -- textbook SSRF. Only http/https to a
    publicly routable address is allowed, which keeps a malicious listing from
    making the scanner probe localhost, link-local metadata endpoints
    (169.254.169.254) or anything else on the internal network.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return False
    return True


class ImageStore:
    def __init__(self, config: Config) -> None:
        self.root = config.images_path
        self.config = config

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
    def download(
        self, session: requests.Session, site_slug: str, source_url: str
    ) -> StoredImage | None:
        """Fetch one image, store it, and generate its thumbnail.

        Returns ``None`` when the download fails, the URL is not safe to fetch,
        or the response is not a decodable image. A missing photo is never worth
        failing a scan over.
        """
        if not _is_public_url(source_url):
            return None

        try:
            response = session.get(
                source_url,
                timeout=self.config.scraping.request_timeout,
                stream=True,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        extension = ALLOWED_CONTENT_TYPES.get(content_type)
        if extension is None:
            # Some hosts serve images as application/octet-stream; fall back to
            # the URL's own extension, but only if it is one we accept.
            guessed = mimetypes.guess_type(source_url)[0]
            extension = ALLOWED_CONTENT_TYPES.get(guessed or "")
            if extension is None:
                response.close()
                return None
            content_type = guessed or "image/jpeg"

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
            response.close()
            return None

        relative = self._relative_path(site_slug, source_url, extension)
        target = self.absolute_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            target.parent.chmod(DIR_MODE)

        # Write to a temporary file first so an interrupted download never
        # leaves a truncated image that later looks cached and complete.
        temp = target.with_suffix(target.suffix + ".part")
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
        except (OSError, ImageStoreError, requests.RequestException):
            temp.unlink(missing_ok=True)
            return None
        finally:
            response.close()

        stored = StoredImage(filename=relative, content_type=content_type, bytes=written)
        self._make_thumbnail(stored, site_slug, source_url)
        return stored

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
