"""A reader's own collection. See app.services.collection.

Owned per user like saved searches and the watchlist: every route is scoped to
``CurrentUser.id``, and somebody else's row is a 404 rather than a 403.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import case, func, or_, select

from ..deps import CurrentUser, DbSession
from ..models import (
    ArmoryStatus,
    Caliber,
    CollectionItem,
    FirearmModel,
    Item,
    Manufacturer,
    Site,
    User,
)
from ..schemas import (
    CollectionHistoryPoint,
    CollectionItemIn,
    CollectionItemOut,
    CollectionItemUpdate,
    CollectionOut,
    CollectionTotalsOut,
    CollectionValuationOut,
    ComparableOut,
    ComparablesOut,
    FitsOut,
    ModelChoiceOut,
    NameChoiceOut,
)
from ..services import collection, foryourguns, traits
from .market import band_out

router = APIRouter(prefix="/collection", tags=["collection"])


def _valuation_out(found: collection.Valuation) -> CollectionValuationOut:
    return CollectionValuationOut(
        estimate=found.estimate,
        basis=found.basis,
        like_for_like=found.like_for_like,
        shelf=band_out(found.shelf) if found.shelf else None,
        departed=band_out(found.departed) if found.departed else None,
    )


def _out(row: CollectionItem, found: collection.Valuation | None) -> CollectionItemOut:
    data = CollectionItemOut.model_validate(row)
    data.model = row.firearm_model.name if row.firearm_model else None
    data.condition_grade_label = traits.GRADE_LABELS.get(row.condition_grade or "")
    if found is not None:
        data.valuation = _valuation_out(found)
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


def _chosen_model(session: DbSession, model_id: int) -> FirearmModel:
    """A model somebody picked: it has to be one the armory vouches for."""
    model = session.get(FirearmModel, model_id)
    if model is None or model.status != ArmoryStatus.APPROVED or not model.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That is not a model the armory has."
        )
    return model


def _armory_search(session: DbSession, table: Any, search: str, limit: int) -> list[Any]:
    """Approved, enabled rows of one armory table matching a search.

    By name or by any spelling on the row, names that start with the search
    first, then alphabetical. The same rule for models, calibers and makers,
    so the three pickers on the collection's form behave alike.
    """
    term = " ".join(search.split())
    statement = select(table).where(table.status == ArmoryStatus.APPROVED, table.enabled.is_(True))
    if term:
        like = f"%{term.replace('%', '').replace('_', '')}%"
        statement = statement.where(or_(table.name.ilike(like), table.aliases.ilike(like)))
        starts = case((func.lower(table.name).startswith(term.lower()), 0), else_=1)
        statement = statement.order_by(starts, table.name)
    else:
        statement = statement.order_by(table.name)
    return list(session.execute(statement.limit(limit)).scalars())


@router.get("/models", response_model=list[ModelChoiceOut])
def model_choices(
    _user: CurrentUser,
    session: DbSession,
    search: str = Query(default="", max_length=80),
    limit: int = Query(default=12, ge=1, le=50),
) -> list[ModelChoiceOut]:
    """The armory models a collection row can be said to be.

    **Why this exists.** A row was matched from its title and from nothing
    else, so "Carcano Carbine" -- a fair name for a Moschetto -- matched no
    model, and the owner's only recourse was guessing the words the armory
    happens to use. The owner knows what the gun is; this lets them say so.

    Open to every signed-in reader: these are the same names the inventory's
    Model filter already shows them.
    """
    return [
        ModelChoiceOut(
            id=row.id,
            name=row.name,
            kind=row.kind.value if row.kind else None,
            country=row.country,
        )
        for row in _armory_search(session, FirearmModel, search, limit)
    ]


@router.get("/calibers", response_model=list[NameChoiceOut])
def caliber_choices(
    _user: CurrentUser,
    session: DbSession,
    search: str = Query(default="", max_length=80),
    limit: int = Query(default=12, ge=1, le=50),
) -> list[NameChoiceOut]:
    """Cartridges as the armory spells them, for the collection form's Caliber.

    The armory's spelling is what the catalog files listings under, so a row
    that uses it finds its ammunition under "For your guns" without being read
    and normalized first. Typed freely, it still works -- this only offers.
    """
    return [NameChoiceOut(name=row.name) for row in _armory_search(session, Caliber, search, limit)]


@router.get("/makers", response_model=list[NameChoiceOut])
def maker_choices(
    _user: CurrentUser,
    session: DbSession,
    search: str = Query(default="", max_length=80),
    limit: int = Query(default=12, ge=1, le=50),
) -> list[NameChoiceOut]:
    """Makers as the armory names them, for the collection form's Maker."""
    return [
        NameChoiceOut(name=row.name, country=row.country)
        for row in _armory_search(session, Manufacturer, search, limit)
    ]


@router.get("", response_model=CollectionOut)
def list_collection(user: CurrentUser, session: DbSession) -> CollectionOut:
    valued = [(row, collection.value(session, row)) for row in _rows(session, user)]
    totals = collection.totals(valued)
    return CollectionOut(
        items=[_out(row, found) for row, found in valued],
        totals=CollectionTotalsOut(**vars(totals)),
        history=[
            CollectionHistoryPoint(day=day, value=value, guns=guns)
            for day, value, guns in collection.history(session, user.id)
        ],
    )


@router.get("/for-your-guns", response_model=list[FitsOut])
def for_your_guns(user: CurrentUser, session: DbSession) -> list[FitsOut]:
    """What is for sale that fits each of this reader's guns. See foryourguns."""
    from .items import _to_out

    fits = foryourguns.for_user(session, user)
    site_names = dict(session.execute(select(Site.id, Site.name)).all())
    return [
        FitsOut(
            row_id=fit.row.id,
            title=fit.row.title,
            model=fit.row.firearm_model.name if fit.row.firearm_model else None,
            calibers=fit.calibers,
            ammo=[_to_out(item, site_names) for item in fit.ammo],
            ammo_total=fit.ammo_total,
            accessories=[_to_out(item, site_names) for item in fit.accessories],
            accessories_total=fit.accessories_total,
        )
        for fit in fits
    ]


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
    if payload.firearm_model_id is not None:
        row.firearm_model_id = _chosen_model(session, payload.firearm_model_id).id
    else:
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


@router.get("/{row_id}/comparables", response_model=ComparablesOut)
def show_comparables(row_id: int, user: CurrentUser, session: DbSession) -> ComparablesOut:
    """The listings this gun's value was worked out from.

    Chosen by the same rules as the value itself (see
    ``collection.comparables``), so what the page lists is what the number
    was drawn from -- narrowed to the same condition when the value was.
    """
    row = _owned(session, user, row_id)
    found = collection.comparables(session, row)
    site_names = dict(session.execute(select(Site.id, Site.name)).all())

    def listed(item: Item) -> ComparableOut:
        left = item.sold_at or item.delisted_at
        return ComparableOut(
            item_id=item.id,
            title=item.title,
            site_name=site_names.get(item.site_id),
            price=item.current_price,
            currency=item.currency,
            condition_grade_label=traits.GRADE_LABELS.get(item.condition_grade or ""),
            left_at=left if not item.is_active or item.is_sold else None,
            marked_sold=item.sold_at is not None,
        )

    return ComparablesOut(
        model=row.firearm_model.name if row.firearm_model else None,
        grade_label=traits.GRADE_LABELS.get(found.grade or ""),
        valuation=_valuation_out(found.valuation) if found.valuation else None,
        departed=[listed(item) for item in found.departed],
        shelf=[listed(item) for item in found.shelf],
        limit=collection.MAX_COMPARABLES,
    )


@router.patch("/{row_id}", response_model=CollectionItemOut)
def update_collection_item(
    row_id: int, payload: CollectionItemUpdate, user: CurrentUser, session: DbSession
) -> CollectionItemOut:
    row = _owned(session, user, row_id)
    sent = payload.model_fields_set
    rematch = False
    if "title" in sent and payload.title:
        # A new title is matched again only when there is no model to keep:
        # one the owner chose, or one they let stand, is not overwritten by
        # rewording the name.
        rematch = payload.title.strip() != row.title and row.firearm_model_id is None
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
    if "firearm_model_id" in sent:
        if payload.firearm_model_id is None:
            row.firearm_model_id = None
            row.model_declined = True
        else:
            row.firearm_model_id = _chosen_model(session, payload.firearm_model_id).id
            row.model_declined = False
        rematch = False
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
