"""Whether the reference tables changed in another process.

The armory, makers, countries, caliber designations and classifier words are
compiled into memory once and kept, and each module's ``invalidate()`` drops
its copy -- **in its own process**. The web app and its scheduler are one
process, and every command-line edit is another, so a change made with
``cli.py armory sync`` or a maintenance script never reached the running app.
It went on matching with what it compiled at start-up, and its scans wrote the
old answers back: on 2026-11-06, 53 Diamondback Firearms revolvers had been
re-filed overnight as Colt Diamondbacks after the alias that caused it was
removed from the command line the evening before.

So the tables carry a generation. Any write that can change what the caches
say bumps it, in the same transaction, from whichever process makes it (see
:func:`install`). Each process compares it with the generation it last saw,
at most every :data:`CHECK_SECONDS`, and drops every cache when it has moved
(:func:`check`).

**What does not bump it: a new proposal.** Every cache reads only approved
rows, and a scan proposes pending ones all day. Letting those bump it would
rebuild every process's caches after every scan, for rows that cannot change
an answer. A pending row edited while still pending is the same. Its
approval, a deletion, or any edit to an approved row bumps it.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy import event, insert, inspect, select, update
from sqlalchemy.orm import InstanceState, Session, sessionmaker

from ..models import (
    ArmoryStatus,
    Caliber,
    CaliberDesignation,
    ClassifierKeyword,
    Country,
    FirearmModel,
    Manufacturer,
    ReferenceGeneration,
    utcnow,
)

log = logging.getLogger(__name__)

#: How stale another process's edit may be here. Short enough that a command-
#: line change is live before the next scan finishes, long enough that the
#: check is one small query in a sea of matching.
CHECK_SECONDS = 10.0

_TRACKED = (FirearmModel, Manufacturer, Caliber, Country, CaliberDesignation, ClassifierKeyword)
_TRACKED_TABLES = frozenset(
    {
        *(cls.__tablename__ for cls in _TRACKED),
        "firearm_model_manufacturers",
        "firearm_model_calibers",
    }
)

_lock = threading.Lock()
_seen: int | None = None
_checked_at = 0.0


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def _matters(obj: object, *, new: bool) -> bool:
    """Whether this change to this row could change what a cache says."""
    if not isinstance(obj, _TRACKED):
        return False
    status = getattr(obj, "status", None)
    if status is None:
        return True
    if new:
        return bool(status != ArmoryStatus.PENDING)
    if status != ArmoryStatus.PENDING:
        return True
    # Pending now. It matters only if it was something else a moment ago,
    # which is sending an approved row back.
    state: InstanceState[Any] = inspect(obj)
    return bool(state.attrs["status"].history.deleted)


def bump(session: Session) -> None:
    """Move the generation on, in the session's own transaction."""
    connection = session.connection()
    moved = connection.execute(
        update(ReferenceGeneration)
        .where(ReferenceGeneration.id == 1)
        .values(generation=ReferenceGeneration.generation + 1, changed_at=utcnow())
    )
    if moved.rowcount == 0:
        connection.execute(
            insert(ReferenceGeneration).values(id=1, generation=1, changed_at=utcnow())
        )


def _before_flush(session: Session, _context, _instances) -> None:
    changed = (
        any(_matters(obj, new=True) for obj in session.new)
        or any(isinstance(obj, _TRACKED) for obj in session.deleted)
        or any(_matters(obj, new=False) for obj in session.dirty if session.is_modified(obj))
    )
    if changed:
        session.info["refgen_pending"] = True


def _after_flush(session: Session, _context) -> None:
    if session.info.pop("refgen_pending", False):
        bump(session)


def _do_orm_execute(state) -> None:
    """A bulk statement (``update(FirearmModel)``, ``delete(firearm_model_
    manufacturers)``) skips the flush, so it is caught here instead."""
    if not (state.is_update or state.is_delete or state.is_insert):
        return
    table = getattr(state.statement, "table", None)
    if getattr(table, "name", None) in _TRACKED_TABLES:
        bump(state.session)


def install(factory: sessionmaker[Session]) -> None:
    """Hook the bump onto every session this factory makes."""
    event.listen(factory, "before_flush", _before_flush)
    event.listen(factory, "after_flush", _after_flush)
    event.listen(factory, "do_orm_execute", _do_orm_execute)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _current(session: Session) -> int | None:
    return session.execute(
        select(ReferenceGeneration.generation).where(ReferenceGeneration.id == 1)
    ).scalar_one_or_none()


def check(session: Session | None = None) -> None:
    """Drop every cache if another process has changed the tables since.

    Cheap to call before every read: it asks the database at most once every
    :data:`CHECK_SECONDS`. Without a session it opens one of its own, for the
    caches whose readers do not take one.
    """
    global _seen, _checked_at
    now = time.monotonic()
    with _lock:
        if now - _checked_at < CHECK_SECONDS:
            return
        _checked_at = now
    try:
        if session is not None:
            generation = _current(session)
        else:
            from ..database import session_scope

            with session_scope() as own:
                generation = _current(own)
    except Exception:  # a failed check must not fail the read
        log.debug("Could not read the reference generation", exc_info=True)
        return
    with _lock:
        if generation == _seen:
            return
        first, _seen = _seen is None, generation
    if not first:
        log.info("Reference tables changed in another process; recompiling.")
        invalidate_all()


def invalidate_all() -> None:
    """Every in-memory copy of a reference table, dropped."""
    from . import accessories, armory, countries, designations

    armory.invalidate()  # and the makers and arsenals with it
    countries.invalidate()
    designations.invalidate()
    accessories.invalidate()


def forget() -> None:
    """Start over, as a fresh process would. For tests."""
    global _seen, _checked_at
    with _lock:
        _seen = None
        _checked_at = 0.0
