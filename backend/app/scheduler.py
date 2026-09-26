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
from concurrent.futures import Future, ThreadPoolExecutor

from .config import Config, get_config
from .database import session_scope
from .models import EmailStatus, User, utcnow
from .services import (
    backup,
    digest,
    hotdeals,
    inbox,
    pushnotify,
    scan_service,
    watchlist,
    watchpoll,
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
        self._dispatch_backup()
        self._dispatch_hot_deals()
        self._dispatch_inbox()

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
                result = inbox.run(session, self.config)
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
                            watchlist.mark_alerted(update.watch, update.item, now)
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
