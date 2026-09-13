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

**Trust is rebuilt slowly, and the pace outlives the pause.** A pause on its
own produces a sawtooth: the host goes quiet, the wait expires, a fresh process
with an empty pace table asks at full speed, and earns the next refusal within
seconds. checkpointcharlies.com sat in that loop for three days — eight
consecutive refusals, every scan dying on a cooldown it had just re-earned —
and none of it was visible, because a scan that never starts looks like a scan
with nothing to report. So a success no longer erases the record; it decays it
by one, and until it reaches zero :func:`pace_for` asks every fetcher to leave
a gap. That is the half of "the pace a scan learns used to die with the
process" that the original stop/go register did not fix.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
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

#: The gap asked for after one refusal, and the ceiling it doubles towards.
#:
#: This is the speed limit that applies *between* pauses -- once a host's
#: cooldown has expired but before it has earned its full pace back. Five
#: seconds matches MIN_PHOTO_BACKOFF, which is the number the photo fetcher
#: already reaches for the first time a host says 429.
MIN_PACE = 5.0
MAX_PACE = 60.0

#: How long a cached answer is trusted.
CACHE_SECONDS = 5.0

_lock = threading.Lock()
#: host -> (cache expiry as monotonic time, seconds still to wait or None,
#: consecutive refusals). The refusal count rides along because succeeded() is
#: called on every successful request and must answer "nothing to do" without
#: touching the database, which is the overwhelmingly common case.
_cache: dict[str, tuple[float, float | None, int]] = {}

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
    remaining, _refusals = _state(url)
    return remaining


def pace_for(url: str) -> float:
    """Seconds a caller should leave between requests to this host.

    Zero for a host that has never refused us, which is nearly all of them.

    This is what stops the sawtooth. A cooldown answers "may I ask at all";
    without an answer to "how fast", a fresh process resumes at full speed the
    instant the pause lifts and is refused again inside a second. The gap
    shrinks as :func:`succeeded` decays the refusal count, so a host that
    starts answering is back to full speed within a handful of requests rather
    than staying throttled forever.
    """
    _remaining, refusals = _state(url)
    return pace_after(refusals)


def pace_after(refusals: int) -> float:
    """The gap a host earns for this many consecutive refusals.

    Public because the `resting` command shows it beside the pause: a host
    being asked slowly and a host not being asked at all are different states,
    and only one of them used to be visible.
    """
    if refusals <= 0:
        return 0.0
    return float(min(MIN_PACE * 2 ** (refusals - 1), MAX_PACE))


def _state(url: str) -> tuple[float, int]:
    """(seconds still to wait, consecutive refusals), cached for a moment."""
    host = host_of(url)
    if not host:
        return 0.0, 0

    now = time.monotonic()
    with _lock:
        cached = _cache.get(host)
        if cached is not None and cached[0] > now:
            remaining = cached[1]
            elapsed = CACHE_SECONDS - (cached[0] - now)
            left = max(0.0, remaining - elapsed) if remaining else 0.0
            return left, cached[2]

    until, refusals = _read_row(host)
    remaining = 0.0
    if until is not None:
        remaining = max(0.0, (until - utcnow()).total_seconds())
    with _lock:
        _cache[host] = (now + CACHE_SECONDS, remaining or None, refusals)
    return remaining, refusals


def _read_row(host: str) -> tuple[datetime | None, int]:
    try:
        with session_scope() as session:
            row = session.execute(
                select(HostCooldown).where(HostCooldown.host == host)
            ).scalar_one_or_none()
            if row is None:
                return None, 0
            return as_utc(row.until), row.refusals
    except Exception as exc:  # see _unavailable: this must never break a fetch
        _unavailable(exc, "reading")
        return None, 0


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
    """Take one step back towards trusting this host.

    Called on every successful request, so it has to do nothing at all in the
    normal case — hence the cache check first, which is a dictionary lookup.

    **One success used to delete the row outright**, and that is what produced
    the sawtooth: eight refusals of accumulated evidence were thrown away by a
    single photograph arriving, the next request went out at full speed, and
    the host refused again. So a success now decays the count by one and lifts
    the pause; the row goes only when the count reaches zero. A host that
    refused us eight times has to answer eight times to be trusted at full
    speed again, which on a recovering host is a few minutes rather than never.
    """
    host = host_of(url)
    if not host:
        return
    with _lock:
        cached = _cache.get(host)
        if cached is not None and cached[2] == 0 and cached[0] > time.monotonic():
            return

    try:
        with session_scope() as session:
            row = session.execute(
                select(HostCooldown).where(HostCooldown.host == host)
            ).scalar_one_or_none()
            if row is None:
                cleared, remaining = False, 0
            elif row.refusals > 1:
                row.refusals -= 1
                # The pause is over -- it answered -- but the pace is not.
                row.until = utcnow()
                session.commit()
                cleared, remaining = False, row.refusals
            else:
                session.execute(delete(HostCooldown).where(HostCooldown.host == host))
                session.commit()
                cleared, remaining = True, 0
    except Exception as exc:  # see _unavailable: this must never break a fetch
        _unavailable(exc, "clearing")
        return

    if cleared:
        log.info("%s is answering again; cooldown cleared.", host)
    elif remaining:
        log.info(
            "%s answered; easing off to one request every %.0fs (%d refusal(s) still on record).",
            host,
            pace_after(remaining),
            remaining,
        )
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


def tracked() -> list[HostCooldown]:
    """Every host with a refusal still on its record, worst first.

    Wider than :func:`active`, and the two answer different questions. A host
    whose pause has lapsed but whose count has not reached zero is not being
    *rested* — it is being asked slowly. Without this it would be invisible,
    which is the state checkpointcharlies.com spent three days in.
    """
    with session_scope() as session:
        rows = (
            session.execute(
                select(HostCooldown)
                .where(HostCooldown.refusals > 0)
                .order_by(HostCooldown.refusals.desc(), HostCooldown.host.asc())
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
