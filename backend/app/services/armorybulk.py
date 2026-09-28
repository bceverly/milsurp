"""Disable or delete many armory rows at once, in any of the three tables.

The Armory page could already promote and send back a selection; ruling on
a long queue of scan-proposed names still meant opening each junk row to
switch it off. These are the same two rulings the row editor makes, applied
to a selection, with the same consequences:

* **Every row is audited on its own**, with the snapshot the revert button
  needs, so a bulk action can be undone row by row from the audit log exactly
  like a single edit. A single maker delete used to record nothing; through
  here it records like the other two tables.
* **The listings they explained are re-matched**, once for the whole batch,
  so what the page shows afterwards is already true.

**Disable is the reject.** A disabled row stays in the table, and that is what
stops the next scan proposing the same name again (see migration 0018).
**Delete removes the row**, and with it that memory: a deleted name that
still appears in listings can come back as a new proposal. The page says so
before it deletes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, User
from . import armory, armoryundo, audit

#: The audit log's name for a row of each table, as the single edits write it.
TARGET_TYPE = {"manufacturers": "manufacturer", "models": "model", "calibers": "caliber"}


def _rows(session: Session, table: str, ids: Iterable[int]) -> Sequence[Any]:
    model = armory.CURATED[table]
    return session.execute(select(model).where(model.id.in_(list(ids)))).scalars().all()


def _spellings(table: str, rows: Iterable[Any]) -> list[str]:
    """Every string whose listings these rows can change the answer for.

    A maker's own spellings and its models', as the maker editor re-matches:
    switching off a maker changes what its models are credited to.
    """
    found: list[str] = []
    for row in rows:
        found.extend(row.spellings)
        if table == "manufacturers":
            found.extend(name for model in row.firearm_models for name in model.spellings)
    return found


def disable(
    session: Session,
    table: str,
    ids: Iterable[int],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> tuple[int, int]:
    """Switch rows off. Returns ``(rows switched off, listings re-matched)``.

    Rows already off are left alone and not counted.
    """
    live = [row for row in _rows(session, table, ids) if row.enabled]
    if not live:
        return 0, 0
    spellings = _spellings(table, live)
    for row in live:
        before = armoryundo.snapshot(row)
        row.enabled = False
        audit.record(
            session,
            actor=actor,
            action=audit.ARMORY_EDITED,
            target_type=TARGET_TYPE[table],
            target_id=row.id,
            target_label=row.name,
            detail="enabled (bulk)",
            ip_address=ip_address,
            before=before,
        )
    session.flush()
    armory.invalidate()
    return len(live), armory.reprocess(session, spellings)


def delete(
    session: Session,
    table: str,
    ids: Iterable[int],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> tuple[int, int]:
    """Delete rows. Returns ``(rows deleted, listings re-matched)``."""
    rows = list(_rows(session, table, ids))
    if not rows:
        return 0, 0
    spellings = _spellings(table, rows)
    maker_names = [row.name for row in rows] if table == "manufacturers" else []
    for row in rows:
        audit.record(
            session,
            actor=actor,
            action=audit.ARMORY_DELETED,
            target_type=TARGET_TYPE[table],
            target_id=row.id,
            target_label=row.name,
            detail="bulk delete",
            ip_address=ip_address,
            before=armoryundo.snapshot(row),
        )
        session.delete(row)
    session.flush()
    armory.invalidate()
    touched = armory.reprocess(session, spellings)
    if maker_names:
        # As the single maker delete does: a listing still labeled with a
        # deleted maker matched it by a spelling nothing covers now.
        session.flush()
        stale = (
            session.execute(select(Item).where(Item.manufacturer.in_(maker_names))).scalars().all()
        )
        for item in stale:
            item.manufacturer = None
        touched += len(stale)
    return len(rows), touched
