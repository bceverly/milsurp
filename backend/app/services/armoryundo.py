"""Putting an armory row back the way it was.

A merge has always reversed — it records what it took so it can be given back —
and an ordinary edit never did. That asymmetry stopped being tolerable the day
an edit started reporting how many listings it moved: *412 listing(s)
re-matched* under a dialog somebody has just closed is precisely the moment they
want the last five minutes back, and the only answer was to remember what the
row used to say.

**Built on the audit log rather than on a history of its own.** The event that
needs undoing is the thing somebody is looking at when they want to undo it, it
is already on a page with a timestamp and a name against it, and a parallel
table would be a second thing to write, read and prune in step with the first.
Migration 0032 gave the log a `before_state`; this reads it back.

Two shapes, and the difference matters:

* An **edit** is reversed by writing the old values over the new ones. The row
  is still there and keeps its id, so everything pointing at it still does.
* A **delete** is reversed by creating the row again. It cannot keep its old id
  — the listings that pointed at it were unlinked when it went — but that turns
  out not to matter, because matching is by spelling: `reprocess` re-reads every
  listing mentioning the restored names and links them to the new row. The
  count comes back the same.

What is deliberately *not* offered is an undo of an undo. A revert is itself
logged, and reverting the revert is the same operation on a newer event, which
is what a person means by "actually, put it back again".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent, Caliber, FirearmModel, Manufacturer, User
from . import armory, audit

#: target_type -> the table it names. The audit log stores a string so it can
#: describe rows from anywhere; only these three can be put back.
REVERTIBLE = {
    "caliber": Caliber,
    "model": FirearmModel,
    "manufacturer": Manufacturer,
}

#: Relationships restored by name rather than by id, because a delete-and-undo
#: gives the row a new one. The names are what the export file uses too.
_LINKS: dict[str, Any] = {"manufacturer_names": Manufacturer, "caliber_names": Caliber}


class CannotRevert(Exception):
    """The event cannot be undone, with a sentence saying why."""


@dataclass
class Reverted:
    """What the undo did."""

    label: str
    recreated: bool
    listings_changed: int


def snapshot(row: Any) -> dict[str, Any]:
    """The state worth restoring, as plain data.

    Names rather than ids for the relationships -- see `_LINKS`. Everything
    here is a column somebody can edit on the page; `id`, timestamps and
    derived counts are left out because restoring them would either fail or
    lie.
    """
    fields: dict[str, Any] = {}
    for name in ("name", "aliases", "notes", "country", "position", "enabled", "wikipedia_url"):
        if hasattr(row, name):
            fields[name] = getattr(row, name)
    if getattr(row, "status", None) is not None:
        fields["status"] = row.status.value
    if hasattr(row, "kind"):
        fields["kind"] = row.kind.value if row.kind is not None else None
    if hasattr(row, "manufacturers"):
        fields["manufacturer_names"] = [maker.name for maker in row.manufacturers]
    if hasattr(row, "calibers"):
        fields["caliber_names"] = [cartridge.name for cartridge in row.calibers]
    return fields


def _apply(session: Session, row: Any, state: dict[str, Any]) -> None:
    """Write a snapshot back onto a row, resolving the relationships by name."""
    from ..models import ArmoryStatus, FirearmKind

    for key, value in state.items():
        if key in _LINKS:
            continue
        if key == "status" and value is not None:
            row.status = ArmoryStatus(value)
        elif key == "kind":
            row.kind = FirearmKind(value) if value else None
        elif hasattr(row, key):
            setattr(row, key, value)

    for key, model in _LINKS.items():
        if key not in state or not hasattr(row, key.replace("_names", "s")):
            continue
        names: list[str] = list(state[key] or [])
        found = [session.query(model).filter(model.name == name).one_or_none() for name in names]
        # A relationship to something since deleted is dropped rather than
        # recreated: guessing a row back into the armory is a bigger decision
        # than the one being undone.
        setattr(row, key.replace("_names", "s"), [item for item in found if item is not None])


def revert(
    session: Session, event: AuditEvent, actor: User | None, ip_address: str | None
) -> Reverted:
    """Put back whatever *event* changed. Raises :class:`CannotRevert`."""
    if event.action not in (audit.ARMORY_EDITED, audit.ARMORY_DELETED):
        raise CannotRevert("Only an armory edit or deletion can be undone.")
    if not event.before_state:
        raise CannotRevert(
            "This change was made before the application recorded what rows "
            "held beforehand, so there is nothing to put back."
        )
    model = REVERTIBLE.get(event.target_type or "")
    if model is None:
        raise CannotRevert(f"Nothing here knows how to undo a {event.target_type!r}.")

    try:
        state = json.loads(event.before_state)
    except ValueError as exc:  # pragma: no cover - a corrupted row
        raise CannotRevert("The recorded state could not be read back.") from exc

    spellings: list[str] = []
    row: Any = session.get(model, int(event.target_id)) if event.target_id else None
    recreated = row is None
    if row is None:
        row = model()
        session.add(row)
    else:
        spellings.extend(row.spellings)

    _apply(session, row, state)
    session.flush()
    spellings.extend(row.spellings)

    armory.invalidate()
    changed = armory.reprocess(session, spellings)
    audit.record(
        session,
        actor=actor,
        action=audit.ARMORY_REVERTED,
        target_type=event.target_type,
        target_id=row.id,
        target_label=str(state.get("name") or event.target_label or ""),
        detail=f"undid {event.action} from {event.created_at:%Y-%m-%d %H:%M}",
        ip_address=ip_address,
    )
    session.commit()
    return Reverted(
        label=str(state.get("name") or event.target_label or ""),
        recreated=recreated,
        listings_changed=changed,
    )
