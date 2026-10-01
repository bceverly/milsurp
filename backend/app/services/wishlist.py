"""The wishlist: what the guns somebody means to buy would cost, and be worth.

A watch follows a listing's price. A wishlist entry is a plan, and a plan wants
adding up: for each gun, its price, the shop's shipping and the dealer's
transfer fee, the total delivered -- and set against it, what a gun of that
model in that condition is worth, so each line and the whole list say whether
the money would hold its value.

**The transfer fee follows the license.** A reader who holds a C&R license
(``User.has_cr_license``) receives a C&R-eligible gun directly, with no dealer
and no fee; everybody else, and every gun that is not eligible, goes through a
dealer at the reader's own fee (``User.ffl_transfer_fee``). A gun whose
eligibility is not known is charged the fee: guessing in the reader's favor is
how a budget comes up short.

**Nothing is made up.** Shipping is the shop's own stated figure or it is
missing, and a total with a missing part is marked incomplete -- "at least" --
rather than treating it as free. The worth is the collection's valuation
(``collection.value_of``) with the listing itself left out of its own
yardstick. It is drawn from asking prices: what the model was asking when it
left the shelf, or what it asks now -- the market's price, not what a dealer
would pay you for it, which is usually less. A gun the market cannot price
has no worth and no profit, rather than a guessed one.

**Only what is for sale counts.** A listing that sells or comes down stays on
the list, marked, so the reader sees it went; it is left out of the totals,
since it can no longer be bought.

**Alerts are opt-in and report changes, not the backlog.** With
``User.wishlist_alerts`` on, a listing that sells, comes down, comes back or
changes price is emailed and pushed on the scheduler's next tick. Each entry
remembers what it last said (``told_price``, ``told_state``), set when the
entry is made and again when alerts are switched on, so switching them on does
not mail every change since the list was started. The digest carries the same
news on its own clock, through ``watchlist.news_about``, for every reader with
a wishlist whether or not alerts are on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Item, Site, User, WishlistItem, utcnow
from . import collection, curio, delivered
from .watchlist import HEADLINES, News, news_about

FOR_SALE = "for_sale"
SOLD = "sold"
GONE = "gone"


def state_of(item: Item) -> str:
    """For sale, sold, or no longer listed."""
    if item.is_sold:
        return SOLD
    return FOR_SALE if item.is_active else GONE


@dataclass
class Line:
    """One wished-for listing, priced to the door and set against its worth."""

    entry: WishlistItem
    item: Item
    site_name: str | None
    for_sale: bool
    price: float | None
    shipping: float | None
    shipping_note: str | None
    #: The C&R verdict, for a firearm: eligible, not_eligible or unknown.
    curio: str | None
    #: The transfer fee charged on this line, None when none is charged or the
    #: reader has not set theirs; ``fee_waived`` says which of those it is.
    fee: float | None
    fee_waived: bool
    fee_missing: bool
    total: float | None
    #: Every part of the total is known.
    complete: bool
    valuation: collection.Valuation | None = None

    @property
    def since_added(self) -> float | None:
        """How far the asking price has moved since the entry was made."""
        added = self.entry.price_when_added
        if added is None or self.price is None:
            return None
        return round(self.price - added, 2)

    @property
    def profit(self) -> float | None:
        if self.valuation is None or self.total is None:
            return None
        return round(self.valuation.estimate - self.total, 2)


@dataclass
class Totals:
    count: int = 0
    for_sale: int = 0
    #: The delivered cost of everything for sale with a price.
    cost: float = 0.0
    #: Every one of those totals is complete; otherwise the sum is a floor.
    cost_complete: bool = True
    unpriced: int = 0
    #: What the for-sale guns the market can price are worth.
    value: float = 0.0
    valued: int = 0
    #: Over the lines with both a total and a worth, so profit compares the
    #: same guns on both sides.
    compared: int = 0
    compared_cost: float = 0.0
    compared_value: float = 0.0

    @property
    def profit(self) -> float:
        return round(self.compared_value - self.compared_cost, 2)


@dataclass
class Wishlist:
    lines: list[Line] = field(default_factory=list)
    totals: Totals = field(default_factory=Totals)


def entries(session: Session, user: User) -> list[WishlistItem]:
    return list(
        session.execute(
            select(WishlistItem)
            .options(selectinload(WishlistItem.item))
            .where(WishlistItem.user_id == user.id)
            .order_by(WishlistItem.added_at.desc(), WishlistItem.id.desc())
        )
        .scalars()
        .all()
    )


def _fee(user: User, item: Item, status: str | None) -> tuple[float | None, bool, bool]:
    """(fee charged, waived, missing) for one gun."""
    if not delivered.is_firearm(item):
        return None, False, False
    if user.has_cr_license and status == curio.ELIGIBLE:
        return None, True, False
    if user.ffl_transfer_fee is None:
        return None, False, True
    return float(user.ffl_transfer_fee), False, False


def build(session: Session, user: User) -> Wishlist:
    """Every line of this reader's wishlist, and the totals."""
    costs = delivered.Costs.load(session, user)
    site_names = dict(session.execute(select(Site.id, Site.name)).all())
    found = Wishlist()
    for entry in entries(session, user):
        item = entry.item
        firearm = delivered.is_firearm(item)
        status = curio.status(item.cr_stated, item.manufacture_year) if firearm else None
        fee, waived, missing = _fee(user, item, status)
        shipping = costs.shipping(item)
        price = float(item.current_price) if item.current_price is not None else None
        shipping_missing = firearm and shipping is None
        total = None if price is None else round(price + (shipping or 0.0) + (fee or 0.0), 2)
        rates = costs.by_site.get(item.site_id)
        line = Line(
            entry=entry,
            item=item,
            site_name=site_names.get(item.site_id),
            for_sale=bool(item.is_active and not item.is_sold),
            price=price,
            shipping=shipping,
            shipping_note=rates.note if rates else None,
            curio=status,
            fee=fee,
            fee_waived=waived,
            fee_missing=missing,
            total=total,
            complete=total is not None and not shipping_missing and not missing,
        )
        if firearm and item.firearm_model_id is not None:
            line.valuation = collection.value_of(
                session, item.firearm_model_id, item.condition_grade, exclude=item.id
            )
        found.lines.append(line)
        _add(found.totals, line)
    return found


def _add(totals: Totals, line: Line) -> None:
    totals.count += 1
    if not line.for_sale:
        return
    totals.for_sale += 1
    if line.total is None:
        totals.unpriced += 1
        return
    totals.cost = round(totals.cost + line.total, 2)
    totals.cost_complete = totals.cost_complete and line.complete
    if line.valuation is not None:
        totals.value = round(totals.value + line.valuation.estimate, 2)
        totals.valued += 1
        totals.compared += 1
        totals.compared_cost = round(totals.compared_cost + line.total, 2)
        totals.compared_value = round(totals.compared_value + line.valuation.estimate, 2)


def add(session: Session, user: User, item: Item) -> WishlistItem:
    """Put a listing on the wishlist. Idempotent: twice is still once."""
    existing = session.execute(
        select(WishlistItem).where(WishlistItem.user_id == user.id, WishlistItem.item_id == item.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    entry = WishlistItem(user_id=user.id, item_id=item.id, price_when_added=item.current_price)
    mark_told(entry, item, utcnow())
    session.add(entry)
    session.flush()
    return entry


def remove(session: Session, user: User, item_id: int) -> bool:
    """Take a listing off. Returns whether it was on."""
    entry = session.execute(
        select(WishlistItem).where(WishlistItem.user_id == user.id, WishlistItem.item_id == item_id)
    ).scalar_one_or_none()
    if entry is None:
        return False
    session.delete(entry)
    session.flush()
    return True


def on_wishlist(session: Session, user: User, item_id: int) -> bool:
    return (
        session.execute(
            select(WishlistItem.id).where(
                WishlistItem.user_id == user.id, WishlistItem.item_id == item_id
            )
        ).first()
        is not None
    )


def ids_on(session: Session, user: User, item_ids: list[int]) -> set[int]:
    """Which of these listings are on this reader's wishlist, for a page of cards."""
    if not item_ids:
        return set()
    return set(
        session.execute(
            select(WishlistItem.item_id).where(
                WishlistItem.user_id == user.id, WishlistItem.item_id.in_(item_ids)
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# What changed
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Update:
    """One wishlist listing with something to report.

    Shaped like ``watchlist.Update`` so the digest renders both the same way:
    a headline, the listing, and no target or note.
    """

    entry: WishlistItem
    item: Item
    news: News
    target_price: float | None = None
    note: str | None = None

    @property
    def headline(self) -> str:
        return HEADLINES[self.news]


def mark_told(entry: WishlistItem, item: Item, when: datetime) -> None:
    """Remember what this entry's listing is now, as the last thing said."""
    entry.told_price = item.current_price
    entry.told_state = state_of(item)
    entry.told_at = when


def alert_news(entry: WishlistItem, item: Item) -> News | None:
    """What changed since the last alert, or None."""
    if entry.told_state is None:
        return None
    now = state_of(item)
    if now != entry.told_state:
        return {SOLD: News.SOLD, GONE: News.GONE, FOR_SALE: News.BACK}[now]
    if now != FOR_SALE or item.current_price is None or entry.told_price is None:
        return None
    if item.current_price < entry.told_price:
        return News.CHEAPER
    if item.current_price > entry.told_price:
        return News.DEARER
    return None


#: An ending first, then a return, then movement, as the watchlist orders it.
_ORDER = {News.SOLD: 0, News.GONE: 1, News.BACK: 2, News.CHEAPER: 3, News.DEARER: 4}


def due_alerts(session: Session) -> dict[int, list[Update]]:
    """Every wishlist change owed an alert, by user id, for readers who asked."""
    rows = (
        session.execute(
            select(WishlistItem)
            .join(User, User.id == WishlistItem.user_id)
            .options(selectinload(WishlistItem.item))
            .where(User.wishlist_alerts.is_(True), User.is_active.is_(True))
        )
        .scalars()
        .all()
    )
    found: dict[int, list[Update]] = {}
    for entry in rows:
        if entry.item is None:
            continue
        news = alert_news(entry, entry.item)
        if news is not None:
            found.setdefault(entry.user_id, []).append(Update(entry, entry.item, news))
    for updates in found.values():
        updates.sort(key=lambda update: (_ORDER[update.news], update.item.title or ""))
    return found


def set_alerts(session: Session, user: User, on: bool) -> None:
    """Switch alerts on or off. On starts from now: the backlog is not news."""
    if on and not user.wishlist_alerts:
        now = utcnow()
        for entry in entries(session, user):
            mark_told(entry, entry.item, now)
    user.wishlist_alerts = on


def digest_updates(
    session: Session, user: User, since: datetime, skip: set[int] | None = None
) -> list[Update]:
    """What the digest says about the wishlist since its watermark.

    ``skip`` is the listings the watchlist section already reports: one
    listing on both lists is said once.
    """
    found = []
    for entry in entries(session, user):
        item = entry.item
        if item is None or item.id in (skip or set()):
            continue
        news = news_about(item, since)
        if news is not None:
            found.append(Update(entry, item, news))
    found.sort(key=lambda update: (_ORDER.get(update.news, 9), update.item.title or ""))
    return found
