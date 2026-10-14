"""The periodic job that scans sites and sends digests.

A single background thread ticks on a timer. Every tick it asks which sites are
due and which users' digests are due, then hands the work to a small thread pool.
No external broker is involved -- for a dozen sites on a cadence measured in
hours, a broker would be more moving parts than the problem needs.

Scans are the slow part (a browser-driven site takes minutes), so they run on
worker threads bounded by ``scheduler.max_concurrent_scans``. Digests are quick
and run inline on the tick thread.

Photo downloads get a thread of their own. A scan caps how many images it
fetches so a first pass over a large catalog cannot run for hours, and carries
the remainder forward -- but that left a backlog draining one scan at a time,
which on a daily cadence is days of listings with no pictures. The photo worker
keeps working through the queue between scans, on its own single thread so it
can never occupy a scan slot.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select

from .config import Config, get_config
from .database import session_scope
from .models import EmailPreference, EmailStatus, User, utcnow
from .services import (
    backup,
    collection,
    digest,
    hotdeals,
    inbox,
    marketreport,
    pushnotify,
    scan_service,
    scanalerts,
    wantlist,
    watchlist,
    watchpoll,
    wishlist,
)

log = logging.getLogger("milsurp.scheduler")


class Scheduler:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._inflight: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._ticks = 0
        self._seconds_since_digest_check = 0.0
        self._seconds_since_watch_poll = 0.0
        #: A single worker, kept apart from the scan pool: photo downloading is
        #: long and low priority, and must never hold a slot a due scan needs.
        self._photo_pool: ThreadPoolExecutor | None = None
        self._photo_future: Future | None = None
        self._seconds_since_photo_check = 0.0
        #: And one more, for the slow reference work: new-gun prices and the
        #: caliber data. Kept off the photo worker since 2026-10-11, when the
        #: first caliber refresh -- an hour of polite requests -- was found
        #: holding 1,551 photos in the queue behind it.
        self._background_pool: ThreadPoolExecutor | None = None
        #: New-gun prices from gun.deals: asked on the reference worker, at most
        #: hourly, and only for variants a day stale. See services/newprices.
        self._newprice_future: Future | None = None
        #: An hour after start, not at it: a restart is not a reason to ask.
        self._last_new_prices: float = time.monotonic()
        #: Caliber data (services/ammunition): looked at once a minute, so
        #: "Refresh now" starts within one; run on the reference worker.
        self._ammo_future: Future | None = None
        self._last_ammo_look: float = 0.0
        #: The manufacturers' own sites (services/makerjobs), asked for from
        #: Site settings: looked for once a minute, run on the reference worker.
        self._maker_future: Future | None = None
        self._last_maker_look: float = 0.0
        self._last_ammo_articles: float = 0.0
        #: When a market report was last attempted per reader, so a failed
        #: delivery is retried hourly rather than on every tick.
        self._market_report_tried: dict[int, datetime] = {}

    # -- lifecycle ----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        if not self.config.scheduler.enabled:
            log.info("Scheduler is disabled in the configuration file.")
            return
        self._stop.clear()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, self.config.scheduler.max_concurrent_scans),
            thread_name_prefix="milsurp-scan",
        )
        self._photo_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="milsurp-photos")
        self._background_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="milsurp-reference"
        )
        self._thread = threading.Thread(target=self._loop, name="milsurp-scheduler", daemon=True)
        self._thread.start()
        log.info(
            "Scheduler started (tick %ss, %s concurrent scans).",
            self.config.scheduler.tick_seconds,
            self.config.scheduler.max_concurrent_scans,
        )

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._pool is not None:
            # Don't block shutdown on a scan that may take minutes; the run is
            # reaped and marked failed on the next start.
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
        if self._photo_pool is not None:
            # Interrupting a photo batch costs nothing: every image already
            # downloaded keeps its file, and the rest stay queued.
            self._photo_pool.shutdown(wait=False, cancel_futures=True)
            self._photo_pool = None
            self._photo_future = None
        if self._background_pool is not None:
            # A refresh interrupted here is asked again: what it finished is
            # saved, and the next start finds it due.
            self._background_pool.shutdown(wait=False, cancel_futures=True)
            self._background_pool = None
        log.info("Scheduler stopped.")

    # -- the loop -----------------------------------------------------------
    def _loop(self) -> None:
        # Clean up anything a previous process left mid-flight before deciding
        # what is due, so a crashed scan does not block its site forever.
        try:
            with session_scope() as session:
                reaped = scan_service.reap_stale_runs(session, self.config)
                if reaped:
                    log.warning("Reaped %s interrupted scan run(s).", reaped)
        except Exception:
            log.exception("Failed to reap stale scan runs")

        tick = max(5, self.config.scheduler.tick_seconds)
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # A scheduler thread that dies stops all automation, so every
                # tick is isolated.
                log.exception("Scheduler tick failed")
            self._seconds_since_digest_check += tick
            self._seconds_since_photo_check += tick
            self._seconds_since_watch_poll += tick
            self._stop.wait(tick)

    def tick(self) -> None:
        self._ticks += 1
        self._dispatch_scans()
        if self._seconds_since_photo_check >= self.config.scheduler.photo_tick_seconds:
            self._seconds_since_photo_check = 0.0
            self._dispatch_photos()
        if self._seconds_since_digest_check >= self.config.scheduler.digest_tick_seconds:
            self._seconds_since_digest_check = 0.0
            self._dispatch_digests()
        # Re-read watched listings on their own clock, well ahead of the daily
        # catalog scan: the alert below can only be as fresh as the price it
        # reads, and this is what makes that price fresh.
        if self._seconds_since_watch_poll >= self.config.scheduler.watch_poll_seconds:
            self._seconds_since_watch_poll = 0.0
            self._dispatch_watch_poll()
        # Every tick, not on the digest's timer. What makes an alert due is a
        # price changing, which happens when a scan or the poll above finds it
        # -- and the whole point of asking for one is not waiting for the next
        # digest. The check is a single indexed query returning nothing on
        # almost every tick.
        self._dispatch_watch_alerts()
        # And want lists, on the same terms: a listing coming to match one is
        # found by a scan or the poll, and the point of the alert is not
        # waiting for the digest.
        self._dispatch_want_alerts()
        # And wishlists whose readers asked to hear the moment one changes.
        self._dispatch_wishlist_alerts()
        # A shop whose scans have kept failing past the grace period is
        # mailed once. Cheap when nothing is: one query over the sites table.
        self._report_failing_shops()
        # A week after the last one, each reader's collection is valued and
        # kept, so its worth can be charted. Cheap when nothing is due: one
        # grouped query.
        self._dispatch_collection_snapshot()
        self._dispatch_market_report()
        self._dispatch_backup()
        self._dispatch_hot_deals()
        self._dispatch_inbox()
        self._dispatch_offer_endings()
        self._dispatch_new_prices()
        self._dispatch_ammunition()
        self._dispatch_maker_jobs()

    # -- new-gun prices -----------------------------------------------------
    #: Seconds between looks for variants whose new price is a day old.
    NEW_PRICE_EVERY = 3600
    #: Variants asked about per run, each a request or two at a polite pace.
    NEW_PRICE_BATCH = 60

    def _dispatch_new_prices(self) -> None:
        """Ask gun.deals what the due variants cost new. See services/newprices.

        On the reference worker, which is single and low priority, so it can
        never hold a slot a scan needs or a photo's turn; and never a second
        run while one is going.
        """
        now = time.monotonic()
        if now - self._last_new_prices < self.NEW_PRICE_EVERY:
            return
        with self._lock:
            if self._newprice_future is not None and not self._newprice_future.done():
                return
            if self._background_pool is None:
                return
            self._last_new_prices = now
            self._newprice_future = self._background_pool.submit(self._ask_new_prices)

    def _ask_new_prices(self) -> None:
        from .scrapers.base import ScrapeContext
        from .services import newprices

        ctx = ScrapeContext(self.config)
        try:
            with session_scope() as session:
                counts = newprices.run(
                    session, ctx, limit=self.NEW_PRICE_BATCH, log=lambda _message: None
                )
            if counts["asked"]:
                log.info("New-gun prices: %s", counts)
        except Exception:
            log.exception("New-gun price run raised")
        finally:
            ctx.close()

    # -- caliber data -------------------------------------------------------
    AMMO_LOOK_EVERY = 60
    AMMO_ARTICLES_EVERY = 3600

    def _dispatch_ammunition(self) -> None:
        """Refresh the caliber data when it is due or was asked for, and read
        any new or edited caliber's Wikipedia facts hourly in between.

        Due is measured from the settings row's ``last_run_at`` and its
        frequency (daily, weekly or every 2 weeks), for the reason hot deals
        are: a timer would reset on every restart. Never a second run while
        one is going, and on the reference worker so it holds neither a scan's
        slot nor a photo's turn.
        """
        now = time.monotonic()
        if now - self._last_ammo_look < self.AMMO_LOOK_EVERY:
            return
        self._last_ammo_look = now
        with self._lock:
            if self._ammo_future is not None and not self._ammo_future.done():
                return
            if self._background_pool is None:
                return
        from .services import ammunition

        try:
            with session_scope() as session:
                parts = ammunition.due_parts(session)
                asked = ammunition.settings(session).requested_at is not None
        except Exception:
            log.exception("Caliber data: could not read the settings")
            return
        articles = now - self._last_ammo_articles >= self.AMMO_ARTICLES_EVERY
        if not parts and not articles:
            return
        self._last_ammo_articles = now
        with self._lock:
            if self._background_pool is None:
                return
            self._ammo_future = self._background_pool.submit(self._refresh_ammunition, parts, asked)

    def _dispatch_maker_jobs(self) -> None:
        """Run a read of the manufacturers' sites somebody asked for on Site
        settings: one at a time, on the reference worker, within a minute."""
        now = time.monotonic()
        if now - self._last_maker_look < self.AMMO_LOOK_EVERY:
            return
        self._last_maker_look = now
        with self._lock:
            if self._maker_future is not None and not self._maker_future.done():
                return
            if self._background_pool is None:
                return
        from .services import makerjobs

        try:
            with session_scope() as session:
                asked = makerjobs.requested(session)
        except Exception:
            log.exception("Manufacturer data: could not read the requests")
            return
        if not asked:
            return
        with self._lock:
            if self._background_pool is None:
                return
            self._maker_future = self._background_pool.submit(self._run_maker_job, asked[0])

    def _run_maker_job(self, name: str) -> None:
        from .scrapers.base import ScrapeContext
        from .services import makerjobs

        ctx = ScrapeContext(self.config)
        try:
            with session_scope() as session:
                summary = makerjobs.run(session, ctx, name, log=lambda _message: None)
            log.info("Manufacturer data (%s): %s", name, summary)
        except Exception:
            log.exception("Manufacturer data (%s) raised", name)
        finally:
            ctx.close()

    def _refresh_ammunition(self, parts: tuple[str, ...], asked: bool = False) -> None:
        """Refresh *parts* of the caliber data, or with none, read the
        Wikipedia facts of new and edited calibers. A refresh someone *asked*
        for reads every article again rather than only the unread ones."""
        from .scrapers.base import ScrapeContext
        from .services import ammunition, wikipedia

        fetch = wikipedia.http_fetch()
        quiet = lambda _message: None  # noqa: E731
        try:
            if not parts:
                with session_scope() as session:
                    ammunition.refresh_articles(session, fetch, limit=60, log=quiet)
                return
            ctx = ScrapeContext(self.config)
            try:
                with session_scope() as session:
                    summary = ammunition.refresh(
                        session, ctx, fetch=fetch, log=quiet, parts=parts, reread=asked
                    )
                log.info("Caliber data: %s", summary)
            finally:
                ctx.close()
        except Exception:
            log.exception("Caliber data refresh raised")

    # -- hot deals ----------------------------------------------------------
    def _dispatch_hot_deals(self) -> None:
        """Re-read the catalog for bargains, then tell whoever asked to hear.

        Checked on every tick rather than on a timer of its own, for the reason
        backups are: what makes a pass due is the age of the last one, recorded
        on the settings row, and a timer would reset on every restart. The
        check is a single row read returning False on almost every tick.

        **The mail goes out in the same breath as the pass, not on a clock of
        its own.** What makes a hot-deal email due is the arrival of a hot deal,
        and a reader asking to hear about bargains is not asking to hear about
        them six hours after they were found.

        The pass runs on the tick thread. It is arithmetic over rows already in
        the database -- measured at half a second against nine thousand
        listings -- so a worker would be more moving parts than the problem
        needs. See services/hotdeals.
        """
        try:
            with session_scope() as session:
                if not hotdeals.is_due(session):
                    return
                result = hotdeals.refresh(session)
                hotdeals.forget_stale_notices(session)
        except Exception as exc:
            # Never let this stop the scans. It is logged, recorded on the
            # settings row for the page to show, and the next tick tries again.
            log.exception("Hot deals refresh failed")
            try:
                with session_scope() as session:
                    hotdeals.record_failure(session, exc)
            except Exception:
                log.exception("Could not record the hot deals failure")
            return

        log.info(
            "Hot deals: %s found from %s considered listing(s) in %.2fs.",
            result.found,
            result.considered,
            result.seconds,
        )
        self._mail_hot_deals()

    # -- vendor mailing lists -------------------------------------------------
    def _dispatch_inbox(self) -> None:
        """Check the notification account's inbox for the shops' mail, when due.

        Due-ness is one row read, false on almost every tick, like hot deals.
        The check itself is a read-only IMAP session of a few seconds, run on
        the tick thread. A failure is recorded on the settings row for the page
        and never stops the scans. See services/inbox.
        """
        try:
            with session_scope() as session:
                if not inbox.is_due(session):
                    return
                result = inbox.run_exclusive(session, self.config)
                if result is None:
                    return  # a check started from the page is running
        except Exception as exc:
            log.exception("Inbox check failed")
            try:
                with session_scope() as session:
                    inbox.record_failure(session, exc)
            except Exception:
                log.exception("Could not record the inbox failure")
            return
        log.info(
            "Inbox: %s (%s message(s) looked at, %s new from the shops; %s link(s) "
            "followed, %s listing(s) re-read, %s price(s) changed, %s scan(s) queued).",
            result.status,
            result.looked_at,
            result.recorded,
            result.links,
            result.rechecked,
            result.prices_changed,
            result.scans_queued,
        )
        # A price an email moved is news now, not at the next hot-deal pass up
        # to eight hours away. Watchlist alerts need nothing: they run every
        # tick and read the stored price.
        if result.prices_changed:
            self._refresh_hot_deals_now()

    def _dispatch_offer_endings(self) -> None:
        """Re-look at shops whose emailed sale ended an hour ago. One indexed
        query that finds nothing on almost every tick; see
        inbox.settle_ended_offers."""
        try:
            with session_scope() as session:
                settled = inbox.settle_ended_offers(session, self.config)
        except Exception:
            log.exception("Settling ended offers failed")
            return
        if settled:
            log.info("Offers: %s ended sale(s) re-checked.", settled)

    def _refresh_hot_deals_now(self) -> None:
        try:
            with session_scope() as session:
                if not hotdeals.settings(session).enabled:
                    return
                hotdeals.refresh(session)
                hotdeals.forget_stale_notices(session)
        except Exception:
            log.exception("Hot deals refresh after the inbox failed")
            return
        self._mail_hot_deals()

    def _mail_hot_deals(self) -> None:
        """One email per subscriber, each in its own session.

        Two passes like the watch alerts: the first asks only *who*, because
        the rows it loads belong to a session that closes with it, and the
        second re-reads inside the session that will do the marking.

        Marked only after the send returns, so a failure is retried on the next
        pass rather than recorded as delivered -- the one ordering that matters
        when the thing being promised is an email.
        """
        try:
            with session_scope() as session:
                user_ids = hotdeals.subscribed_user_ids(session)
        except Exception:
            log.exception("Could not determine who wants hot deals")
            return

        for user_id in user_ids:
            if self._stop.is_set():
                return
            try:
                with session_scope() as session:
                    user = session.get(User, user_id)
                    if user is None:
                        continue
                    fresh = hotdeals.unsent_for(session, user)
                    if not fresh:
                        continue
                    result = digest.send_hot_deals(session, user, fresh, self.config)
                    if result.status is EmailStatus.SENT:
                        hotdeals.mark_sent(session, user, fresh)
                        row = hotdeals.preference(session, user)
                        row.last_sent_at = utcnow()
                        session.commit()
                    log.info(
                        "Hot deals for %s: %s (%s listing(s)).",
                        user.username,
                        result.status.value,
                        len(fresh),
                    )
            except Exception:
                log.exception("Hot deals email for user %s raised", user_id)

    # -- backups ------------------------------------------------------------
    def _dispatch_backup(self) -> None:
        """Take a snapshot if one is due.

        Checked on every tick rather than on a timer of its own, because what
        makes a backup due is the age of the last one on disk. A process that
        restarts twice a day should still produce one backup a day, and a
        process that was down when a timer would have fired should take one as
        soon as it comes back.
        """
        try:
            with session_scope() as session:
                if not backup.is_due(session, self.config):
                    return
                backup.run(session, self.config)
        except Exception:
            # Never let a failed backup stop the scans. It is logged, recorded
            # on the settings row for the admin page to show, and the next tick
            # tries again.
            log.exception("Database backup failed")

    # -- scans --------------------------------------------------------------
    def _dispatch_scans(self) -> None:
        with self._lock:
            for site_id, future in list(self._inflight.items()):
                if future.done():
                    self._inflight.pop(site_id, None)

        with session_scope() as session:
            due = scan_service.due_site_ids(session)
        if not due:
            return

        for site_id in due:
            with self._lock:
                if site_id in self._inflight or self._pool is None:
                    continue
                future = self._pool.submit(self._run_scan, site_id)
                self._inflight[site_id] = future

    def _run_scan(self, site_id: int) -> None:
        try:
            run_id = scan_service.run_scan(site_id, trigger="scheduled")
            log.info("Scan run %s finished for site %s.", run_id, site_id)
        except scan_service.ScanBusy:
            log.debug("Site %s already scanning; skipping.", site_id)
        except Exception:
            log.exception("Scan for site %s raised", site_id)

    # -- photos -------------------------------------------------------------
    def _dispatch_photos(self) -> None:
        """Keep working through the photo queue between scans.

        One batch at a time, and never a second one while the first is still
        going: the point is to drain the backlog steadily in the background,
        not to open a hundred connections to a vendor at once.
        """
        with self._lock:
            if self._photo_future is not None and not self._photo_future.done():
                return
            if self._photo_pool is None:
                return
            self._photo_future = self._photo_pool.submit(self._drain_photos)

    def _drain_photos(self) -> None:
        try:
            downloaded = scan_service.download_pending_photos()
            if downloaded:
                log.info("Downloaded %s queued photo(s).", downloaded)
        except Exception:
            log.exception("Photo download batch raised")

    # -- digests ------------------------------------------------------------
    def _dispatch_digests(self) -> None:
        try:
            with session_scope() as session:
                user_ids = digest.due_user_ids(session)
        except Exception:
            log.exception("Could not determine which digests are due")
            return

        for user_id in user_ids:
            if self._stop.is_set():
                return
            try:
                with session_scope() as session:
                    user = session.get(User, user_id)
                    if user is None:
                        continue
                    result = digest.send_digest_for_user(session, user, self.config)
                    log.info(
                        "Digest for %s: %s (%s new, %s drops).",
                        user.username,
                        result.status.value,
                        result.new_item_count,
                        result.price_drop_count,
                    )
            except Exception:
                log.exception("Digest for user %s raised", user_id)

    def _dispatch_watch_poll(self) -> None:
        """Re-read the listings people are watching.

        Isolated like every other dispatch: a shop refusing one page must not
        stop the scans, and the poller itself already swallows a refusal per
        listing so one bad page does not end the pass.
        """
        try:
            with session_scope() as session:
                result = watchpoll.run(session, self.config)
        except Exception:
            log.exception("Watch poll failed")
            return
        if result.checked or result.failed:
            log.info(
                "Watch poll: checked %s, %s changed, %s sold, %s skipped, %s failed.",
                result.checked,
                result.changed,
                result.sold,
                result.skipped,
                result.failed,
            )

    def _dispatch_watch_alerts(self) -> None:
        """Mail anybody whose watched listing has reached their target.

        Each user in their own session, the way digests are: one reader's mail
        failing must not cost the others theirs.

        The watch is marked only after the send returns, so a failure is
        retried on the next tick rather than recorded as delivered -- the one
        ordering that matters here, because the thing being promised is an
        email somebody is waiting for.
        """
        # Two passes, and the first one only asks *who*. The ORM rows it loads
        # belong to a session that closes with it, and the send needs live ones
        # to mark afterwards -- so the second pass re-reads inside the session
        # that will do the marking, which also re-checks the answer against a
        # price that may have moved in between.
        try:
            with session_scope() as session:
                user_ids = sorted(watchlist.due_alerts(session))
        except Exception:
            log.exception("Could not determine which watch alerts are due")
            return

        for user_id in user_ids:
            if self._stop.is_set():
                return
            try:
                with session_scope() as session:
                    user = session.get(User, user_id)
                    if user is None:
                        continue
                    fresh = watchlist.due_alerts(session).get(user_id, [])
                    if not fresh:
                        continue
                    result = digest.send_watch_alert(session, user, fresh, self.config)
                    # And every browser this reader has signed up. Push is the
                    # alternative channel rather than a second copy of the
                    # same one: somebody who asked to be told the moment a
                    # rifle reaches a price is not served by an email they
                    # read when they next open a laptop.
                    pushed = pushnotify.send_to_user(
                        session, user, pushnotify.watch_alert_payload(fresh), self.config
                    )
                    # Either channel is enough. Requiring the email would mean
                    # an installation with no SMTP could never mark an alert
                    # delivered and would re-send it on every tick forever.
                    if result.status is EmailStatus.SENT or pushed:
                        now = utcnow()
                        for update in fresh:
                            watchlist.mark_update(update, now)
                    session.commit()
                    log.info(
                        "Watch alert for %s: email %s, %s device(s) (%s listing(s)).",
                        user.username,
                        result.status.value,
                        pushed,
                        len(fresh),
                    )
            except Exception:
                log.exception("Watch alert for user %s raised", user_id)

    def _report_failing_shops(self) -> None:
        """Mail "stopped scraping" for shops failing longer than the grace."""
        grace = timedelta(minutes=self.config.scheduler.scan_alert_grace_minutes)
        try:
            with session_scope() as session:
                told = scanalerts.report_overdue(session, grace)
        except Exception:
            log.exception("Could not report failing shops")
            return
        for slug in told:
            log.info("Administrators told: %s stopped scraping.", slug)

    def _dispatch_wishlist_alerts(self) -> None:
        """Tell anybody with wishlist alerts on what changed. See services/wishlist.

        The watch alerts' shape: who in one pass, then each reader in their own
        session that re-reads, sends, and marks only after a channel delivered.
        """
        try:
            with session_scope() as session:
                user_ids = sorted(wishlist.due_alerts(session))
        except Exception:
            log.exception("Could not determine which wishlist alerts are due")
            return

        for user_id in user_ids:
            if self._stop.is_set():
                return
            try:
                with session_scope() as session:
                    user = session.get(User, user_id)
                    if user is None:
                        continue
                    fresh = wishlist.due_alerts(session).get(user_id, [])
                    if not fresh:
                        continue
                    result = digest.send_watch_alert(
                        session, user, fresh, self.config, wishlist_alert=True
                    )
                    pushed = pushnotify.send_to_user(
                        session, user, pushnotify.wishlist_alert_payload(fresh), self.config
                    )
                    if result.status is EmailStatus.SENT or pushed:
                        now = utcnow()
                        for update in fresh:
                            wishlist.mark_told(update.entry, update.item, now)
                    session.commit()
                    log.info(
                        "Wishlist alert for %s: email %s, %s device(s) (%s listing(s)).",
                        user.username,
                        result.status.value,
                        pushed,
                        len(fresh),
                    )
            except Exception:
                log.exception("Wishlist alert for user %s raised", user_id)

    def _dispatch_want_alerts(self) -> None:
        """Tell anybody whose want list has a new match. See services/wantlist.

        The same shape as the watch alerts above, for the same reasons: who in
        one pass, then each reader in a session of their own that re-reads
        the answer, sends, and marks only after the send returns.
        """
        try:
            with session_scope() as session:
                user_ids = sorted(wantlist.due(session))
        except Exception:
            log.exception("Could not determine which want-list alerts are due")
            return

        for user_id in user_ids:
            if self._stop.is_set():
                return
            try:
                with session_scope() as session:
                    user = session.get(User, user_id)
                    if user is None or not user.is_active:
                        continue
                    wants = wantlist.due(session).get(user_id, [])
                    if not wants:
                        continue
                    result = digest.send_want_alert(session, user, wants, self.config)
                    pushed = pushnotify.send_to_user(
                        session, user, pushnotify.want_alert_payload(wants), self.config
                    )
                    # Either channel is enough, as for a watch alert.
                    if result.status is EmailStatus.SENT or pushed:
                        wantlist.mark(session, wants)
                    session.commit()
                    log.info(
                        "Want-list alert for %s: email %s, %s device(s) (%s listing(s)).",
                        user.username,
                        result.status.value,
                        pushed,
                        sum(want.total for want in wants),
                    )
            except Exception:
                log.exception("Want-list alert for user %s raised", user_id)

    def _dispatch_collection_snapshot(self) -> None:
        """Record collections' worth where a week has passed. See services/collection."""
        try:
            with session_scope() as session:
                recorded = collection.snapshot_due(session)
                session.commit()
        except Exception:
            log.exception("Collection snapshot failed")
            return
        if recorded:
            log.info("Recorded the worth of %s collection row(s).", recorded)

    def _dispatch_market_report(self) -> None:
        """On the first of the month, mail the market report to whoever asked.

        Marked as sent whatever came of it except a failed delivery: a month
        with too little history to report is that month's answer, and asking
        again every tick would only ask the same question. A failure is tried
        again an hour later rather than every tick.
        """
        now = utcnow()
        if not marketreport.due(now):
            return
        try:
            with session_scope() as session:
                rows = (
                    session.execute(
                        select(EmailPreference).where(EmailPreference.market_report.is_(True))
                    )
                    .scalars()
                    .all()
                )
                month = (now.year, now.month)
                waiting = [
                    row.user_id
                    for row in rows
                    if row.market_report_sent_at is None
                    or (row.market_report_sent_at.year, row.market_report_sent_at.month) != month
                ]
        except Exception:
            log.exception("Could not determine who is due a market report")
            return
        for user_id in waiting:
            if self._stop.is_set():
                return
            tried = self._market_report_tried.get(user_id)
            if tried is not None and (now - tried).total_seconds() < 3600:
                continue
            self._market_report_tried[user_id] = now
            try:
                with session_scope() as session:
                    user = session.get(User, user_id)
                    if user is None or not user.is_active or user.email_preference is None:
                        continue
                    entry = marketreport.send(session, user, self.config, now)
                    if entry.status is not EmailStatus.FAILED:
                        user.email_preference.market_report_sent_at = now
                    session.commit()
                    log.info("Market report for %s: %s", user.username, entry.status.value)
            except Exception:
                log.exception("Market report for user %s raised", user_id)

    # -- introspection ------------------------------------------------------
    def status(self) -> dict[str, object]:
        with self._lock:
            active = sorted(self._inflight)
        return {
            "running": self.running,
            "enabled": self.config.scheduler.enabled,
            "ticks": self._ticks,
            "tick_seconds": self.config.scheduler.tick_seconds,
            "photo_tick_seconds": self.config.scheduler.photo_tick_seconds,
            "downloading_photos": self._photo_future is not None and not self._photo_future.done(),
            "digest_tick_seconds": self.config.scheduler.digest_tick_seconds,
            "max_concurrent_scans": self.config.scheduler.max_concurrent_scans,
            "scanning_site_ids": active,
        }


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
