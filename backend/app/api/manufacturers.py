"""The maker list, editable. Every route here is admin-only.

An edit here rewrites listings, which is the point of it: adding "Husqvarna"
should file the Husqvarnas under Husqvarna without waiting for the next scan.
So every write re-derives the maker on the listings the change can reach, and
says how many that was — see :func:`app.services.manufacturers.reprocess` for
why that is a narrow query rather than a pass over the catalog.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..deps import AdminUser, DbSession
from ..logsafe import client_address
from ..models import Item, Manufacturer, firearm_model_manufacturers
from ..schemas import (
    ManufacturerCreate,
    ManufacturerOut,
    ManufacturerUpdate,
    ManufacturerWrite,
)
from ..services import armory, armoryundo, audit
from ..services import manufacturers as service

router = APIRouter(prefix="/manufacturers", tags=["manufacturers"])


def _counts(session: DbSession) -> dict[str, int]:
    rows = session.execute(
        select(Item.manufacturer, func.count(Item.id))
        .where(Item.manufacturer.is_not(None))
        .group_by(Item.manufacturer)
    ).all()
    return {name: count for name, count in rows if name}


def _model_counts(session: DbSession) -> dict[int, int]:
    """How many armory models name each maker, in one grouped read.

    The list used to take ``len(row.firearm_models)`` per maker, which loads
    each maker's models in a query of its own: two hundred makers, two
    hundred queries, on every load of the Manufacturers tab.
    """
    link = firearm_model_manufacturers.c
    rows = session.execute(
        select(link.manufacturer_id, func.count(link.firearm_model_id)).group_by(
            link.manufacturer_id
        )
    ).all()
    return {int(maker): int(count) for maker, count in rows}


def _to_out(
    row: Manufacturer, counts: dict[str, int], model_counts: dict[int, int] | None = None
) -> ManufacturerOut:
    """One maker, with a count of the models the armory says it built.

    The models themselves used to live here, as a block of text on the maker —
    which meant a designation two firms both made had to be dropped from
    matching, because a flat list per firm cannot say "these two made the same
    thing". They are rows in the armory now, each with all of its makers, and
    this reports the tally so the page can offer the drill-down.
    """
    return ManufacturerOut(
        id=row.id,
        name=row.name,
        aliases=row.aliases,
        model_count=(
            model_counts.get(row.id, 0) if model_counts is not None else len(row.firearm_models)
        ),
        position=row.position,
        enabled=row.enabled,
        notes=row.notes,
        status=row.status,
        merged_into=row.merged_into.name if row.merged_into else None,
        first_seen_in=row.first_seen_in,
        item_count=counts.get(row.name, 0),
        country=row.country,
    )


def _lines(text: str | None) -> list[str]:
    """One entry per line, blanks dropped, order and case as typed."""
    found: list[str] = []
    for line in (text or "").splitlines():
        entry = line.strip()
        if entry and entry.lower() not in {item.lower() for item in found}:
            found.append(entry)
    return found


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
def list_manufacturers(
    _admin: AdminUser,
    session: DbSession,
    view: armory.ArmoryView | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=100),
) -> list[ManufacturerOut]:
    """The maker list, filtered the same way the armory's other two tabs are.

    The filters were missing, so the Manufacturers tab ignored the status the
    page was set to and always returned all of them -- which, with no status in
    the payload either, read as fifty-one makers all awaiting approval.
    """
    stmt = (
        select(Manufacturer)
        .options(selectinload(Manufacturer.merged_into))
        .order_by(Manufacturer.position, Manufacturer.name)
    )
    stmt = armory.filter_by_view(stmt, Manufacturer, view)
    if search:
        stmt = stmt.where(
            Manufacturer.name.ilike(f"%{search}%") | Manufacturer.aliases.ilike(f"%{search}%")
        )
    counts = _counts(session)
    model_counts = _model_counts(session)
    return [_to_out(row, counts, model_counts) for row in session.execute(stmt).scalars()]


@router.post("", response_model=ManufacturerWrite, status_code=status.HTTP_201_CREATED)
def create_manufacturer(
    payload: ManufacturerCreate, admin: AdminUser, request: Request, session: DbSession
) -> ManufacturerWrite:
    _reject_duplicate(session, payload.name)

    row = Manufacturer(
        name=payload.name.strip(),
        aliases=payload.aliases,
        status=payload.status,
        position=payload.position,
        enabled=payload.enabled,
        notes=payload.notes,
        country=(payload.country or None),
    )
    session.add(row)
    session.flush()

    service.invalidate()
    changed = service.reprocess(session, row.spellings)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_CREATED,
        target_type="manufacturer",
        target_id=row.id,
        target_label=row.name,
        detail=f"{changed} listing(s) re-derived",
        ip_address=client_address(request),
    )
    session.commit()

    return ManufacturerWrite(
        manufacturer=_to_out(row, _counts(session)),
        listings_changed=changed,
    )


@router.patch("/{manufacturer_id}", response_model=ManufacturerWrite)
def update_manufacturer(
    manufacturer_id: int,
    payload: ManufacturerUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> ManufacturerWrite:
    row = _find(session, manufacturer_id)
    # What it held, so the audit log can put it back -- as for a model or a
    # caliber. Manufacturers were the one armory table that left no record.
    before = armoryundo.snapshot(row)
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
    if payload.status is not None:
        row.status = payload.status
    if payload.position is not None:
        row.position = payload.position
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.notes is not None:
        row.notes = payload.notes
    if payload.country is not None:
        # Blank clears it: "we have not been told" is a real state, and there
        # has to be a way back to it from a country entered by mistake.
        row.country = payload.country.strip() or None
    touched: list[str] = [name for model in row.firearm_models for name in model.spellings]
    session.flush()

    service.invalidate()
    changed = service.reprocess(session, [*was, *row.spellings, *touched])
    # A rename does not change what matches, only what it is called, and a
    # listing whose text does not contain the *new* name will not be found by
    # the query above. Those are moved by name.
    if payload.name is not None and row.name != previous_name:
        changed += _rename_labels(session, previous_name, row.name)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_EDITED,
        target_type="manufacturer",
        target_id=row.id,
        target_label=row.name,
        detail=", ".join(sorted(payload.model_dump(exclude_unset=True))),
        ip_address=client_address(request),
        before=before,
    )
    session.commit()

    return ManufacturerWrite(
        manufacturer=_to_out(row, _counts(session)),
        listings_changed=changed,
    )


@router.delete("/{manufacturer_id}", response_model=ManufacturerWrite)
def delete_manufacturer(
    manufacturer_id: int, admin: AdminUser, request: Request, session: DbSession
) -> ManufacturerWrite:
    row = _find(session, manufacturer_id)
    spellings = [*row.spellings, *(n for m in row.firearm_models for n in m.spellings)]
    name, was_id, before = row.name, row.id, armoryundo.snapshot(row)
    session.delete(row)
    session.flush()

    service.invalidate()
    changed = service.reprocess(session, spellings)
    # Anything still labeled with the deleted name matched it by a spelling
    # the remaining rules do not cover; it has no maker now.
    changed += _rename_labels(session, name, None)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_DELETED,
        target_type="manufacturer",
        target_id=was_id,
        target_label=name,
        detail=f"{changed} listing(s) re-derived",
        ip_address=client_address(request),
        before=before,
    )
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
