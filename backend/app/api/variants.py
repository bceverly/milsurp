"""A model's variants -- caliber, barrel, finish, UPC, MSRP -- edited on the
Armory page. See ``models.ModelVariant`` and ``app.services.variants``.

Administrators only, like the rest of the armory. Every change re-matches the
model's listings at once, so a variant added for a 4" Tracker is the variant
the 4" Trackers on the shelf show before the next scan.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, update

from ..deps import AdminUser, DbSession
from ..logsafe import client_address
from ..models import Caliber, FirearmModel, Item, ModelVariant
from ..schemas import VariantIn, VariantOut, VariantUpdate
from ..services import audit, frames
from ..services import variants as service

router = APIRouter(prefix="/armory", tags=["armory"])


def _out(row: ModelVariant) -> VariantOut:
    # Not model_validate(row): the row's ``caliber`` is the Caliber, and the
    # schema's is its name -- every variant the manufacturers' sites gave a
    # caliber failed with a 500 until 2026-10-13.
    fields = {name: getattr(row, name) for name in VariantOut.model_fields if name != "caliber"}
    return VariantOut(**fields, caliber=row.caliber.name if row.caliber else None)


def _finish(text: str | None) -> str | None:
    if not text:
        return None
    finish = service.normalize_finish(text)
    if finish is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown finish {text!r}. Valid: {', '.join(service.FINISH_NAMES)}.",
        )
    return finish


def _frame(text: str | None) -> str | None:
    try:
        return frames.checked(text)
    except frames.UnknownFrameSize as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


def _rematch(session: DbSession, model_id: int) -> int:
    """Re-settle every listing of the model. Returns how many moved."""
    moved = 0
    for item in session.execute(select(Item).where(Item.firearm_model_id == model_id)).scalars():
        was = (item.barrel_inches, item.finish, item.frame_size, item.variant_id)
        service.settle(session, item)
        moved += int((item.barrel_inches, item.finish, item.frame_size, item.variant_id) != was)
    return moved


def _check_caliber(session: DbSession, caliber_id: int | None) -> None:
    if caliber_id is not None and session.get(Caliber, caliber_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such caliber.")


@router.get("/models/{model_id}/variants", response_model=list[VariantOut])
def list_variants(model_id: int, _admin: AdminUser, session: DbSession) -> list[VariantOut]:
    model = session.get(FirearmModel, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such model.")
    return [_out(row) for row in model.variants]


@router.post(
    "/models/{model_id}/variants", response_model=VariantOut, status_code=status.HTTP_201_CREATED
)
def add_variant(
    model_id: int, payload: VariantIn, admin: AdminUser, request: Request, session: DbSession
) -> VariantOut:
    if session.get(FirearmModel, model_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such model.")
    _check_caliber(session, payload.caliber_id)
    data = payload.model_dump()
    data["finish"] = _finish(data["finish"])
    data["frame_size"] = _frame(data["frame_size"])
    row = ModelVariant(model_id=model_id, **data)
    session.add(row)
    session.flush()
    _rematch(session, model_id)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_CREATED,
        target_type="variant",
        target_id=row.id,
        target_label=row.label,
        ip_address=client_address(request),
    )
    session.commit()
    return _out(row)


@router.patch("/variants/{variant_id}", response_model=VariantOut)
def update_variant(
    variant_id: int,
    payload: VariantUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> VariantOut:
    row = session.get(ModelVariant, variant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such variant.")
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True)
    if "caliber_id" in changes:
        _check_caliber(session, changes["caliber_id"])
    if "finish" in changes:
        changes["finish"] = _finish(changes["finish"])
    if "frame_size" in changes:
        changes["frame_size"] = _frame(changes["frame_size"])
    for name, value in changes.items():
        setattr(row, name, value)
    session.flush()
    _rematch(session, row.model_id)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_EDITED,
        target_type="variant",
        target_id=row.id,
        target_label=row.label,
        detail=", ".join(sorted(changes)),
        ip_address=client_address(request),
    )
    session.commit()
    return _out(row)


@router.delete("/variants/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variant(variant_id: int, admin: AdminUser, request: Request, session: DbSession) -> None:
    row = session.get(ModelVariant, variant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such variant.")
    model_id, label = row.model_id, row.label
    # The link on items is the application's to keep -- see Item.variant_id.
    session.execute(update(Item).where(Item.variant_id == variant_id).values(variant_id=None))
    session.delete(row)
    session.flush()
    _rematch(session, model_id)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_DELETED,
        target_type="variant",
        target_id=variant_id,
        target_label=label,
        ip_address=client_address(request),
    )
    session.commit()
