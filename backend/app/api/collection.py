"""A reader's own collection. See app.services.collection.

Owned per user like saved searches and the watchlist: every route is scoped to
``CurrentUser.id``, and somebody else's row is a 404 rather than a 403.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession
from ..models import CollectionItem, Item, Site, User
from ..schemas import (
    CollectionItemIn,
    CollectionItemOut,
    CollectionItemUpdate,
    CollectionOut,
    CollectionTotalsOut,
    CollectionValuationOut,
)
from ..services import collection, traits
from .market import band_out

router = APIRouter(prefix="/collection", tags=["collection"])


def _out(row: CollectionItem, found: collection.Valuation | None) -> CollectionItemOut:
    data = CollectionItemOut.model_validate(row)
    data.model = row.firearm_model.name if row.firearm_model else None
    data.condition_grade_label = traits.GRADE_LABELS.get(row.condition_grade or "")
    if found is not None:
        data.valuation = CollectionValuationOut(
            estimate=found.estimate,
            basis=found.basis,
            like_for_like=found.like_for_like,
            shelf=band_out(found.shelf) if found.shelf else None,
            departed=band_out(found.departed) if found.departed else None,
        )
    return data


def _owned(session: DbSession, user: User, row_id: int) -> CollectionItem:
    row = session.get(CollectionItem, row_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not in your collection.")
    return row


def _rows(session: DbSession, user: User) -> list[CollectionItem]:
    return list(
        session.execute(
            select(CollectionItem)
            .where(CollectionItem.user_id == user.id)
            .order_by(CollectionItem.acquired_on.desc().nulls_last(), CollectionItem.id.desc())
        )
        .scalars()
        .all()
    )


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


@router.get("", response_model=CollectionOut)
def list_collection(user: CurrentUser, session: DbSession) -> CollectionOut:
    valued = [(row, collection.value(session, row)) for row in _rows(session, user)]
    totals = collection.totals(valued)
    return CollectionOut(
        items=[_out(row, found) for row, found in valued],
        totals=CollectionTotalsOut(**vars(totals)),
    )


@router.post("", response_model=CollectionItemOut, status_code=status.HTTP_201_CREATED)
def add_to_collection(
    payload: CollectionItemIn, user: CurrentUser, session: DbSession
) -> CollectionItemOut:
    row = CollectionItem(
        user_id=user.id,
        title=payload.title.strip(),
        caliber=_clean(payload.caliber),
        manufacturer=_clean(payload.manufacturer),
        condition_grade=payload.condition_grade,
        acquired_on=payload.acquired_on,
        paid=payload.paid,
        acquired_from=_clean(payload.acquired_from),
        notes=_clean(payload.notes),
    )
    collection.match_model(session, row)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _out(row, collection.value(session, row))


@router.post(
    "/from-item/{item_id}", response_model=CollectionItemOut, status_code=status.HTTP_201_CREATED
)
def bought_this(item_id: int, user: CurrentUser, session: DbSession) -> CollectionItemOut:
    """ "I bought this": a collection row filled in from the listing.

    The listing's title, caliber, maker and model, its price as what was paid,
    the shop as where from, today as when, and its stated condition. Every one
    of them can be corrected afterwards -- a price negotiated at the counter
    is not the one on the page.
    """
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such item.")
    site = session.get(Site, item.site_id)
    row = CollectionItem(
        user_id=user.id,
        title=item.title[:200],
        firearm_model_id=item.firearm_model_id,
        caliber=item.caliber,
        manufacturer=item.manufacturer,
        condition_grade=item.condition_grade,
        acquired_on=datetime.now(UTC).date(),
        paid=item.current_price,
        acquired_from=site.name if site else None,
        item_id=item.id,
    )
    if row.firearm_model_id is None:
        collection.match_model(session, row)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _out(row, collection.value(session, row))


@router.patch("/{row_id}", response_model=CollectionItemOut)
def update_collection_item(
    row_id: int, payload: CollectionItemUpdate, user: CurrentUser, session: DbSession
) -> CollectionItemOut:
    row = _owned(session, user, row_id)
    sent = payload.model_fields_set
    rematch = False
    if "title" in sent and payload.title:
        rematch = payload.title.strip() != row.title
        row.title = payload.title.strip()
    for name in ("caliber", "manufacturer", "acquired_from", "notes"):
        if name in sent:
            setattr(row, name, _clean(getattr(payload, name)))
    for name in ("condition_grade", "acquired_on", "paid"):
        if name in sent:
            setattr(row, name, getattr(payload, name))
    if "model_declined" in sent and payload.model_declined is not None:
        rematch = rematch or row.model_declined != payload.model_declined
        row.model_declined = payload.model_declined
    if rematch:
        collection.match_model(session, row)
    session.commit()
    session.refresh(row)
    return _out(row, collection.value(session, row))


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_collection(row_id: int, user: CurrentUser, session: DbSession) -> None:
    session.delete(_owned(session, user, row_id))
    session.commit()


#: The export's columns, in the order an insurer's form asks for them.
EXPORT_COLUMNS = (
    "title",
    "manufacturer",
    "model",
    "caliber",
    "condition",
    "acquired_on",
    "acquired_from",
    "paid",
    "estimated_value",
    "value_basis",
    "notes",
)


@router.get("/export")
def export_collection(user: CurrentUser, session: DbSession) -> Response:
    """The collection as a spreadsheet, for insurance and for keeping."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(EXPORT_COLUMNS))
    writer.writeheader()
    for row in _rows(session, user):
        found = collection.value(session, row)
        writer.writerow(
            {
                "title": row.title,
                "manufacturer": row.manufacturer or "",
                "model": row.firearm_model.name if row.firearm_model else "",
                "caliber": row.caliber or "",
                "condition": traits.GRADE_LABELS.get(row.condition_grade or "", ""),
                "acquired_on": row.acquired_on.isoformat() if row.acquired_on else "",
                "acquired_from": row.acquired_from or "",
                "paid": row.paid if row.paid is not None else "",
                "estimated_value": found.estimate if found else "",
                "value_basis": (
                    ""
                    if found is None
                    else (
                        "median asking price when this model left the shelf"
                        if found.basis == "left"
                        else "median asking price of this model on the shelf now"
                    )
                ),
                "notes": row.notes or "",
            }
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="collection-{stamp}.csv"'},
    )
