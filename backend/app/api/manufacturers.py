"""The maker list, editable. Every route here is admin-only.

An edit here rewrites listings, which is the point of it: adding "Husqvarna"
should file the Husqvarnas under Husqvarna without waiting for the next scan.
So every write re-derives the maker on the listings the change can reach, and
says how many that was — see :func:`app.services.manufacturers.reprocess` for
why that is a narrow query rather than a pass over the catalog.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from ..deps import AdminUser, DbSession
from ..models import Item, Manufacturer, ManufacturerModel
from ..schemas import (
    ManufacturerCreate,
    ManufacturerOut,
    ManufacturerUpdate,
    ManufacturerWrite,
)
from ..services import manufacturers as service

router = APIRouter(prefix="/manufacturers", tags=["manufacturers"])


def _counts(session: DbSession) -> dict[str, int]:
    rows = session.execute(
        select(Item.manufacturer, func.count(Item.id))
        .where(Item.manufacturer.is_not(None))
        .group_by(Item.manufacturer)
    ).all()
    return {name: count for name, count in rows if name}


def _to_out(
    row: Manufacturer, counts: dict[str, int], shared: set[str] | None = None
) -> ManufacturerOut:
    # Built field by field rather than from the ORM row: `models` is a
    # relationship on the row and a block of text in the response — the same
    # word for two shapes — so reading the row wholesale hands pydantic a list
    # of ORM objects where it wants a string.
    return ManufacturerOut(
        id=row.id,
        name=row.name,
        aliases=row.aliases,
        models="\n".join(row.model_names),
        ambiguous_models=[name for name in row.model_names if name.lower() in (shared or set())],
        position=row.position,
        enabled=row.enabled,
        notes=row.notes,
        item_count=counts.get(row.name, 0),
    )


def _lines(text: str | None) -> list[str]:
    """One entry per line, blanks dropped, order and case as typed."""
    found: list[str] = []
    for line in (text or "").splitlines():
        entry = line.strip()
        if entry and entry.lower() not in {item.lower() for item in found}:
            found.append(entry)
    return found


def _set_models(session: DbSession, row: Manufacturer, text: str | None) -> list[str]:
    """Replace this maker's models with what the textarea says.

    Returns every model name involved — the ones going and the ones arriving —
    because a listing filed under a model that has just been deleted has to be
    re-derived too.
    """
    wanted = _lines(text)
    was = list(row.model_names)
    keep = {name.lower(): name for name in wanted}

    for model in list(row.models):
        if model.name.lower() in keep:
            keep.pop(model.name.lower())
        else:
            session.delete(model)
            row.models.remove(model)
    for name in keep.values():
        row.models.append(ManufacturerModel(name=name))
    return [*was, *wanted]


def _shared_models(session: DbSession) -> set[str]:
    rows = session.execute(select(Manufacturer)).scalars().all()
    return service.ambiguous_models(rows)


def _find(session: DbSession, manufacturer_id: int) -> Manufacturer:
    row = session.get(Manufacturer, manufacturer_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such manufacturer.")
    return row


def _reject_duplicate(session: DbSession, name: str, *, exclude_id: int | None = None) -> None:
    query = select(Manufacturer).where(func.lower(Manufacturer.name) == name.strip().lower())
    if exclude_id is not None:
        query = query.where(Manufacturer.id != exclude_id)
    if session.execute(query).scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A manufacturer named {name.strip()!r} already exists.",
        )


@router.get("", response_model=list[ManufacturerOut])
def list_manufacturers(_admin: AdminUser, session: DbSession) -> list[ManufacturerOut]:
    rows = (
        session.execute(select(Manufacturer).order_by(Manufacturer.position, Manufacturer.name))
        .scalars()
        .all()
    )
    counts = _counts(session)
    shared = _shared_models(session)
    return [_to_out(row, counts, shared) for row in rows]


@router.post("", response_model=ManufacturerWrite, status_code=status.HTTP_201_CREATED)
def create_manufacturer(
    payload: ManufacturerCreate, _admin: AdminUser, session: DbSession
) -> ManufacturerWrite:
    _reject_duplicate(session, payload.name)

    row = Manufacturer(
        name=payload.name.strip(),
        aliases=payload.aliases,
        position=payload.position,
        enabled=payload.enabled,
        notes=payload.notes,
    )
    session.add(row)
    session.flush()
    touched = _set_models(session, row, payload.models)
    session.flush()

    service.invalidate()
    changed = service.reprocess(session, [*row.spellings, *touched])
    session.commit()

    return ManufacturerWrite(
        manufacturer=_to_out(row, _counts(session), _shared_models(session)),
        listings_changed=changed,
    )


@router.patch("/{manufacturer_id}", response_model=ManufacturerWrite)
def update_manufacturer(
    manufacturer_id: int, payload: ManufacturerUpdate, _admin: AdminUser, session: DbSession
) -> ManufacturerWrite:
    row = _find(session, manufacturer_id)
    if payload.name is not None:
        _reject_duplicate(session, payload.name, exclude_id=row.id)

    # The spellings as they were, so listings that used to match and no longer
    # do are re-derived too. Without this, renaming or narrowing a rule left
    # its old answer on every listing it had already labeled.
    was = row.spellings
    previous_name = row.name

    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.aliases is not None:
        row.aliases = payload.aliases
    if payload.position is not None:
        row.position = payload.position
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.notes is not None:
        row.notes = payload.notes
    touched: list[str] = list(row.model_names)
    if payload.models is not None:
        touched = _set_models(session, row, payload.models)
    session.flush()

    service.invalidate()
    changed = service.reprocess(session, [*was, *row.spellings, *touched])
    # A rename does not change what matches, only what it is called, and a
    # listing whose text does not contain the *new* name will not be found by
    # the query above. Those are moved by name.
    if payload.name is not None and row.name != previous_name:
        changed += _rename_labels(session, previous_name, row.name)
    session.commit()

    return ManufacturerWrite(
        manufacturer=_to_out(row, _counts(session), _shared_models(session)),
        listings_changed=changed,
    )


@router.delete("/{manufacturer_id}", response_model=ManufacturerWrite)
def delete_manufacturer(
    manufacturer_id: int, _admin: AdminUser, session: DbSession
) -> ManufacturerWrite:
    row = _find(session, manufacturer_id)
    spellings = [*row.spellings, *row.model_names]
    name = row.name
    session.delete(row)
    session.flush()

    service.invalidate()
    changed = service.reprocess(session, spellings)
    # Anything still labeled with the deleted name matched it by a spelling
    # the remaining rules do not cover; it has no maker now.
    changed += _rename_labels(session, name, None)
    session.commit()

    return ManufacturerWrite(manufacturer=None, listings_changed=changed)


def _rename_labels(session: DbSession, old: str, new: str | None) -> int:
    """Move listings still carrying a label the rules no longer produce.

    Flushes first. These sessions do not autoflush, so without it the query
    reads the rows as they were before :func:`reprocess` touched them, and
    every listing it had already re-filed is found again and re-filed a second
    time -- back to the deleted maker's name, or to nothing.
    """
    session.flush()
    stale = session.execute(select(Item).where(Item.manufacturer == old)).scalars().all()
    for item in stale:
        item.manufacturer = new
    return len(stale)
