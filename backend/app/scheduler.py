"""The periodic job that scans sites and sends digests.

A single background thread ticks on a timer. Every tick it asks which sites are
due and which users' digests are due, then hands the work to a small thread pool.
No external broker is involved -- for a dozen sites on a cadence measured in
hours, a broker would be more moving parts than the problem needs.

Scans are the slow part (a browser-driven site takes minutes), so they run on
worker threads bounded by ``scheduler.max_concurrent_scans``. Digests are quick
and run inline on the tick thread.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from .config import Config, get_config
from .database import session_scope
from .models import User
from .services import digest, scan_service

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
            self._stop.wait(tick)

    def tick(self) -> None:
        self._ticks += 1
        self._dispatch_scans()
        if self._seconds_since_digest_check >= self.config.scheduler.digest_tick_seconds:
            self._seconds_since_digest_check = 0.0
            self._dispatch_digests()

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

    # -- introspection ------------------------------------------------------
    def status(self) -> dict[str, object]:
        with self._lock:
            active = sorted(self._inflight)
        return {
            "running": self.running,
            "enabled": self.config.scheduler.enabled,
            "ticks": self._ticks,
            "tick_seconds": self.config.scheduler.tick_seconds,
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
