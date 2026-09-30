"""A reader's own guns, and what the market says they are worth.

Everything else in this application is about buying. This is about having
bought: a list of what somebody owns, what they paid, and -- because the
catalog already knows what every armory model goes for -- what each one is
worth now. It is what keeps the application useful between purchases, and it
is the list an insurer asks for.

**How a gun is valued.** Against the listings of the same armory model, which
is why a row is matched to one from its title the way a scan matches a
listing. Two numbers are worked out, and the better one leads:

* *What guns of this model were asking when they left the shelf* (see
  ``market.departure_band``). The nearest thing to a sale price the catalog
  has, and preferred whenever there is a sample of it.
* *What they are asking now*, the median of the model's live listings. Always
  the bigger sample, and always a little high: a shelf over-represents
  whatever has not sold.

**Like with like, where the sample allows.** A row carrying its owner's grade
is compared first against listings of the same model *and* the same stated
condition (see ``app.services.traits``) -- a "very good" K31 against very good
K31s -- and only against the whole model when there are too few of those.
Which basis was used is returned beside the number, so the page can say so.

**No valuation from a caliber.** A 7.62x54R could be a $300 Mosin or a $3,000
SVT; a median across both describes neither gun. A row that matched no model
says that it could not be valued, rather than inventing a number.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CollectionItem, Item
from . import armory, market, traits


@dataclass(frozen=True)
class Valuation:
    """What one owned gun is worth, and what that was worked out from."""

    #: The figure to show: the departure median where there is one, the shelf
    #: median otherwise.
    estimate: float
    #: "left" or "shelf" -- which of the two ``estimate`` is.
    basis: str
    #: Whether both samples were narrowed to the owner's stated condition.
    like_for_like: bool
    shelf: market.Band | None
    departed: market.Band | None


def _shelf_band(session: Session, model_id: int, grade: str | None) -> market.Band | None:
    statement = select(Item.current_price, Item.currency, Item.site_id).where(
        Item.firearm_model_id == model_id,
        Item.is_active.is_(True),
        Item.is_sold.is_(False),
        Item.is_parts_kit.is_(False),
        Item.is_rifle.is_(True) | Item.is_pistol.is_(True),
        Item.current_price.is_not(None),
        Item.current_price > 0,
    )
    if grade is not None:
        statement = statement.where(Item.condition_grade == grade)
    rows = session.execute(statement).all()
    if len(rows) < market.MIN_SAMPLE:
        return None
    shops: Counter[int] = Counter(site_id for _p, _c, site_id in rows)
    # The query excludes a missing price; the test is for the type checker.
    prices = [float(p) for p, _c, _s in rows if p is not None]
    return market.make_band(str(model_id), prices, rows[0][1] or "USD", shops)


def value(session: Session, row: CollectionItem) -> Valuation | None:
    """What this gun is worth, or None when there is nothing to judge it by."""
    if row.firearm_model_id is None:
        return None
    model_id = row.firearm_model_id
    same_model = Item.firearm_model_id == model_id

    grade = row.condition_grade if row.condition_grade in traits.GRADES else None
    if grade is not None:
        shelf = _shelf_band(session, model_id, grade)
        departed = market.departure_band(
            session, "model", same_model & (Item.condition_grade == grade)
        )
        if shelf is not None or departed is not None:
            return _choose(shelf, departed, like_for_like=True)

    return _choose(
        _shelf_band(session, model_id, None),
        market.departure_band(session, "model", same_model),
        like_for_like=False,
    )


def _choose(
    shelf: market.Band | None, departed: market.Band | None, *, like_for_like: bool
) -> Valuation | None:
    if departed is not None:
        return Valuation(departed.median, "left", like_for_like, shelf, departed)
    if shelf is not None:
        return Valuation(shelf.median, "shelf", like_for_like, shelf, departed)
    return None


def match_model(session: Session, row: CollectionItem) -> None:
    """Match the row's title to an armory model, and fill what that says.

    Only while the owner has not said the match was wrong, and only filling
    blanks: a caliber or a maker the owner typed is theirs.
    """
    if row.model_declined:
        row.firearm_model_id = None
        return
    found = armory.fill_in(session, row.title, None, row.caliber, is_firearm=True)
    row.firearm_model_id = found.model_id
    if found.caliber and not row.caliber:
        row.caliber = found.caliber
    if found.manufacturer and not row.manufacturer:
        row.manufacturer = found.manufacturer


@dataclass(frozen=True)
class Totals:
    count: int
    #: What was paid, over the rows that say.
    paid: float
    paid_count: int
    #: What the valued rows are worth.
    value: float
    valued_count: int
    #: The rows with both a price paid and a value, and the two sums over only
    #: those -- so "up 12%" compares the same guns on both sides rather than
    #: every purchase against only the ones the market could price.
    compared_count: int
    compared_paid: float
    compared_value: float


def totals(rows: list[tuple[CollectionItem, Valuation | None]]) -> Totals:
    paid = [row.paid for row, _v in rows if row.paid is not None]
    valued = [found.estimate for _row, found in rows if found is not None]
    both = [(row.paid, found.estimate) for row, found in rows if found and row.paid is not None]
    return Totals(
        count=len(rows),
        paid=round(sum(paid), 2),
        paid_count=len(paid),
        value=round(sum(valued), 2),
        valued_count=len(valued),
        compared_count=len(both),
        compared_paid=round(sum(p for p, _v in both), 2),
        compared_value=round(sum(v for _p, v in both), 2),
    )
