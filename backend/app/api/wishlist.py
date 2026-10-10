"""The listings a reader means to buy, added up. See app.services.wishlist.

Scoped to ``CurrentUser.id`` like the watchlist: what somebody plans to buy is
theirs alone.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession
from ..models import CollectionItem, Item, Site
from ..schemas import (
    CollectionItemOut,
    WishlistLineOut,
    WishlistOut,
    WishlistSettingsIn,
    WishlistTotalsOut,
)
from ..services import collection, wishlist
from .collection import _out as _collection_out
from .collection import _valuation_out

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


def _line_out(line: wishlist.Line, site_names: dict[int, str]) -> WishlistLineOut:
    from .items import _to_out

    item = _to_out(line.item, site_names)
    item.wishlisted = True
    return WishlistLineOut(
        item=item,
        added_at=line.entry.added_at,
        for_sale=line.for_sale,
        price=line.price,
        shipping=line.shipping,
        shipping_note=line.shipping_note,
        curio=line.curio,
        fee=line.fee,
        fee_waived=line.fee_waived,
        fee_missing=line.fee_missing,
        total=line.total,
        complete=line.complete,
        valuation=_valuation_out(line.valuation) if line.valuation else None,
        profit=line.profit,
        price_when_added=line.entry.price_when_added,
        since_added=line.since_added,
    )


def _wishlist_out(session: DbSession, user: CurrentUser) -> WishlistOut:
    found = wishlist.build(session, user)
    site_names = dict(session.execute(select(Site.id, Site.name)).all())
    totals = found.totals
    return WishlistOut(
        lines=[_line_out(line, site_names) for line in found.lines],
        totals=WishlistTotalsOut(
            count=totals.count,
            for_sale=totals.for_sale,
            cost=totals.cost,
            cost_complete=totals.cost_complete,
            unpriced=totals.unpriced,
            value=totals.value,
            valued=totals.valued,
            compared=totals.compared,
            compared_cost=totals.compared_cost,
            compared_value=totals.compared_value,
            profit=totals.profit,
        ),
        ffl_transfer_fee=user.ffl_transfer_fee,
        ffl_dealer=user.cheapest_dealer.name if user.cheapest_dealer else None,
        has_cr_license=user.has_cr_license,
        wishlist_alerts=user.wishlist_alerts,
        budget=user.wishlist_budget,
    )


@router.get("", response_model=WishlistOut)
def get_wishlist(user: CurrentUser, session: DbSession) -> WishlistOut:
    return _wishlist_out(session, user)


# Before the /{item_id} routes, which would otherwise try to read "settings"
# and "export" as a listing number.
@router.put("/settings", response_model=WishlistOut)
def save_settings(
    payload: WishlistSettingsIn, user: CurrentUser, session: DbSession
) -> WishlistOut:
    """Alerts on or off, and the budget. Switching alerts on starts from now."""
    if payload.alerts is not None:
        wishlist.set_alerts(session, user, payload.alerts)
    if "budget" in payload.model_fields_set:
        user.wishlist_budget = payload.budget
    session.commit()
    return _wishlist_out(session, user)


#: The columns of the export, in order, and what each reads off a line.
_EXPORT = {
    "title": lambda line: line.item.title,
    "shop": lambda line: line.site_name,
    "url": lambda line: line.item.url,
    "status": lambda line: wishlist.state_of(line.item),
    "price": lambda line: line.price,
    "shipping": lambda line: line.shipping,
    "transfer_fee": lambda line: line.fee,
    "total": lambda line: line.total,
    "total_complete": lambda line: line.complete,
    "worth": lambda line: line.valuation.estimate if line.valuation else None,
    "profit": lambda line: line.profit,
    "price_when_added": lambda line: line.entry.price_when_added,
    "added": lambda line: line.entry.added_at.date().isoformat(),
}


def _cell(value: object) -> object:
    """A spreadsheet cell that cannot be read as a formula.

    Titles come from vendors' pages, and a cell starting with "=" is run by
    the spreadsheet that opens it.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@router.get("/export")
def export_wishlist(user: CurrentUser, session: DbSession) -> Response:
    """The wishlist as a spreadsheet, every line and the figures on it."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(_EXPORT))
    for line in wishlist.build(session, user).lines:
        writer.writerow([_cell(read(line)) for read in _EXPORT.values()])
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="wishlist-{stamp}.csv"'},
    )


@router.put("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_to_wishlist(item_id: int, user: CurrentUser, session: DbSession) -> Response:
    """Put a listing on the wishlist. PUT because it is a state: twice is once."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such listing")
    wishlist.add(session, user, item)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_wishlist(item_id: int, user: CurrentUser, session: DbSession) -> Response:
    """Take a listing off. Taking off one that was not on is not an error."""
    wishlist.remove(session, user, item_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{item_id}/bought", response_model=CollectionItemOut, status_code=status.HTTP_201_CREATED
)
def bought_it(item_id: int, user: CurrentUser, session: DbSession) -> CollectionItemOut:
    """ "Bought it": into the collection at its delivered total, off the wishlist.

    What was paid is the line's total -- price, shipping and fee -- since that
    is what the gun cost, and the collection's gain or loss should start from
    it. Like "I bought this", every field can be corrected afterwards.
    """
    line = next(
        (line for line in wishlist.build(session, user).lines if line.item.id == item_id), None
    )
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your wishlist")
    item = line.item
    row = CollectionItem(
        user_id=user.id,
        title=item.title[:200],
        firearm_model_id=item.firearm_model_id,
        caliber=item.caliber,
        manufacturer=item.manufacturer,
        condition_grade=item.condition_grade,
        acquired_on=datetime.now(UTC).date(),
        paid=line.total,
        acquired_from=line.site_name,
        item_id=item.id,
    )
    if row.firearm_model_id is None:
        collection.match_model(session, row)
    session.add(row)
    wishlist.remove(session, user, item.id)
    session.commit()
    session.refresh(row)
    return _collection_out(row, collection.value(session, row))
