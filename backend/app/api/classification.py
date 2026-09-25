"""Editing the caliber designations and the accessory keywords.

The last two classification lists that lived in the source. See
:mod:`app.api.countries` for the shape and :mod:`app.services.designations`
for why the rules are process-wide registries rather than per-request reads.

Every write here invalidates the matching registry. Forgetting to is the
failure mode this kind of cache has: the edit saves, the page shows it, and
nothing classifies differently until the process restarts, with nothing on
screen to explain why.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import case, func, select

from ..deps import AdminUser, DbSession
from ..logsafe import client_address
from ..models import CaliberDesignation, ClassifierKeyword, Item
from ..schemas import (
    CaliberDesignationIn,
    CaliberDesignationOut,
    CaliberDesignationUpdate,
    ClassifierKeywordIn,
    ClassifierKeywordOut,
    ClassifierKeywordUpdate,
)
from ..services import accessories, audit, designations

router = APIRouter(tags=["classification"])

DESIGNATIONS = "/caliber-designations"
KEYWORDS = "/classifier-keywords"


# --------------------------------------------------------------------------
# Caliber designations
# --------------------------------------------------------------------------


def _designation_out(row: CaliberDesignation, counts: dict[str, int]) -> CaliberDesignationOut:
    return CaliberDesignationOut(
        id=row.id,
        caliber=row.caliber,
        spellings=row.spellings,
        requires=row.requires,
        whole_word=row.whole_word,
        position=row.position,
        enabled=row.enabled,
        notes=row.notes,
        listing_count=counts.get(row.caliber, 0),
    )


def _caliber_counts(session: DbSession) -> dict[str, int]:
    rows = session.execute(
        select(Item.caliber, func.count(Item.id))
        .where(Item.is_active.is_(True), Item.caliber.is_not(None))
        .group_by(Item.caliber)
    ).all()
    return {name: int(n) for name, n in rows if name is not None}


@router.get(DESIGNATIONS, response_model=list[CaliberDesignationOut])
def list_designations(
    _admin: AdminUser,
    session: DbSession,
    search: str | None = Query(default=None, max_length=100),
) -> list[CaliberDesignationOut]:
    """The rules, in the order they are tried. Order is the whole contract
    here: the first match wins."""
    stmt = select(CaliberDesignation).order_by(CaliberDesignation.position, CaliberDesignation.id)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(CaliberDesignation.caliber).like(like)
            | func.lower(CaliberDesignation.spellings).like(like)
            | func.lower(func.coalesce(CaliberDesignation.requires, "")).like(like)
        )
    counts = _caliber_counts(session)
    return [_designation_out(row, counts) for row in session.execute(stmt).scalars().all()]


@router.post(
    DESIGNATIONS, response_model=CaliberDesignationOut, status_code=status.HTTP_201_CREATED
)
def create_designation(
    payload: CaliberDesignationIn, admin: AdminUser, request: Request, session: DbSession
) -> CaliberDesignationOut:
    row = CaliberDesignation(
        caliber=payload.caliber.strip(),
        spellings=payload.spellings,
        requires=payload.requires or None,
        whole_word=payload.whole_word,
        position=payload.position,
        enabled=payload.enabled,
        notes=payload.notes,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        actor=admin,
        action=audit.DESIGNATION_CHANGED,
        target_type="caliber_designation",
        target_id=row.id,
        target_label=row.caliber,
        detail="created",
        ip_address=client_address(request),
    )
    session.commit()
    designations.invalidate()
    return _designation_out(row, _caliber_counts(session))


@router.patch(DESIGNATIONS + "/{designation_id}", response_model=CaliberDesignationOut)
def update_designation(
    designation_id: int,
    payload: CaliberDesignationUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> CaliberDesignationOut:
    row = session.get(CaliberDesignation, designation_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule.")

    changes = []
    for field in ("caliber", "spellings", "requires", "whole_word", "position", "enabled", "notes"):
        value = getattr(payload, field)
        if value is None:
            continue
        if getattr(row, field) != value:
            changes.append(field)
            setattr(row, field, value.strip() if isinstance(value, str) else value)

    if changes:
        audit.record(
            session,
            actor=admin,
            action=audit.DESIGNATION_CHANGED,
            target_type="caliber_designation",
            target_id=row.id,
            target_label=row.caliber,
            detail=", ".join(changes),
            ip_address=client_address(request),
        )
    session.commit()
    designations.invalidate()
    return _designation_out(row, _caliber_counts(session))


@router.delete(DESIGNATIONS + "/{designation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_designation(
    designation_id: int, admin: AdminUser, request: Request, session: DbSession
) -> None:
    """Remove a rule.

    Listings already carrying the caliber keep it: this deletes the rule that
    *assigns* one, not the answer it gave. Disabling is usually what somebody
    means, which is why that is a switch rather than this.
    """
    row = session.get(CaliberDesignation, designation_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule.")
    audit.record(
        session,
        actor=admin,
        action=audit.DESIGNATION_CHANGED,
        target_type="caliber_designation",
        target_id=row.id,
        target_label=row.caliber,
        detail="deleted",
        ip_address=client_address(request),
    )
    session.delete(row)
    session.commit()
    designations.invalidate()


# --------------------------------------------------------------------------
# Classifier keywords: the accessory words and the two lists that veto them
# --------------------------------------------------------------------------


def _keyword_out(row: ClassifierKeyword) -> ClassifierKeywordOut:
    return ClassifierKeywordOut(
        id=row.id,
        kind=row.kind,
        keyword=row.keyword,
        match=row.match,
        enabled=row.enabled,
        notes=row.notes,
    )


@router.get(KEYWORDS, response_model=list[ClassifierKeywordOut])
def list_keywords(
    _admin: AdminUser,
    session: DbSession,
    kind: str | None = Query(default=None, max_length=16),
) -> list[ClassifierKeywordOut]:
    """All three lists, or one of them.

    Ordered by kind and then alphabetically. Unlike the designations these do
    not compete within a list, so there is no position to preserve -- but the
    *lists* are applied in a fixed order, and that order lives in the
    classifier rather than in a column somebody could reshuffle.
    """
    # Sorted into the order the classifier *reads* the lists, not
    # alphabetically. The page states that order at the top, and a table
    # underneath it running accessory-firearm-promotional contradicts the
    # sentence it sits below.
    reading_order = case(
        {
            accessories.PROMOTIONAL: 0,
            accessories.FIREARM: 1,
            accessories.ACCESSORY: 2,
        },
        value=ClassifierKeyword.kind,
        else_=3,
    )
    stmt = select(ClassifierKeyword).order_by(reading_order, ClassifierKeyword.keyword)
    if kind:
        stmt = stmt.where(ClassifierKeyword.kind == kind)
    return [_keyword_out(row) for row in session.execute(stmt).scalars().all()]


@router.post(KEYWORDS, response_model=ClassifierKeywordOut, status_code=status.HTTP_201_CREATED)
def create_keyword(
    payload: ClassifierKeywordIn, admin: AdminUser, request: Request, session: DbSession
) -> ClassifierKeywordOut:
    keyword = payload.keyword.strip().lower()
    existing = session.execute(
        select(ClassifierKeyword).where(
            ClassifierKeyword.kind == payload.kind,
            func.lower(ClassifierKeyword.keyword) == keyword,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That word is already in this list.",
        )
    row = ClassifierKeyword(
        kind=payload.kind,
        keyword=keyword,
        match=payload.match,
        enabled=payload.enabled,
        notes=payload.notes,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        actor=admin,
        action=audit.CLASSIFIER_KEYWORD_CHANGED,
        target_type="classifier_keyword",
        target_id=row.id,
        target_label=f"{row.kind}: {row.keyword}",
        detail="created",
        ip_address=client_address(request),
    )
    session.commit()
    accessories.invalidate()
    return _keyword_out(row)


@router.patch(KEYWORDS + "/{keyword_id}", response_model=ClassifierKeywordOut)
def update_keyword(
    keyword_id: int,
    payload: ClassifierKeywordUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> ClassifierKeywordOut:
    row = session.get(ClassifierKeyword, keyword_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such word.")

    changes = []
    for field in ("kind", "keyword", "match", "enabled", "notes"):
        value = getattr(payload, field)
        if value is None:
            continue
        if field == "keyword" and isinstance(value, str):
            value = value.strip().lower()
        if getattr(row, field) != value:
            changes.append(field)
            setattr(row, field, value)

    if changes:
        audit.record(
            session,
            actor=admin,
            action=audit.CLASSIFIER_KEYWORD_CHANGED,
            target_type="classifier_keyword",
            target_id=row.id,
            target_label=f"{row.kind}: {row.keyword}",
            detail=", ".join(changes),
            ip_address=client_address(request),
        )
    session.commit()
    accessories.invalidate()
    return _keyword_out(row)


@router.delete(KEYWORDS + "/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_keyword(keyword_id: int, admin: AdminUser, request: Request, session: DbSession) -> None:
    row = session.get(ClassifierKeyword, keyword_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such word.")
    audit.record(
        session,
        actor=admin,
        action=audit.CLASSIFIER_KEYWORD_CHANGED,
        target_type="classifier_keyword",
        target_id=row.id,
        target_label=f"{row.kind}: {row.keyword}",
        detail="deleted",
        ip_address=client_address(request),
    )
    session.delete(row)
    session.commit()
    accessories.invalidate()
