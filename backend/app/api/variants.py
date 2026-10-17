"""A model's variants -- caliber, barrel, finish, UPC, MSRP -- edited on the
Armory page. See ``models.ModelVariant`` and ``app.services.variants``.

Administrators only, like the rest of the armory. Every change re-matches the
model's listings at once, so a variant added for a 4" Tracker is the variant
the 4" Trackers on the shelf show before the next scan.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select, update

from ..deps import AdminUser, DbSession
from ..logsafe import client_address
from ..models import ArmoryStatus, Caliber, FirearmModel, Item, ModelVariant
from ..schemas import ArmoryAction, ArmoryIds, VariantIn, VariantOut, VariantUpdate
from ..services import audit, frames
from ..services import variants as service

router = APIRouter(prefix="/armory", tags=["armory"])


def _out(row: ModelVariant) -> VariantOut:
    # Not model_validate(row): the row's ``caliber`` is the Caliber, and the
    # schema's is its name -- every variant the manufacturers' sites gave a
    # caliber failed with a 500 until 2026-10-13.
    fields = {
        name: getattr(row, name)
        for name in VariantOut.model_fields
        if name not in ("caliber", "model_name")
    }
    return VariantOut(
        **fields,
        caliber=row.caliber.name if row.caliber else None,
        model_name=row.model.name if row.model else None,
    )


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


#: The Variants tab's Showing filter, as the other tabs': waiting, in use,
#: switched off, or all of them.
VARIANT_VIEWS = ("pending", "approved", "disabled", "")


@router.get("/variants", response_model=list[VariantOut])
def every_variant(
    _admin: AdminUser,
    session: DbSession,
    status_filter: str = Query(default="pending", alias="status"),
    search: str | None = Query(default=None, max_length=200),
) -> list[VariantOut]:
    """Every model's variants together, for the Armory's Variants tab.

    Asked for on 2026-10-14 ("shouldn't that be on its own tab?"): the 605 a
    first read of the manufacturers' sites proposed could only be seen and
    approved one model's dialog at a time.
    """
    if status_filter not in VARIANT_VIEWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown status {status_filter!r}. Valid: pending, approved, disabled, or blank.",
        )
    query = select(ModelVariant).join(FirearmModel, FirearmModel.id == ModelVariant.model_id)
    if status_filter == "pending":
        query = query.where(
            ModelVariant.status == ArmoryStatus.PENDING, ModelVariant.enabled.is_(True)
        )
    elif status_filter == "approved":
        query = query.where(
            ModelVariant.status == ArmoryStatus.APPROVED, ModelVariant.enabled.is_(True)
        )
    elif status_filter == "disabled":
        query = query.where(ModelVariant.enabled.is_(False))
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.where(
            func.lower(ModelVariant.label).like(like) | func.lower(FirearmModel.name).like(like)
        )
    rows = session.execute(
        query.order_by(func.lower(FirearmModel.name), func.lower(ModelVariant.label))
    ).scalars()
    return [_out(row) for row in rows]


@router.get("/variants/counts", response_model=dict[str, int])
def variant_counts(_admin: AdminUser, session: DbSession) -> dict[str, int]:
    """How many variants each Showing setting lists, for the Variants tab's
    label (asked for on 2026-10-17): the counts without the rows, which run to
    thousands once approved.
    """
    counts = {"pending": 0, "approved": 0, "disabled": 0, "": 0}
    for row_status, enabled, n in session.execute(
        select(ModelVariant.status, ModelVariant.enabled, func.count(ModelVariant.id)).group_by(
            ModelVariant.status, ModelVariant.enabled
        )
    ):
        counts[""] += n
        if not enabled:
            counts["disabled"] += n
        elif row_status in (ArmoryStatus.PENDING, ArmoryStatus.APPROVED):
            counts[row_status.value] += n
    return counts


def _bulk(
    session: DbSession,
    admin: Any,
    request: Request,
    ids: list[int],
    change: Any,
    detail: str,
) -> ArmoryAction:
    rows = list(session.execute(select(ModelVariant).where(ModelVariant.id.in_(ids))).scalars())
    changed = [row for row in rows if change(row)]
    session.flush()
    moved = sum(_rematch(session, model_id) for model_id in {row.model_id for row in changed})
    for row in changed:
        audit.record(
            session,
            actor=admin,
            action=audit.ARMORY_EDITED,
            target_type="variant",
            target_id=row.id,
            target_label=row.label,
            detail=detail,
            ip_address=client_address(request),
        )
    session.commit()
    return ArmoryAction(
        changed=len(changed),
        items_restamped=moved,
        message=f"{len(changed)} variant(s) {detail}."
        + (f" {moved} listing(s) re-matched." if moved else ""),
    )


@router.post("/variants/approve", response_model=ArmoryAction)
def approve_variants(
    payload: ArmoryIds, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Approve variants, from any number of models at once."""

    def approve(row: ModelVariant) -> bool:
        if row.status == ArmoryStatus.APPROVED and row.enabled:
            return False
        row.status, row.enabled = ArmoryStatus.APPROVED, True
        return True

    return _bulk(session, admin, request, payload.ids, approve, "approved")


@router.post("/variants/disable", response_model=ArmoryAction)
def disable_variants(
    payload: ArmoryIds, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Switch variants off: no listing is matched to one, and the manufacturer's
    site refreshes it rather than proposing it again."""

    def disable(row: ModelVariant) -> bool:
        if not row.enabled:
            return False
        row.enabled = False
        return True

    return _bulk(session, admin, request, payload.ids, disable, "switched off")


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
