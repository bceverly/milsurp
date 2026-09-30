"""Want lists: a saved search that tells you the moment one appears.

People think in wants, not filters: "an Inland M1 Carbine, not refinished,
under $1,400". The browse page can already say all of that -- the price slider
is the ceiling, the collector details are the rest -- and a saved search can
already remember it. What it could not do is interrupt anybody. It waited for
the digest, and a surplus bargain that waits a day is usually a sold one.

So a saved search can be switched to alert instantly. On every scheduler tick
each such search is asked one question: **what matches it now that did not
have a reason to be news before?** Three things make a listing news:

* it was first seen after the alert was switched on;
* its price dropped after then, which is how a listing that was $1,450 comes
  under a $1,400 ceiling; or
* it came back in stock after then.

**Once per listing.** Each listing a search has announced is recorded
(``saved_search_alerts``), so a rifle that drops $50 twice under the ceiling is
one message. And **never the backlog**: switching the alert on stamps
``alert_since``, so the forty listings already matching -- the ones the search
page already shows -- are not mailed at once.

Only what is for sale. A saved search may ask for sold listings, as a research
question; an alert about one would be telling somebody about a thing they can
no longer buy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.orm import Session

from ..models import Item, SavedSearch, SavedSearchAlert, User, utcnow
from . import search

log = logging.getLogger("milsurp.wantlist")

#: The most listings one alert carries per search. A want list that suddenly
#: matches fifty listings has probably had its filters widened; the message
#: says how many more there are and links to the search.
MAX_PER_SEARCH = 10


def _news_since(since: datetime):
    """The three ways a listing becomes worth telling somebody about."""
    return or_(
        Item.first_seen_at >= since,
        and_(
            Item.price_changed_at.is_not(None),
            Item.price_changed_at >= since,
            Item.previous_price.is_not(None),
            Item.current_price.is_not(None),
            Item.current_price < Item.previous_price,
        ),
        and_(Item.restocked_at.is_not(None), Item.restocked_at >= since),
    )


def _fresh_statement(row: SavedSearch) -> tuple[Select[Item] | None, str | None]:
    """The query for what this search has to announce, or None.

    A query that no longer parses -- a filter this release does not know --
    announces nothing and says so in the log, rather than raising: one rotten
    row must not stop every other reader's alerts.
    """
    if not row.alert_instantly or row.alert_since is None:
        return None, None
    try:
        parsed = search.parse_query(row.query)
    except search.BadQuery:
        log.warning("Saved search %s no longer parses; no alert.", row.id)
        return None, None

    filters = dict(parsed.filters)
    filters["availability"] = "available"
    told = exists().where(
        SavedSearchAlert.saved_search_id == row.id, SavedSearchAlert.item_id == Item.id
    )
    statement = search.apply_filters(select(Item), **filters).where(
        _news_since(row.alert_since), ~told
    )
    return statement, parsed.sort


@dataclass
class Want:
    """One search's news: what to show, and every listing it covers."""

    search: SavedSearch
    #: Up to MAX_PER_SEARCH, in the search's own order.
    items: list[Item]
    #: Every fresh match, shown or not -- what :func:`mark` records.
    ids: list[int] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.ids)

    def as_section(self) -> tuple[SavedSearch, list[Item], int]:
        """The shape the digest's saved-search block renders."""
        return self.search, self.items, self.total


def fresh_matches(session: Session, row: SavedSearch) -> Want | None:
    """What this search has to announce, or None when nothing is."""
    statement, sort = _fresh_statement(row)
    if statement is None or sort is None:
        return None
    found: list[Item] = list(
        session.execute(statement.order_by(*search.SORTS[sort])).scalars().unique().all()
    )
    if not found:
        return None
    return Want(search=row, items=found[:MAX_PER_SEARCH], ids=[item.id for item in found])


def due(session: Session) -> dict[int, list[Want]]:
    """Every reader with something to hear, and what, by user id."""
    rows = (
        session.execute(
            select(SavedSearch)
            .join(User, User.id == SavedSearch.user_id)
            .where(SavedSearch.alert_instantly.is_(True), User.is_active.is_(True))
            .order_by(SavedSearch.user_id, SavedSearch.id)
        )
        .scalars()
        .all()
    )
    found: dict[int, list[Want]] = {}
    for row in rows:
        want = fresh_matches(session, row)
        if want:
            found.setdefault(row.user_id, []).append(want)
    return found


def mark(session: Session, wants: list[Want], when: datetime | None = None) -> None:
    """Record that these listings were announced, so they are not again.

    Every fresh match is marked, not only the ten that were shown: the message
    said how many more there were and linked to them, and announcing the
    eleventh on the next tick would be the same news twice. The ids are the
    ones found when the message was built, not re-read now -- a listing that
    arrived in between has not been announced and must stay news.
    """
    when = when or utcnow()
    for want in wants:
        for item_id in want.ids:
            session.add(
                SavedSearchAlert(saved_search_id=want.search.id, item_id=item_id, alerted_at=when)
            )


def switch(row: SavedSearch, on: bool, now: datetime | None = None) -> None:
    """Turn a search's instant alert on or off.

    Switching it on stamps ``alert_since``, so only what changes from now on
    is news. Switching it off leaves the record of what was announced: turning
    it back on later starts a new watermark anyway.
    """
    if on and not row.alert_instantly:
        row.alert_since = now or utcnow()
    row.alert_instantly = on
