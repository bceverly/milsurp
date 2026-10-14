"""Corrections by hand, applied after every rule has had its say.

The classification pipeline is built to be recomputed: a caliber read out of a
title, a country inferred from a maker, a model matched from the armory, all
rebuilt on every scan. That is deliberate and it is what lets one rule fix
reach eleven thousand listings. It also means a correction typed into the
database survives exactly until the next scan.

An override is the answer to that, and it is narrow on purpose:

* **It wins over everything**, because the alternative -- a person's decision
  losing to a heuristic -- is the whole problem.
* **A blank field means "no opinion"**, never "clear it". Somebody correcting a
  caliber is not also asserting the country is unknown, and a form that posts
  every field would say exactly that on every save.
* **It records who and why.** An override nobody can explain is one nobody can
  safely undo, and the person who set it will not be the person reading it.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ArmoryStatus, FirearmModel, Item, ItemOverride, User
from . import provenance

#: The fields a person may correct.
#:
#: These and no others, because these are the derived ones -- the ones a scan
#: recomputes and can therefore get wrong twice. Price, title and URL are the
#: vendor's own words: disagreeing with those is not a correction, it is a
#: different listing.
FIELDS: tuple[str, ...] = ("caliber", "country", "manufacturer", "model", "kind")


def for_item(session: Session, item_id: int) -> ItemOverride | None:
    return session.execute(
        select(ItemOverride).where(ItemOverride.item_id == item_id)
    ).scalar_one_or_none()


def apply_to(session: Session, item: Item) -> bool:
    """Put this listing's override onto it, if there is one. True if anything changed.

    Called at the end of the scan's reconcile, after the armory, so it is the
    last word. Cheap when there is nothing to do, which is the common case:
    one indexed lookup by item id.
    """
    override = for_item(session, item.id)
    if override is None:
        return False
    changed = False
    for field in FIELDS:
        value = getattr(override, field, None)
        if not value:
            continue
        if getattr(item, field, None) != value:
            setattr(item, field, value)
            changed = True
        # Stamped whether or not the value moved. A correction that happens to
        # agree with the rules is still a person's answer, and the stamp is
        # what stops a later rebuild treating it as the rules' own to discard.
        # `model` and `kind` are overridable and have no source column: they
        # are not fields reclassify rebuilds from text.
        column = provenance.SOURCE_COLUMNS.get(field)
        if column and getattr(item, column, None) != provenance.OVERRIDE:
            setattr(item, column, provenance.OVERRIDE)
            changed = True
    # A corrected model is a row of the armory, not only a name: what the
    # armory knows, the manufacturer's page and the model filter all follow
    # ``firearm_model_id``, and correcting an original 1915 M1911 away from
    # the modern "Springfield Armory 1911" changed the name it showed and left
    # it linked to the modern pistol's page (2026-10-13).
    if override.model:
        model_id = _model_id(session, override.model)
        if model_id is not None and item.firearm_model_id != model_id:
            item.firearm_model_id = model_id
            changed = True
    return changed


def _model_id(session: Session, name: str) -> int | None:
    """The armory model a corrected name means: the row of that name, or the
    one the matcher reads it as."""
    from . import armory

    row = session.execute(
        select(FirearmModel.id).where(
            func.lower(FirearmModel.name) == name.strip().lower(),
            FirearmModel.status != ArmoryStatus.MERGED,
        )
    ).first()
    if row is not None:
        return int(row[0])
    return armory.match(session, name).model_id


def save(
    session: Session,
    item: Item,
    values: dict[str, str | None],
    *,
    actor: User | None = None,
    note: str | None = None,
) -> ItemOverride:
    """Create or update this listing's override, then apply it immediately.

    Applied here as well as during a scan so the change is visible at once:
    waiting for the next scan to see a correction take effect is indisputably
    correct and reads as the button not working.
    """
    override = for_item(session, item.id)
    if override is None:
        override = ItemOverride(item_id=item.id)
        session.add(override)

    for field in FIELDS:
        if field in values:
            # Empty string and None both mean "no opinion on this field", so a
            # form that clears a box removes the override for it rather than
            # writing a blank over the derived value.
            raw = values.get(field)
            setattr(override, field, (raw or "").strip() or None)

    if note is not None:
        override.note = note.strip() or None
    if actor is not None:
        override.set_by_id = actor.id
        override.set_by_name = actor.username

    session.flush()
    apply_to(session, item)
    return override


def clear(session: Session, item: Item) -> bool:
    """Drop the override. True if there was one.

    The derived values are *not* restored here: what they should be is the
    scan's business, and guessing at them from this side would mean writing a
    second implementation of the pipeline. The next scan -- or ``reclassify
    --recompute`` -- puts back whatever the rules now say, which is the whole
    point of removing the override.
    """
    override = for_item(session, item.id)
    if override is None:
        return False
    session.delete(override)
    return True
