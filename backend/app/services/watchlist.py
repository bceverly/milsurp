"""The listings a user is following, and what counts as news about one.

The catalog answers "what is on the shelves" and, since the price spectrum,
"is this a good deal". It could not answer "tell me when *that one* moves" --
the question somebody has about the rifle they have decided they want and will
not pay this week's price for. The only way to find out was to come back and
look, which is what a monitor is meant to save you.

**What counts as news is defined once, here**, rather than in the digest that
mails it and again in the page that shows it. Three things are worth an email
and the rest are not:

* it **sold**, or was de-listed -- the end of the story either way, and the one
  a watcher most needs to hear because nothing else will tell them;
* its **price moved** at all, for a watch with no target;
* its price reached a **target** the watcher set.

A watch with a target is deliberately quiet about movement away from it. The
whole point of naming a number is "do not tell me until then", and a rifle
drifting from $900 to $925 is not the thing somebody waiting for $700 asked to
hear about.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Item, User, WatchedItem


class News(str, enum.Enum):
    """Why a watched listing is in the email."""

    SOLD = "sold"
    GONE = "gone"
    TARGET = "target"
    CHEAPER = "cheaper"
    DEARER = "dearer"


#: What each reads as. Server-side, so the digest and the watchlist page cannot
#: drift on the wording.
HEADLINES = {
    News.SOLD: "Sold",
    News.GONE: "No longer listed",
    News.TARGET: "Reached your target",
    News.CHEAPER: "Price dropped",
    News.DEARER: "Price rose",
}


@dataclass(frozen=True)
class Update:
    """One watched listing with something to report."""

    watch: WatchedItem
    item: Item
    news: News

    @property
    def headline(self) -> str:
        return HEADLINES[self.news]


def for_user(session: Session, user: User) -> list[WatchedItem]:
    """Everything this user is watching, newest first."""
    return list(
        session.execute(
            select(WatchedItem)
            .options(selectinload(WatchedItem.item).selectinload(Item.site))
            .where(WatchedItem.user_id == user.id)
            .order_by(WatchedItem.created_at.desc(), WatchedItem.id.desc())
        )
        .scalars()
        .all()
    )


def watching(session: Session, user: User, item_id: int) -> WatchedItem | None:
    return session.execute(
        select(WatchedItem).where(WatchedItem.user_id == user.id, WatchedItem.item_id == item_id)
    ).scalar_one_or_none()


def news_for(  # noqa: PLR0911 - one return per kind of news, which is the shape
    watch: WatchedItem, item: Item, since: datetime
) -> News | None:
    """What to say about this listing, or None for "nothing since last time".

    ``since`` is the digest's own watermark, so this needs no state of its own:
    a listing reports once per digest and the next one starts from where that
    finished. Storing "last notified price" here instead would be a second
    clock to keep wound, and one that disagrees with the digest's the first
    time an email fails to send.
    """
    if item.is_sold:
        return News.SOLD if _after(item.price_changed_at or item.last_seen_at, since) else None
    if not item.is_active:
        return News.GONE if _after(item.delisted_at or item.last_seen_at, since) else None

    if not _after(item.price_changed_at, since):
        return None
    if item.current_price is None:
        return None

    if watch.target_price is not None:
        # Silent unless it has arrived. Naming a number means "do not tell me
        # until then", and a rifle drifting from $900 to $925 is not news to
        # somebody waiting for $700.
        return News.TARGET if item.current_price <= watch.target_price else None
    if item.previous_price is None:
        return None
    if item.current_price < item.previous_price:
        return News.CHEAPER
    if item.current_price > item.previous_price:
        return News.DEARER
    return None


def _after(moment: datetime | None, since: datetime) -> bool:
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=since.tzinfo)
    return moment > since


def updates(session: Session, user: User, since: datetime) -> list[Update]:
    """Everything worth telling this user about their watchlist.

    Ordered by how much it matters: an ending first, then a target reached,
    then ordinary movement. A watcher scanning one email wants the rifle that
    sold before the one that went up eleven dollars.
    """
    order = {News.SOLD: 0, News.GONE: 1, News.TARGET: 2, News.CHEAPER: 3, News.DEARER: 4}
    found: list[Update] = []
    for watch in for_user(session, user):
        item = watch.item
        if item is None:
            continue
        news = news_for(watch, item, since)
        if news is not None:
            found.append(Update(watch=watch, item=item, news=news))
    found.sort(key=lambda update: (order[update.news], update.item.title or ""))
    return found
