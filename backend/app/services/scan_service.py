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

import threading
import time
import traceback
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..database import session_scope
from ..models import Item, ItemPhoto, PriceHistory, ScanRun, ScanStatus, Site, utcnow
from ..scrapers import ScrapeCanceled, ScrapeContext, ScrapedItem, ScrapeError, get_scraper
from .image_store import ImageStore

#: Progress lines kept per run. Enough to debug a scrape without unbounded growth.
MAX_LOG_LINES = 500

#: Guards ``_running`` and ``_cancel_flags``.
_lock = threading.Lock()
#: site_id -> ScanRun.id for scans in flight in this process.
_running: dict[int, int] = {}
#: site_id -> event set when an operator asks to stop the run.
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
    item.caliber = scraped.caliber
    item.country = scraped.country
    item.manufacturer = scraped.manufacturer
    item.condition = scraped.condition
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

    session.flush()

    # Record photo URLs now; the bytes are fetched in a later pass so a slow
    # image host cannot stall the reconcile.
    if scraped.image_urls:
        by_url = {photo.source_url: photo for photo in item.photos}
        for position, url in enumerate(scraped.image_urls):
            existing_photo = by_url.pop(url, None)
            if existing_photo is None:
                session.add(ItemPhoto(item_id=item.id, source_url=url, position=position))
            else:
                # Keep display order in sync with the gallery.
                existing_photo.position = position
        # Anything left over is a photo the vendor has removed, or the
        # low-resolution grid thumbnail that the detail pass has now replaced
        # with the real gallery. Drop the row; the file is reclaimed by
        # 'milsurp prune-images'.
        for stale_photo in by_url.values():
            session.delete(stale_photo)
    return item, created, price_dropped


def _mark_delisted(session: Session, site: Site, seen_keys: set[str], seen_at: datetime) -> int:
    """De-list active items the scraper did not return this run."""
    stale = (
        session.execute(select(Item).where(Item.site_id == site.id, Item.is_active.is_(True)))
        .scalars()
        .all()
    )
    count = 0
    for item in stale:
        if item.external_key not in seen_keys:
            item.is_active = False
            item.delisted_at = seen_at
            count += 1
    return count


def _download_photos(
    session: Session,
    site: Site,
    ctx: ScrapeContext,
    config: Config,
    limit: int = 400,
) -> int:
    """Fetch bytes for photo rows that have no file yet."""
    if not config.scraping.download_images:
        return 0
    store = ImageStore(config)
    pending = (
        session.execute(
            select(ItemPhoto)
            .join(Item, Item.id == ItemPhoto.item_id)
            .where(Item.site_id == site.id, ItemPhoto.filename.is_(None))
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if not pending:
        return 0

    ctx.log(f"Downloading {len(pending)} new photo(s)…")
    downloaded = 0
    for index, photo in enumerate(pending):
        if ctx.stopped:
            break
        stored = store.download(ctx.session, site.slug, photo.source_url)
        if stored is None:
            continue
        photo.filename = stored.filename
        photo.thumb_filename = stored.thumb_filename
        photo.content_type = stored.content_type
        photo.bytes = stored.bytes
        photo.thumb_bytes = stored.thumb_bytes
        photo.width = stored.width
        photo.height = stored.height
        photo.downloaded_at = utcnow()
        downloaded += 1
        if (index + 1) % 50 == 0:
            session.commit()
            ctx.log(f"  …{index + 1}/{len(pending)} photos processed.")
    session.commit()
    ctx.log(f"Stored {downloaded} photo(s).")
    return downloaded


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
    count = 0
    for run in orphans:
        if run.site_id in live and run.started_at.replace(tzinfo=UTC) > cutoff:
            continue
        run.status = ScanStatus.FAILED
        run.finished_at = utcnow()
        run.error_message = (
            "Scan did not finish — the application restarted or the run exceeded "
            f"the {config.scheduler.scan_timeout_minutes} minute timeout."
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

    config = get_config()
    started = time.monotonic()

    try:
        with session_scope() as session:
            site = session.get(Site, site_id)
            if site is None:
                raise ScanBusy(f"site {site_id} does not exist")

            scraper = get_scraper(site.slug)
            run = ScanRun(site_id=site.id, trigger=trigger, status=ScanStatus.RUNNING)
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
                """Has this listing already been fully fetched?

                A listing counts as complete once it has a description and at
                least one photo, which is what a detail-page fetch produces.
                """
                row = session.execute(
                    select(Item.id, Item.description).where(
                        Item.site_id == site.id, Item.external_key == external_key
                    )
                ).first()
                if row is None:
                    return True
                item_id, description = row
                if not description:
                    return True
                photo_count = session.execute(
                    select(func.count(ItemPhoto.id)).where(ItemPhoto.item_id == item_id)
                ).scalar_one()
                return photo_count == 0

            ctx = ScrapeContext(
                config,
                progress=log,
                should_stop=cancel.is_set,
                needs_detail=needs_detail,
            )
            seen_at = utcnow()

            try:
                log(f"Starting {site.name} scan ({trigger}).")
                scraped: Iterable[ScrapedItem] = scraper.scrape(ctx)
                scraped_list = list(scraped)
                log(f"Scraper returned {len(scraped_list)} listing(s).")

                # Two listings sharing a key would violate the unique index and
                # abort the whole transaction; last one wins, as with a re-scrape.
                unique: dict[str, ScrapedItem] = {}
                for entry in scraped_list:
                    if entry.external_key:
                        unique[entry.external_key] = entry
                if len(unique) != len(scraped_list):
                    log(f"Collapsed {len(scraped_list) - len(unique)} duplicate key(s).")

                created = updated = drops = changes = 0
                for index, entry in enumerate(unique.values()):
                    ctx.check_stop()
                    _item, was_created, dropped = _upsert_item(session, site, entry, run, seen_at)
                    if was_created:
                        created += 1
                    else:
                        updated += 1
                    if dropped:
                        drops += 1
                    if (index + 1) % 100 == 0:
                        session.commit()
                        log(f"  …{index + 1}/{len(unique)} listings reconciled.")

                session.commit()
                changes = (
                    session.query(PriceHistory).filter(PriceHistory.scan_run_id == run.id).count()
                )

                delisted = _mark_delisted(session, site, set(unique), seen_at)
                session.commit()
                log(
                    f"Reconciled: {created} new, {updated} updated, "
                    f"{delisted} de-listed, {changes} price change(s)."
                )

                images = _download_photos(session, site, ctx, config)

                run.items_found = len(unique)
                run.items_new = created
                run.items_updated = updated
                run.items_delisted = delisted
                run.price_changes = changes
                run.price_drops = drops
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


def due_site_ids(session: Session) -> list[int]:
    """Enabled, available sites whose next scan time has arrived."""
    now = utcnow()
    sites = (
        session.execute(select(Site).where(Site.enabled.is_(True), Site.is_available.is_(True)))
        .scalars()
        .all()
    )
    return [site.id for site in sites if site.next_scan_at is None or site.next_scan_at <= now]
