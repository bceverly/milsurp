"""Runs a site's scraper and reconciles the result into the database.

One public entry point, :func:`run_scan`, which is what the scheduler, the admin
"Scan now" button and the CLI all call. It owns the whole lifecycle of a scan:

1. Open a ``ScanRun`` row in RUNNING state so the UI can show it immediately.
2. Drive the scraper, streaming progress lines into that row.
3. Upsert every returned listing, appending price history only on real changes.
4. Mark anything the scraper did not return as de-listed.
5. Download photos for listings that do not have them yet.
6. Close the run out as SUCCESS, PARTIAL, FAILED or CANCELED.

Only one scan per site runs at a time; a second request for a busy site is
rejected rather than queued, since scans are idempotent and the next tick will
pick it up anyway.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import traceback
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..database import session_scope
from ..models import (
    Item,
    ItemPhoto,
    PriceHistory,
    ScanRun,
    ScanStatus,
    Site,
    as_utc,
    utcnow,
)
from ..scrapers import (
    ScrapeCanceled,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    get_scraper,
    get_scraper_class,
)
from . import armory, classify, discovery, manufacturers
from .image_store import ImageStore, StoredImage

#: Progress lines kept per run. Enough to debug a scrape without unbounded growth.
MAX_LOG_LINES = 500

#: How often to report progress in the scan log. Not how often to commit.
LOG_EVERY = 25

#: How often to say so in the log. Not how often to commit: see below.
LOG_EVERY_PHOTO = 50

#: Stop asking for a photograph after this many failures.
#:
#: A queued photo is a row with no file, so a URL that can never work looks
#: exactly like one not reached yet. Without a ceiling it is retried on every
#: scan for the life of the listing. Three is enough to ride out a bad
#: afternoon — the downloader already retries a 429 within a single attempt —
#: and small enough that a dead URL stops costing anything quickly.
MAX_PHOTO_ATTEMPTS = 3

#: Room for a sentence, not a traceback.
PHOTO_ERROR_CHARS = 500


#: Which sites are being scanned by *this* process, and how to ask them to
#: stop. A separate process — the CLI, say — has its own registry and cannot
#: see this one, which is why reap_stale_runs() treats a RUNNING row it does
#: not recognize as orphaned.
_lock = threading.Lock()

_running: dict[int, int] = {}

_cancel_flags: dict[int, threading.Event] = {}


class ScanBusy(RuntimeError):
    """A scan for this site is already in flight."""


def is_running(site_id: int) -> bool:
    with _lock:
        return site_id in _running


def running_site_ids() -> set[int]:
    with _lock:
        return set(_running)


def request_cancel(site_id: int) -> bool:
    """Ask an in-flight scan to stop at its next checkpoint."""
    with _lock:
        event = _cancel_flags.get(site_id)
    if event is None:
        return False
    event.set()
    return True


class _RunLog:
    """Accumulates progress lines and flushes them to the ScanRun row.

    Flushing is time-based rather than per-line: a scrape emits a line every few
    seconds and each flush is a database write that competes with the API for
    SQLite's write lock.
    """

    def __init__(self, session: Session, run: ScanRun, flush_seconds: float = 3.0) -> None:
        self.session = session
        self.run = run
        self.lines: list[str] = []
        self.flush_seconds = flush_seconds
        self._last_flush = 0.0

    def __call__(self, message: str) -> None:
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        self.lines.append(f"[{stamp}] {message}")
        if len(self.lines) > MAX_LOG_LINES:
            # Keep the beginning (setup) and the end (where failures show up).
            head = self.lines[: MAX_LOG_LINES // 4]
            tail = self.lines[-(MAX_LOG_LINES - MAX_LOG_LINES // 4 - 1) :]
            self.lines = [*head, "… (older lines trimmed) …", *tail]
        if time.monotonic() - self._last_flush >= self.flush_seconds:
            self.flush()

    def flush(self) -> None:
        self.run.log = "\n".join(self.lines)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
        self._last_flush = time.monotonic()


def descriptions_are_reliable(site_slug: str) -> bool:
    """Whether this vendor's prose is about the listing it is attached to.

    Answered from the scraper class, which is the only thing that knows. A site
    whose scraper has been removed keeps whatever its rows already hold, so the
    default is the ordinary one.
    """
    scraper = get_scraper_class(site_slug)
    return bool(getattr(scraper, "descriptions_are_reliable", True))


# ---------------------------------------------------------------------------
# Holding the write lock
# ---------------------------------------------------------------------------
# SQLite has one writer, and this application writes inside loops that go to
# the network between rows. A transaction left open across one of those waits
# holds the write lock for as long as the *vendor* takes to answer, and every
# write the web application attempts meanwhile — signing in updates a last-seen
# timestamp — waits out its busy timeout and fails.
#
# So both loops commit at the end of every iteration, before control goes back
# to the thing that will spend twenty seconds on the network. Not every N rows,
# and not "every N seconds, checked when a row arrives": the second of those
# was tried and does not work, because the dead time is precisely when no row
# is arriving. Ten listings would land in milliseconds, sit below the batch
# size, and then the lock would be held across the twenty-second fetch of the
# next page — with the clock never checked, because checking it happens when a
# row arrives.
#
# Committing per row is affordable here in a way it would not be elsewhere:
# WAL with synchronous=NORMAL makes a commit an append with no fsync, and these
# loops are bounded by the network by orders of magnitude.


def _price_changed(previous: float | None, current: float | None) -> bool:
    if current is None:
        return False
    if previous is None:
        return True
    # Compare in cents: vendors round inconsistently and float equality on
    # parsed decimals is not reliable.
    return round(previous * 100) != round(current * 100)


def _upsert_item(
    session: Session,
    site: Site,
    scraped: ScrapedItem,
    run: ScanRun,
    seen_at: datetime,
) -> tuple[Item, bool, bool]:
    """Insert or update one listing. Returns ``(item, created, price_dropped)``."""
    item = session.execute(
        select(Item).where(Item.site_id == site.id, Item.external_key == scraped.external_key)
    ).scalar_one_or_none()

    created = item is None
    if item is None:
        item = Item(
            site_id=site.id,
            external_key=scraped.external_key,
            first_seen_at=seen_at,
        )
        session.add(item)

    item.url = scraped.url
    item.title = scraped.title
    if scraped.description:
        item.description = scraped.description
    item.category = scraped.category
    # Only what the scraper actually stated, exactly like the description above.
    #
    # These four can come from a *product page*, and a scraper skips the
    # product page of a listing it has already fetched one for — so on every
    # re-scan the same listing arrives with all four empty, meaning "I did not
    # ask" and not "the vendor no longer says". Assigning that unconditionally
    # wiped them and let the heuristics fill the hole: Legacy Collectibles
    # publish "Maker: IMI" in a field of their own, and one scan later their
    # Uzi's manufacturer was **Luger**, read back out of "9mm Luger" in the
    # title. Every bore grade they publish was gone the same way.
    #
    # The cost of this direction is that a vendor who *removes* a value does
    # not clear ours. That is the same trade the description has always made,
    # and `reclassify --recompute` is the way to force a rebuild.
    item.caliber = scraped.caliber or item.caliber
    item.country = scraped.country or item.country
    trusted = descriptions_are_reliable(site.slug)
    item.manufacturer = scraped.manufacturer or item.manufacturer
    item.condition = scraped.condition or item.condition
    item.is_sold = scraped.is_sold
    item.currency = scraped.currency
    if scraped.posted_at:
        item.posted_at = scraped.posted_at
    item.last_seen_at = seen_at

    # A listing that reappears after being de-listed comes back as active, but
    # keeps its original first_seen_at so "new" stays honest.
    if not item.is_active:
        item.is_active = True
        item.delisted_at = None

    price_dropped = False
    if scraped.price is not None and _price_changed(item.current_price, scraped.price):
        item.previous_price = item.current_price
        item.current_price = scraped.price
        item.price_changed_at = seen_at
        item.lowest_price = (
            scraped.price if item.lowest_price is None else min(item.lowest_price, scraped.price)
        )
        item.highest_price = (
            scraped.price if item.highest_price is None else max(item.highest_price, scraped.price)
        )
        session.flush()  # need item.id for the history row
        session.add(
            PriceHistory(
                item_id=item.id,
                scan_run_id=run.id,
                price=scraped.price,
                currency=scraped.currency,
                observed_at=seen_at,
            )
        )
        price_dropped = item.previous_price is not None and scraped.price < item.previous_price

    # Firearm classification happens here, not in the scrapers.
    #
    # It is the same judgment for every vendor, and putting it in the scrapers
    # meant each one had to remember — none did. classify.enrich() returned
    # is_rifle/is_pistol from the very first commit and nothing ever read them
    # onto the row, so every listing on every site sat at the column default of
    # False and the "Rifles" filter matched nothing at all.
    #
    # Doing it here also means it runs against the *merged* record: Royal Tiger
    # yields a listing from the grid with no description and again once the
    # detail page has supplied one, and the second pass reclassifies with the
    # better text.
    derived = classify.enrich(
        item.title,
        item.description,
        item.current_price,
        caliber=item.caliber,
        category=item.category,
        trust_description=trusted,
    )
    item.is_rifle = derived["is_rifle"]
    item.is_pistol = derived["is_pistol"]
    item.is_bayonet = derived["is_bayonet"]
    item.is_parts_kit = derived["is_parts_kit"]
    item.is_police_surplus = derived["is_police_surplus"]

    # And the descriptive fields, where the vendor gave none. Some catalogs
    # publish the caliber as its own field and some write it into the title;
    # a WooCommerce shop has nowhere structured to put it at all, so the first
    # of them read every rifle in as "7.62x54R" in the title and blank in the
    # column. Only the gaps are filled — a value the vendor stated is theirs.
    item.caliber = item.caliber or derived["caliber"]
    item.country = item.country or derived["country"]
    item.condition = item.condition or derived["condition"]

    # The maker last, because the caliber is one of the things that names it —
    # a great many surplus cartridges are called after the firm that designed
    # them — and the caliber is only settled on the line above. Derived first,
    # this read a caliber that was not there yet.
    item.manufacturer = item.manufacturer or manufacturers.extract(
        session,
        item.title,
        item.description if trusted else None,
        item.caliber,
    )
    # Whichever way it arrived, written the way the table writes it. A vendor
    # who states "S&W" is not being argued with -- they are being spelled --
    # and without this the Manufacturer filter offered "S&W" and
    # "Smith & Wesson" as two firms, 25 listings under one and 53 under the
    # other, with no way to ask for both.
    item.manufacturer = manufacturers.canonical(session, item.manufacturer)

    _apply_catalog(session, item, trusted)

    session.flush()

    # Record photo URLs now; the bytes are fetched in a later pass so a slow
    # image host cannot stall the reconcile.
    _reconcile_photos(session, item, scraped)

    if scraped.images_are_complete:
        # The record is complete: description and full gallery. This is the
        # fact ScrapeContext.needs_detail() reads, so it must be set only here.
        item.detail_fetched_at = seen_at

    return item, created, price_dropped


def _apply_catalog(session: Session, item: Item, trusted: bool) -> None:
    """Let the armory correct and complete what the guesses said.

    It outranks them because it is not a guess: somebody who knows the trade
    stated it. Three things happen and a fourth deliberately does not.

    The caliber is *normalized*, so ".32 ACP" and "7.65mm Browning" stop being
    two answers to one question. A caliber and a maker the listing never stated
    are *filled in* from the model it names -- "RUSSIAN M44 CARBINES" says
    neither and is a Mosin-Nagant in 7.62x54R. And the model's kind settles
    rifle-or-handgun, which it does better than the words in the title: a
    flintlock pistol and a percussion revolver are both handguns and neither
    has to spell that out.

    What it will not do is argue with a caliber a dealer stated. Sixty years of
    surplus is full of rebarreled and rechambered guns, and the vendor has the
    thing in their hand.

    Only rows an admin has promoted take part. A pending row is a question
    nobody has answered yet, and a question must not rewrite the armory.
    """
    found = armory.fill_in(session, item.title, item.description if trusted else None, item.caliber)
    # Which model, recorded rather than merely used. Without it the armory
    # shaped a listing and left nothing to say it had: no way to browse the
    # M91/30s, no link to what is known about the gun, and no way to look at a
    # questionable caliber and see where it came from.
    item.firearm_model_id = found.model_id
    if found.caliber:
        item.caliber = found.caliber
    item.manufacturer = item.manufacturer or found.manufacturer
    # Same one-directional fill, and for a sharper reason than the maker. The
    # model's country is where the *pattern* comes from; a listing's is where
    # this particular gun is said to be from, and those genuinely differ -- a
    # K98k assembled in Brno after the war is a German pattern made in
    # Czechoslovakia. Whoever wrote the listing was looking at the gun.
    item.country = item.country or found.country
    # The kind *refines*, it never promotes. The armory knows what a model is;
    # it does not know whether this listing is selling one. "Early style band
    # bolt handle Berthier 1907/15 and M16 bolt assembly" names a rifle and is
    # a bag of bolt parts, and "W+F Bern K31 Pioneer Sawback Bayonet" names a
    # carbine and is a bayonet. The accessory rules in classify.py decide that
    # question and are heavily tested on it; all this does is say which of the
    # two buckets a thing already known to be a firearm belongs in, which it
    # does better than the words can -- a flintlock pistol and a percussion
    # revolver are both handguns and neither has to spell that out.
    if found.kind is not None and (item.is_rifle or item.is_pistol):
        item.is_rifle = found.kind.is_long_gun
        item.is_pistol = found.kind.is_handgun


def _reconcile_photos(session: Session, item: Item, scraped: ScrapedItem) -> None:
    """Bring an item's photo rows in line with what the scraper just saw.

    Bytes are not fetched here: a row without a filename is a job for
    :func:`_download_photos`, so a slow image host cannot stall the reconcile.
    """
    if scraped.generated_images:
        _store_generated_images(session, item, scraped)
        return

    if not scraped.image_urls:
        return

    preview_only = not scraped.images_are_complete
    stored = sorted(item.photos, key=lambda photo: photo.position)

    # Same URLs in the same order means nothing about this gallery has changed:
    # no row to insert, none to prune, and every file already downloaded is
    # still the right one. Returning early keeps a re-scan of an unchanged
    # catalog from generating any image work at all.
    if scraped.image_urls == [photo.source_url for photo in stored]:
        return

    # A catalog-grid preview knows one photo and nothing about the rest, so it
    # has nothing to say about a gallery that has already been collected.
    if preview_only and stored:
        return

    by_url = {photo.source_url: photo for photo in stored}
    for position, url in enumerate(scraped.image_urls):
        existing_photo = by_url.pop(url, None)
        if existing_photo is None:
            session.add(ItemPhoto(item_id=item.id, source_url=url, position=position))
        else:
            # Keep display order in sync with the gallery.
            existing_photo.position = position

    # Anything left over is a photo the vendor has removed. Drop the row; the
    # file is reclaimed by 'milsurp prune-images'.
    #
    # Only ever from a *complete* record. Letting a preview prune would delete
    # a seven-photo gallery down to the grid thumbnail — which is precisely
    # what happened to 207 Royal Tiger listings.
    if not preview_only:
        for stale_photo in by_url.values():
            session.delete(stale_photo)


def _mark_delisted(
    session: Session,
    site: Site,
    seen_keys: set[str],
    seen_at: datetime,
    unread_categories: set[str] | None = None,
) -> int:
    """De-list active items the scraper did not return this run.

    ``unread_categories`` names sections the scraper says it never opened --
    refused by robots.txt, skipped as unchanged, cut short by an error. A
    listing filed under one of those was not *omitted* from the inventory; it
    simply was not looked at, and reading the two the same way is how a partly
    refused scan quietly empties half a catalog.
    """
    skip = unread_categories or set()
    stale = (
        session.execute(select(Item).where(Item.site_id == site.id, Item.is_active.is_(True)))
        .scalars()
        .all()
    )
    count = 0
    for item in stale:
        if item.external_key in seen_keys or item.category in skip:
            continue
        item.is_active = False
        item.delisted_at = seen_at
        count += 1
    return count


def _store_generated_images(session: Session, item: Item, scraped: ScrapedItem) -> None:
    """Persist images a scraper made itself, rather than queueing a download.

    There is no URL to fetch later, so the bytes go to disk now and the row is
    written already complete — which also means _download_photos never sees it.
    The key doubles as the photo's source_url so a re-scan of the same flyer
    recognizes the same crop instead of storing it again — but "the same crop"
    has to mean the same *pixels*, not merely the same key. These images are
    derived by our own code from a page that has not changed, so the thing that
    changes them is a change to the reader: when it learned to include the
    heading above the picture, every crop moved, and skipping on the key alone
    left every listing showing the picture it had been cut before. So the bytes
    are compared, and only an unchanged crop is left alone.
    """
    config = get_config()
    if not config.scraping.download_images:
        return
    store = ImageStore(config)
    existing = {photo.source_url: photo for photo in item.photos}
    for position, (key, data) in enumerate(scraped.generated_images):
        photo = existing.get(key)
        if photo is not None and _same_bytes_on_disk(store, photo, data):
            photo.position = position
            continue
        stored = store.store_bytes(item.site.slug, key, data)
        if stored is None:
            continue
        if photo is None:
            photo = ItemPhoto(item_id=item.id, source_url=key)
            session.add(photo)
        photo.position = position
        photo.filename = stored.filename
        photo.thumb_filename = stored.thumb_filename
        photo.content_type = stored.content_type
        photo.bytes = stored.bytes
        photo.thumb_bytes = stored.thumb_bytes
        photo.width = stored.width
        photo.height = stored.height
        photo.downloaded_at = utcnow()


def _same_bytes_on_disk(store: ImageStore, photo: ItemPhoto, data: bytes) -> bool:
    """Whether the stored file is already exactly these bytes.

    Compared rather than hashed: the file name is derived from the crop's key,
    not from its content, so it says nothing about what is inside. There are a
    few dozen of these per flyer and the scraper runs weekly.
    """
    if not photo.filename or photo.bytes != len(data):
        return False
    try:
        return store.absolute_path(photo.filename).read_bytes() == data
    except OSError:
        return False


def _record_stored_photo(photo: ItemPhoto, stored: StoredImage) -> None:
    """Copy a fetched image's facts onto its row."""
    photo.attempts += 1
    photo.last_error = None
    photo.filename = stored.filename
    photo.thumb_filename = stored.thumb_filename
    photo.content_type = stored.content_type
    photo.bytes = stored.bytes
    photo.thumb_bytes = stored.thumb_bytes
    photo.width = stored.width
    photo.height = stored.height
    photo.downloaded_at = utcnow()


def _report_photo_run(
    ctx: ScrapeContext, attempted: int, downloaded: int, failed: int, discarded: int, exhausted: int
) -> None:
    """Say what happened, and warn only about what changed.

    Two things are said rather than warned. A dropped URL is not a missing
    photograph -- it was never one -- and a run that fetched fewer than it
    tried is already reported by ``failed``. What warns is a failure this run,
    and a photograph that has just run out of retries: both are new, and both
    are things somebody could act on.
    """
    # "Stored 1 photo" out of twenty-three read as success for as long as the
    # failures were silent, so the counts go in the log either way.
    ctx.log(
        f"Stored {downloaded} photo(s)."
        + (f" {failed} could not be fetched; see the log for each." if failed else "")
        # A row disappearing with no line explaining it is how a real bug hides.
        + (f" Dropped {discarded} URL(s) that do not serve a picture." if discarded else "")
    )
    if failed:
        ctx.warn(f"{failed} of {attempted} photo(s) could not be fetched.")
    if exhausted:
        ctx.warn(
            f"{exhausted} photo(s) reached {MAX_PHOTO_ATTEMPTS} failed attempts in this scan "
            f"and will not be retried. Run 'make photos-retry' once the cause is fixed."
        )


def _download_photos(
    session: Session,
    site: Site,
    ctx: ScrapeContext,
    config: Config,
    limit: int | None = None,
) -> int:
    """Fetch bytes for photo rows that have no file yet.

    Only rows with no file, so a photo is downloaded exactly once however many
    times its listing is re-scanned. What is left over after the per-scan
    budget is picked up by the next run.

    Rows that have already failed :data:`MAX_PHOTO_ATTEMPTS` times are left
    alone, and the rest are taken fewest-failures-first. Both matter for the
    same reason: the budget is finite, and without this a few hundred dead URLs
    — a 404, a removed image — sit at the front of an unordered queue and are
    retried on every scan forever, while photographs that would have worked are
    never reached.
    """
    if not config.scraping.download_images:
        return 0
    limit = limit if limit is not None else config.scraping.max_photo_downloads_per_scan
    # Stop is heard during a host's pacing wait, not only between
    # photographs. A host that has asked for a minute between images
    # means this loop is asleep almost all of the time.
    store = ImageStore(config, should_stop=lambda: ctx.stopped)
    waiting = (Item.site_id == site.id, ItemPhoto.filename.is_(None))
    live = (*waiting, ItemPhoto.attempts < MAX_PHOTO_ATTEMPTS)

    outstanding = session.execute(
        select(func.count(ItemPhoto.id)).join(Item, Item.id == ItemPhoto.item_id).where(*live)
    ).scalar_one()
    given_up = session.execute(
        select(func.count(ItemPhoto.id))
        .join(Item, Item.id == ItemPhoto.item_id)
        .where(*waiting, ItemPhoto.attempts >= MAX_PHOTO_ATTEMPTS)
    ).scalar_one()
    if given_up:
        # Said, not warned. **A warning is for something that changed.**
        #
        # This used to warn every scan for as long as the rows existed, and the
        # effect was a site permanently PARTIAL over a condition nobody could
        # act on: Classic Firearms' four recorded scans are four PARTIALs, all
        # of them one photograph of a BM-59 whose file their own CDN has 404'd
        # since 7 September, while their product page still links it. Eleven of
        # its twelve photographs are here. Repeating that every scan does not
        # make it more fixable; it teaches whoever reads the scan list that
        # PARTIAL means nothing.
        #
        # A photo that gives up *during this run* is new information and still
        # warns -- see below. The standing total stays visible here, and on the
        # item, for anyone looking.
        ctx.log(
            f"{given_up} photo(s) previously failed {MAX_PHOTO_ATTEMPTS} times and are no "
            f"longer retried. Run 'make photos-retry' if the cause has been fixed."
        )
    if not outstanding:
        return 0
    pending = (
        session.execute(
            select(ItemPhoto)
            .join(Item, Item.id == ItemPhoto.item_id)
            .where(*live)
            # Fewest failures first, so a row that keeps failing drifts to the
            # back of the queue instead of consuming the budget ahead of one
            # that would succeed.
            .order_by(ItemPhoto.attempts.asc(), ItemPhoto.id.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if not pending:
        return 0

    backlog = outstanding - len(pending)
    ctx.log(
        f"Downloading {len(pending)} new photo(s)…"
        + (
            f" ({backlog} more queued; raise scraping.max_photo_downloads_per_scan,"
            f" or run 'make photos' to drain the rest without re-scraping)"
            if backlog
            else ""
        )
    )
    downloaded = 0
    failed = 0
    #: Rows dropped because their URL does not serve a picture at all.
    discarded = 0
    #: Photos that ran out of retries *during this run*, which is the only
    #: state change worth a warning. See the note above `given_up`.
    exhausted = 0
    for index, photo in enumerate(pending):
        if ctx.stopped:
            break
        result = store.fetch(ctx.session, site.slug, photo.source_url)
        if result.resting:
            # Nothing was asked, so nothing failed. Every photo left in this
            # batch is on the same host, so there is no point walking the rest
            # of them to be told the same thing four hundred times.
            ctx.warn(f"{result.reason}. Leaving the remaining photo(s) queued.")
            break
        photo.last_attempt_at = utcnow()
        stored = result.image
        if stored is None:
            # A URL that does not serve a picture is not a photograph waiting
            # to be fetched, so the row goes rather than joining the queue for
            # good. Not counted as a failure either: nothing is missing from
            # the listing, because there was never a photograph there. See
            # FetchResult.discard.
            if result.discard:
                session.delete(photo)
                session.commit()
                discarded += 1
                continue
            failed += 1
            photo.last_error = (result.reason or "unknown error")[:PHOTO_ERROR_CHARS]
            # Only a failure that will still be true tomorrow counts against
            # the budget. A 429 or a timeout is the shop having a bad
            # afternoon, and letting those accumulate would strand every
            # photograph the afternoon touched — which is precisely what a host
            # cooldown exists to prevent rather than cause.
            if result.permanent:
                photo.attempts += 1
                if photo.attempts >= MAX_PHOTO_ATTEMPTS:
                    exhausted += 1
            session.commit()
            continue
        _record_stored_photo(photo, stored)
        downloaded += 1
        # Same rule: each iteration above went to the network for an image.
        session.commit()
        if (index + 1) % LOG_EVERY_PHOTO == 0:
            ctx.log(f"  …{index + 1}/{len(pending)} photos processed.")
    session.commit()
    _report_photo_run(ctx, len(pending), downloaded, failed, discarded, exhausted)
    return downloaded


def download_pending_photos(
    site_slug: str | None = None,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    retry_failed: bool = False,
) -> int:
    """Fetch the bytes for photo rows that are still waiting for a file.

    A scan caps how many photos it downloads so a first pass over a large
    catalog cannot run for hours, and carries the rest to the next run. That is
    the right default, but it means a backlog drains a scan at a time — and a
    Royal Tiger scan is fifteen minutes of scraping to reach a download step
    whose URLs are already known.

    This is that download step on its own: no browser, no detail pages, no
    re-scrape. Nothing is inserted or de-listed, so it is safe to run at any
    time and safe to interrupt.

    ``retry_failed`` clears the attempt counts first, so photographs that have
    been given up on are tried again. That is the right thing after fixing
    whatever was wrong — a vendor's rate limit, a scraper reading the wrong
    URL — and the wrong thing to do on a schedule, which is why it is a flag
    rather than the default.
    """
    config = get_config()
    log = progress or (lambda _message: None)
    total = 0
    with session_scope() as session:
        sites = session.execute(select(Site).order_by(Site.name)).scalars().all()
        if site_slug:
            sites = [site for site in sites if site.slug == site_slug]
            if not sites:
                raise ScanBusy(f"no site with slug {site_slug!r}")

        if retry_failed:
            result = session.execute(
                update(ItemPhoto)
                .where(
                    ItemPhoto.filename.is_(None),
                    ItemPhoto.attempts > 0,
                    ItemPhoto.item_id.in_(
                        select(Item.id).where(Item.site_id.in_([site.id for site in sites]))
                    ),
                )
                .values(attempts=0, last_error=None)
            )
            # CursorResult in practice; the Result protocol does not promise a
            # row count, and an UPDATE always has one.
            reset = getattr(result, "rowcount", 0)
            session.commit()
            log(f"Retrying {reset} photo(s) that had been given up on.")

        ctx = ScrapeContext(config, progress=log)
        try:
            for site in sites:
                downloaded = _download_photos(session, site, ctx, config, limit=limit)
                if downloaded:
                    log(f"{site.name}: stored {downloaded} photo(s).")
                total += downloaded
        finally:
            ctx.close()
    return total


def _owner_is_alive(host: str | None, pid: int | None) -> bool:
    """Whether the process that claimed a run still exists.

    Only answerable for a run claimed on this machine: a pid means nothing on
    somebody else's. A run from another host is left to the timeout, which is
    the only evidence available about it.
    """
    if not pid or host != socket.gethostname():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, and owned by another user.
        return True
    return True


def _claim_site(site_id: int) -> None:
    """Refuse to start when another *process* is already scanning this site.

    A RUNNING row whose owner has gone — a crash, a kill, a restart — is not a
    claim, and is failed here rather than blocking the site until its timeout.
    """
    config = get_config()
    cutoff = utcnow() - timedelta(minutes=config.scheduler.scan_timeout_minutes)
    with session_scope() as session:
        for run in (
            session.execute(
                select(ScanRun).where(
                    ScanRun.site_id == site_id, ScanRun.status == ScanStatus.RUNNING
                )
            )
            .scalars()
            .all()
        ):
            started = as_utc(run.started_at) or cutoff
            if _owner_is_alive(run.owner_host, run.owner_pid) and started > cutoff:
                with _lock:
                    _running.pop(site_id, None)
                    _cancel_flags.pop(site_id, None)
                raise ScanBusy(
                    f"a scan for site {site_id} is already running "
                    f"(process {run.owner_pid} on {run.owner_host})"
                )
            run.status = ScanStatus.FAILED
            run.finished_at = utcnow()
            run.error_message = (
                "Scan did not finish: the process running it is gone. Anything "
                "already reconciled was saved; the next scan resumes from there."
            )
        session.commit()


def reap_stale_runs(session: Session, config: Config | None = None) -> int:
    """Fail runs left RUNNING by a crash or restart.

    A run is only in ``_running`` for the process that owns it, so on startup any
    RUNNING row is by definition orphaned.
    """
    config = config or get_config()
    cutoff = utcnow() - timedelta(minutes=config.scheduler.scan_timeout_minutes)
    orphans = (
        session.execute(select(ScanRun).where(ScanRun.status == ScanStatus.RUNNING)).scalars().all()
    )
    live = running_site_ids()
    timeout = config.scheduler.scan_timeout_minutes
    count = 0
    for run in orphans:
        # started_at is NOT NULL, so as_utc never returns None here; the
        # fallback keeps the type checker honest without inventing a time.
        started = as_utc(run.started_at) or cutoff
        if run.site_id in live and started > cutoff:
            continue
        # Another process's live scan is not an orphan. Without this the CLI
        # marked the web application's running scan as failed the moment it
        # started, because a RUNNING row it did not own looked abandoned.
        if _owner_is_alive(run.owner_host, run.owner_pid) and started > cutoff:
            continue
        now = utcnow()
        run.status = ScanStatus.FAILED
        run.finished_at = now
        # Say which of the two it was. The old message named both causes and
        # left the reader to guess, which made a 16-minute scan killed by a
        # restart look like a scraper that had hung for two hours.
        minutes = max(0, int((now - started).total_seconds() // 60))
        if started > cutoff:
            run.error_message = (
                f"Scan did not finish: the application stopped or restarted "
                f"{minutes} minute(s) into the run. Anything already reconciled "
                f"was saved; the next scan resumes from there."
            )
        else:
            run.error_message = (
                f"Scan did not finish: it ran for {minutes} minute(s), past the "
                f"{timeout} minute limit (scheduler.scan_timeout_minutes), and "
                f"was abandoned."
            )
        count += 1
    if count:
        session.commit()
    return count


def schedule_next(site: Site, from_time: datetime | None = None) -> None:
    """Set ``next_scan_at`` from the site's interval."""
    base = from_time or utcnow()
    interval = max(5, site.scan_interval_minutes)
    site.next_scan_at = base + timedelta(minutes=interval)


def run_scan(  # noqa: PLR0912,PLR0915 - one linear scan lifecycle; see ROADMAP
    site_id: int, trigger: str = "scheduled"
) -> int:
    """Scan one site start to finish. Returns the ``ScanRun`` id.

    Raises :class:`ScanBusy` when a scan for the site is already in flight.
    """
    cancel = threading.Event()
    with _lock:
        if site_id in _running:
            raise ScanBusy(f"a scan for site {site_id} is already running")
        _running[site_id] = -1
        _cancel_flags[site_id] = cancel

    # ...and again in the database, which is the only thing the CLI and the web
    # application share. The dictionary above is per-process, so without this
    # both would scan the same vendor at once, at twice the request rate its
    # robots.txt asks for. Collectors Firearms answered that with 429s.
    _claim_site(site_id)

    config = get_config()
    started = time.monotonic()

    try:
        with session_scope() as session:
            site = session.get(Site, site_id)
            if site is None:
                raise ScanBusy(f"site {site_id} does not exist")

            scraper = get_scraper(site.slug)
            run = ScanRun(
                site_id=site.id,
                trigger=trigger,
                status=ScanStatus.RUNNING,
                owner_host=socket.gethostname(),
                owner_pid=os.getpid(),
            )
            session.add(run)
            session.commit()
            with _lock:
                _running[site_id] = run.id

            log = _RunLog(session, run)

            if scraper is None:
                site.is_available = False
                run.status = ScanStatus.FAILED
                run.finished_at = utcnow()
                run.error_message = (
                    f"No scraper is registered for '{site.slug}'. The site row is "
                    f"kept for its history but cannot be scanned."
                )
                log(run.error_message)
                log.flush()
                return run.id

            def needs_detail(external_key: str) -> bool:
                """Has this listing already had its detail page fetched?

                Answered from Item.detail_fetched_at, which a scraper sets by
                handing over a complete record. It used to be inferred from
                "has a description and at least one photo row", which is a
                different question and got Royal Tiger badly wrong — see the
                note on the column.
                """
                fetched = session.execute(
                    select(Item.detail_fetched_at).where(
                        Item.site_id == site.id, Item.external_key == external_key
                    )
                ).scalar_one_or_none()
                return fetched is None

            def holds_key_prefix(key_prefix: str) -> bool:
                """Whether anything from this source is stored under this prefix.

                ilike rather than like so the answer does not change with the
                engine: SQLite's LIKE ignores ASCII case and PostgreSQL's does
                not. Both sides of the comparison are built by the same
                scraper, so case never actually differs -- this is about the
                two databases agreeing, not about matching more.
                """
                pattern = key_prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
                return (
                    session.execute(
                        select(Item.id)
                        .where(
                            Item.site_id == site.id, Item.external_key.ilike(pattern, escape="!")
                        )
                        .limit(1)
                    ).scalar_one_or_none()
                    is not None
                )

            # The sections this site already holds listings under, read once
            # before the scan writes anything. A scraper that skips a section
            # on the vendor's word that it has not changed needs to know
            # whether it has ever actually read it -- see
            # ScrapeContext.holds_category().
            stored_categories = {
                category
                for (category,) in session.execute(
                    select(Item.category)
                    .where(Item.site_id == site.id, Item.category.is_not(None))
                    .distinct()
                ).all()
                if category
            }

            ctx = ScrapeContext(
                config,
                progress=log,
                should_stop=cancel.is_set,
                needs_detail=needs_detail,
                already_seen=holds_key_prefix,
                last_success_at=as_utc(site.last_success_at),
                stored_categories=stored_categories,
            )
            seen_at = utcnow()

            try:
                log(f"Starting {site.name} scan ({trigger}).")

                # Consumed as a stream, not collected into a list first.
                #
                # A Royal Tiger scan spends roughly sixteen minutes in the
                # scraper — nine walking seven sections in a browser, seven
                # fetching detail pages. Materialising the whole result before
                # the first INSERT meant that a restart at minute fifteen threw
                # all of it away and the next run started from nothing.
                #
                # Committing in batches as listings arrive means an interrupted
                # scan keeps everything it had reached. The next run then skips
                # what it already has: ScrapeContext.needs_detail() suppresses
                # the detail fetch for any listing that already has a
                # description and a photo, and _download_photos() picks up any
                # photo row still missing its file. Interrupted work is resumed
                # rather than repeated.
                scraped: Iterable[ScrapedItem] = scraper.scrape(ctx)

                # A scraper may yield the same key more than once — Royal Tiger
                # yields each listing from the grid, then again once its detail
                # page has filled in the description and gallery. Later wins,
                # which is what _upsert_item does anyway; the set is only here
                # so the counters and the de-list set stay honest.
                seen_keys: set[str] = set()
                dropped_keys: set[str] = set()
                created = updated = changes = 0
                duplicates = 0
                processed = 0

                for entry in scraped:
                    ctx.check_stop()
                    if not entry.external_key:
                        continue
                    already_seen = entry.external_key in seen_keys
                    _item, was_created, dropped = _upsert_item(session, site, entry, run, seen_at)
                    if already_seen:
                        duplicates += 1
                    elif was_created:
                        created += 1
                    else:
                        updated += 1
                    if dropped:
                        dropped_keys.add(entry.external_key)
                    seen_keys.add(entry.external_key)
                    processed += 1

                    # Before going back to the scraper, which is about to
                    # spend twenty seconds on the network.
                    session.commit()
                    if processed % LOG_EVERY == 0:
                        log(f"  …{len(seen_keys)} listing(s) saved.")

                session.commit()
                log(f"Scraper returned {len(seen_keys)} listing(s).")
                if duplicates:
                    log(f"Collapsed {duplicates} repeated key(s).")

                changes = (
                    session.query(PriceHistory).filter(PriceHistory.scan_run_id == run.id).count()
                )

                # Only reached when the scraper ran to completion. An
                # interrupted stream raises out of the loop above, so a partial
                # result can never de-list the listings it did not get to.
                #
                # A scraper that reported "nothing has changed" deliberately
                # returned no listings, which is not the same as saying the
                # catalog is empty. De-listing on that would wipe the site.
                #
                # Nor is "I could not read any of it". A run that returned
                # *nothing* and warned while doing so has not observed an empty
                # catalog; it has failed to observe one. J&G Sales lost all 64
                # of their listings to that: one Cloudflare 403 on robots.txt
                # denied every section, the stream ended politely with nothing
                # in it, and this read the silence as "the shop is empty".
                #
                # Deliberately narrow. A run that read *some* of the catalog
                # still de-lists what it did not see, which is wrong in the
                # same way and in smaller print -- five sections refused out of
                # nine would de-list those five. Fixing that properly needs a
                # scraper to distinguish "this section was refused" from "this
                # product page was refused", which it cannot yet say.
                held_back = bool(ctx.warnings) and not seen_keys
                if held_back:
                    log(
                        "Nothing was read and the run warned, so no listing is "
                        "being de-listed: an unreadable catalog is not an empty one."
                    )
                if ctx.unread_categories:
                    log(
                        "Not de-listing anything filed under "
                        + ", ".join(sorted(ctx.unread_categories))
                        + ": those sections were not read this run."
                    )
                delisted = (
                    0
                    if ctx.unchanged or held_back
                    else _mark_delisted(session, site, seen_keys, seen_at, ctx.unread_categories)
                )
                session.commit()
                log(
                    f"Reconciled: {created} new, {updated} updated, "
                    f"{delisted} de-listed, {changes} price change(s)."
                )

                _propose_armory_rows(session, site, seen_keys, log)

                images = _download_photos(session, site, ctx, config)

                run.items_found = len(seen_keys)
                run.items_new = created
                run.items_updated = updated
                run.items_delisted = delisted
                run.price_changes = changes
                run.price_drops = len(dropped_keys)
                run.images_downloaded = images
                run.status = ScanStatus.PARTIAL if ctx.warnings else ScanStatus.SUCCESS
                if ctx.warnings:
                    run.error_message = "; ".join(ctx.warnings[:10])
                site.last_success_at = utcnow()
                log(f"Scan finished: {run.status.value}.")

            except ScrapeCanceled:
                run.status = ScanStatus.CANCELED
                run.error_message = "Canceled by an administrator."
                log("Scan canceled.")
            except (ScrapeError, Exception) as exc:
                run.status = ScanStatus.FAILED
                run.error_message = f"{type(exc).__name__}: {exc}"
                log(f"Scan failed: {run.error_message}")
                log(traceback.format_exc(limit=6))
            finally:
                ctx.close()
                run.finished_at = utcnow()
                run.duration_seconds = round(time.monotonic() - started, 2)
                site.last_scan_at = run.finished_at
                schedule_next(site, run.finished_at)
                log.flush()
                session.commit()

            return run.id
    finally:
        with _lock:
            _running.pop(site_id, None)
            _cancel_flags.pop(site_id, None)


#: Keys per SELECT when gathering a scan's listings back. Under SQLite's
#: default 999-variable ceiling with room for the other bound parameters.
_KEYS_PER_QUERY = 500


def _propose_armory_rows(session: Session, site: Site, keys: set[str], log: "_RunLog") -> None:
    """Write down what this scan met and the armory cannot explain.

    At the end, over the listings this run actually touched, rather than per
    listing during the reconcile loop. Two reasons: the loop commits between
    listings to keep the write lock free, and a proposal is worth making from
    the *stored* record -- caliber filled in, rifle-or-handgun settled -- not
    from the raw scrape.

    Everything it writes is pending, so nothing here can change what a scan
    decides about a listing. A failure is a warning rather than a scan failure,
    because the catalog is already saved by this point and losing a run over a
    housekeeping pass would be a poor trade.
    """
    if not keys:
        return
    try:
        # Chunked, because SQLite caps a statement at 999 bound variables by
        # default and a first scan of a large catalog carries more keys than
        # that. Centerfire's 495 fit; SARCO's 429 fit; the next shop need not.
        keys_list = list(keys)
        items: list[Item] = []
        for start in range(0, len(keys_list), _KEYS_PER_QUERY):
            batch = keys_list[start : start + _KEYS_PER_QUERY]
            items.extend(
                session.execute(
                    select(Item).where(Item.site_id == site.id, Item.external_key.in_(batch))
                )
                .scalars()
                .all()
            )
        found = discovery.discover(session, items)
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive; see the docstring
        session.rollback()
        log(f"Could not update the armory queue: {type(exc).__name__}: {exc}")
        return
    if found.total_added:
        log(f"Armory: proposed {found.summary()}, awaiting approval.")


def due_site_ids(session: Session) -> list[int]:
    """Enabled, available sites whose next scan time has arrived."""
    now = utcnow()
    sites = (
        session.execute(select(Site).where(Site.enabled.is_(True), Site.is_available.is_(True)))
        .scalars()
        .all()
    )
    # as_utc, because next_scan_at comes back from SQLite naive while now is
    # aware. Comparing them directly raises TypeError, and the scheduler
    # isolates each tick, so the whole schedule stopped with nothing in the log
    # and a healthy-looking scheduler thread. A NULL means "never scanned",
    # which is why the first scan of each site worked and no later one did.
    return [site.id for site in sites if (due := as_utc(site.next_scan_at)) is None or due <= now]
