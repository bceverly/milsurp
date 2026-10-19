"""Published serial-to-date tables, edited on the Armory's Serial tables tab.

"Serial tables" in ROADMAP.md, 2026-10-19. Administrators only, like the rest
of the armory. Every change re-dates the model's listings at once, so a range
added for the Winchester Garands dates the ones on the shelf before the next
scan. See ``models.SerialRange`` and ``app.services.serials``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..deps import AdminUser, DbSession
from ..logsafe import client_address
from ..models import FirearmModel, Item, Manufacturer, SerialRange
from ..schemas import SerialRangeIn, SerialRangeOut, SerialRangeUpdate
from ..services import audit, serials

router = APIRouter(prefix="/armory", tags=["armory"])


def _out(row: SerialRange) -> SerialRangeOut:
    return SerialRangeOut(
        id=row.id,
        model_id=row.model_id,
        model_name=row.model.name,
        manufacturer_id=row.manufacturer_id,
        maker=row.manufacturer.name if row.manufacturer else None,
        prefix=row.prefix,
        suffix=row.suffix,
        serial_low=row.serial_low,
        serial_high=row.serial_high,
        year_from=row.year_from,
        year_to=row.year_to,
        source=row.source,
        note=row.note,
    )


def _label(row: SerialRange) -> str:
    whose = f"{row.manufacturer.name} " if row.manufacturer else ""
    low = f"{row.prefix}{row.serial_low:,}{row.suffix}"
    return f"{row.model.name} {whose}{low}-{row.prefix}{row.serial_high:,}{row.suffix}"


def _check(session: DbSession, row: SerialRange) -> None:
    """Refuse a range that cannot be one, or that points at nothing."""

    def refuse(detail: str) -> None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)

    if session.get(FirearmModel, row.model_id) is None:
        refuse("No such model.")
    if row.manufacturer_id is not None and session.get(Manufacturer, row.manufacturer_id) is None:
        refuse("No such manufacturer.")
    if row.serial_low > row.serial_high:
        refuse("The first serial is after the last.")
    if row.year_from > row.year_to:
        refuse("The first year is after the last.")
    row.prefix = (row.prefix or "").upper()
    row.suffix = (row.suffix or "").upper()
    row.source = row.source.strip()


def _redate(session: DbSession, model_id: int) -> int:
    """Date the model's listings again, by the tables as they now stand.
    Returns how many changed."""
    changed = 0
    for item in session.execute(
        select(Item).where(Item.firearm_model_id == model_id, Item.serial_low.is_not(None))
    ).scalars():
        was = (item.made_from, item.made_to, item.made_source)
        serials.estimate(session, item)
        changed += int((item.made_from, item.made_to, item.made_source) != was)
    return changed


def _record(
    session: DbSession,
    admin: Any,
    request: Request,
    action: str,
    row: SerialRange,
    detail: str | None = None,
) -> None:
    audit.record(
        session,
        actor=admin,
        action=action,
        target_type="serial_range",
        target_id=row.id,
        target_label=_label(row),
        detail=detail,
        ip_address=client_address(request),
    )


@router.get("/serials", response_model=list[SerialRangeOut])
def every_range(
    _admin: AdminUser,
    session: DbSession,
    search: str | None = Query(default=None, max_length=200),
) -> list[SerialRangeOut]:
    """Every model's serial ranges, by model, maker and number."""
    query = (
        select(SerialRange)
        .join(FirearmModel, FirearmModel.id == SerialRange.model_id)
        .outerjoin(Manufacturer, Manufacturer.id == SerialRange.manufacturer_id)
        .options(selectinload(SerialRange.model), selectinload(SerialRange.manufacturer))
    )
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.where(
            func.lower(FirearmModel.name).like(like)
            | func.lower(func.coalesce(Manufacturer.name, "")).like(like)
            | func.lower(SerialRange.source).like(like)
        )
    rows = session.execute(
        query.order_by(
            func.lower(FirearmModel.name),
            func.lower(func.coalesce(Manufacturer.name, "")),
            SerialRange.prefix,
            SerialRange.suffix,
            SerialRange.serial_low,
        )
    ).scalars()
    return [_out(row) for row in rows]


@router.post("/serials", response_model=SerialRangeOut, status_code=status.HTTP_201_CREATED)
def add_range(
    payload: SerialRangeIn, admin: AdminUser, request: Request, session: DbSession
) -> SerialRangeOut:
    row = SerialRange(**payload.model_dump())
    _check(session, row)
    session.add(row)
    session.flush()
    session.refresh(row)
    moved = _redate(session, row.model_id)
    _record(session, admin, request, audit.ARMORY_CREATED, row, f"{moved} listing(s) re-dated")
    session.commit()
    return _out(row)


@router.patch("/serials/{range_id}", response_model=SerialRangeOut)
def update_range(
    range_id: int,
    payload: SerialRangeUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> SerialRangeOut:
    row = session.get(SerialRange, range_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such range.")
    was_model = row.model_id
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True)
    for name, value in changes.items():
        if value is None and name not in ("manufacturer_id", "note"):
            continue
        setattr(row, name, value)
    _check(session, row)
    session.flush()
    session.refresh(row)
    moved = _redate(session, row.model_id)
    if was_model != row.model_id:
        moved += _redate(session, was_model)
    _record(
        session,
        admin,
        request,
        audit.ARMORY_EDITED,
        row,
        f"{', '.join(sorted(changes))}; {moved} listing(s) re-dated",
    )
    session.commit()
    return _out(row)


@router.delete("/serials/{range_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_range(range_id: int, admin: AdminUser, request: Request, session: DbSession) -> None:
    row = session.get(SerialRange, range_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such range.")
    model_id = row.model_id
    _record(session, admin, request, audit.ARMORY_DELETED, row)
    session.delete(row)
    session.flush()
    _redate(session, model_id)
    session.commit()
