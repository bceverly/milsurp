"""A shared "leave this host alone for a while" register.

Every fetching path in the application consults this before making a request
and reports to it when a host refuses one. That is the point: the pace a scan
learns used to die with the process, so the scheduler, the CLI and a
``make photos`` run each rediscovered the same rate limit separately, and from
the vendor's side that is several crawlers ignoring the same instruction.

Two decisions worth stating.

**Per host, not per site.** A rate limiter counts requests to a hostname; a
vendor's catalog pages and their uploads directory are usually the same one,
and where they are not, the CDN in front of both is what is counting.

**Reads are cached for a moment.** This is consulted before every request, and
a scan makes thousands. A few seconds of staleness cannot matter — the shortest
cooldown is a minute — and it keeps a hot loop off the database, which on
SQLite is a lock this application has already been bitten by once.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import delete, select

from ..database import session_scope
from ..models import HostCooldown, as_utc, utcnow

log = logging.getLogger("milsurp.cooldown")

#: The first wait, and the ceiling it doubles towards.
#:
#: The floor is a minute because anything shorter is not a cooldown, it is a
#: retry — and the fetchers already retry within a request. The ceiling is an
#: hour because a scan that finds a host paused reports it and moves on, so a
#: longer pause only delays the next honest attempt.
MIN_COOLDOWN = timedelta(minutes=1)
MAX_COOLDOWN = timedelta(hours=1)

#: How long a cached answer is trusted.
CACHE_SECONDS = 5.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, float | None]] = {}

#: Whether the register has already complained about being unreachable. It is
#: consulted before every request, so a broken one must not write a line per
#: fetch.
_warned = False


def _unavailable(exc: Exception, doing: str) -> None:
    """Note that the register could not be reached, once.

    This is politeness bookkeeping, not correctness: a cooldown that cannot be
    read has to mean "carry on", never "fail the fetch". The alternative is an
    application whose HTTP layer stops working when a table is missing, which
    is a strictly worse failure than asking a vendor too often.

    Hence the deliberately broad catches at the call sites. A missing table
    raises SQLAlchemyError, but an unconfigured database raises whatever the
    misconfiguration raises, and "never break a fetch" has to mean never.
    """
    global _warned
    if not _warned:
        _warned = True
        log.warning("The host cooldown register is unavailable (%s): %s", doing, exc)


def _rows_affected(result: object) -> int:
    """A DELETE's row count.

    SQLAlchemy's Result protocol does not promise one — only the cursor result
    a DML statement actually returns has it — so it is read defensively rather
    than asserted.
    """
    count = getattr(result, "rowcount", 0)
    return count if isinstance(count, int) and count > 0 else 0


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _forget(host: str) -> None:
    with _lock:
        _cache.pop(host, None)


def paused_for(url: str) -> float:
    """Seconds still to wait before this host should be asked for anything.

    Zero when the host is free, which is the overwhelmingly common answer and
    the one that has to be cheap.
    """
    host = host_of(url)
    if not host:
        return 0.0

    now = time.monotonic()
    with _lock:
        cached = _cache.get(host)
        if cached is not None and cached[0] > now:
            remaining = cached[1]
            return max(0.0, remaining - (CACHE_SECONDS - (cached[0] - now))) if remaining else 0.0

    until = _read_until(host)
    remaining = 0.0
    if until is not None:
        remaining = max(0.0, (until - utcnow()).total_seconds())
    with _lock:
        _cache[host] = (now + CACHE_SECONDS, remaining or None)
    return remaining


def _read_until(host: str):
    try:
        with session_scope() as session:
            row = session.execute(
                select(HostCooldown).where(HostCooldown.host == host)
            ).scalar_one_or_none()
            return as_utc(row.until) if row is not None else None
    except Exception as exc:  # see _unavailable: this must never break a fetch
        _unavailable(exc, "reading")
        return None


def refused(url: str, reason: str, retry_after: float | None = None) -> float:
    """Record a refusal and return how long everything should now wait.

    The wait doubles with each consecutive refusal, and a ``Retry-After`` the
    host actually sent always wins over our own arithmetic — it is the only
    number in this whole exchange that the vendor chose.
    """
    host = host_of(url)
    if not host:
        return 0.0

    now = utcnow()
    try:
        with session_scope() as session:
            row = session.execute(
                select(HostCooldown).where(HostCooldown.host == host)
            ).scalar_one_or_none()
            if row is None:
                row = HostCooldown(host=host, until=now, refusals=0, first_refused_at=now)
                session.add(row)

            row.refusals += 1
            wait = min(MIN_COOLDOWN * (2 ** (row.refusals - 1)), MAX_COOLDOWN)
            if retry_after:
                wait = max(wait, timedelta(seconds=retry_after))
            wait = min(wait, MAX_COOLDOWN)

            # Never shorten a pause somebody else has already set.
            proposed = now + wait
            row.until = max(proposed, as_utc(row.until) or proposed)
            row.reason = reason[:255]
            row.last_refused_at = now
            session.commit()
            # as_utc() is only None for a None input, and row.until was just set.
            until = as_utc(row.until) or now
            seconds = (until - now).total_seconds()
            refusals = row.refusals
    except Exception as exc:  # see _unavailable: this must never break a fetch
        _unavailable(exc, "recording a refusal")
        return 0.0

    _forget(host)
    log.warning(
        "%s refused a request (%s); pausing every fetcher for %.0fs (refusal %d).",
        host,
        reason,
        seconds,
        refusals,
    )
    return seconds


def succeeded(url: str) -> None:
    """Clear a host's cooldown after it answers again.

    Called on every successful request, so it has to do nothing at all in the
    normal case — hence the cache check first, which is a dictionary lookup.
    """
    host = host_of(url)
    if not host:
        return
    with _lock:
        cached = _cache.get(host)
        if cached is not None and cached[1] is None and cached[0] > time.monotonic():
            return

    try:
        with session_scope() as session:
            result = session.execute(delete(HostCooldown).where(HostCooldown.host == host))
            deleted = _rows_affected(result)
            session.commit()
    except Exception as exc:  # see _unavailable: this must never break a fetch
        _unavailable(exc, "clearing")
        return
    if deleted:
        log.info("%s is answering again; cooldown cleared.", host)
    _forget(host)


def active() -> list[HostCooldown]:
    """Every host currently being left alone, soonest first."""
    with session_scope() as session:
        rows = (
            session.execute(
                select(HostCooldown)
                .where(HostCooldown.until > utcnow())
                .order_by(HostCooldown.until.asc())
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return list(rows)


def clear(host: str | None = None) -> int:
    """Lift a cooldown by hand, or all of them. Returns how many were lifted."""
    with session_scope() as session:
        statement = delete(HostCooldown)
        if host:
            statement = statement.where(HostCooldown.host == host.lower())
        removed = _rows_affected(session.execute(statement))
        session.commit()
    with _lock:
        _cache.clear()
    return removed
