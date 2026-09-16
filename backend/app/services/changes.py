"""A week in review of the catalog itself.

Deliberately not the per-user email. That one is a shopping list: each person's
sites, each person's price floor, capped per site so it fits in a preview pane.
This is the other question — *what happened to the catalog* — and it is the
same answer for everybody, which is why it is a page rather than a message.

What it adds over the digest is mostly what the digest cannot carry:

* **What left.** A digest is about arrivals, so a listing that sold or was
  taken down is invisible in it. Half of what happens in a week is departures.
* **Which shops were quiet.** A site that produced nothing all week is either a
  slow shop or a broken scraper, and nothing else in the application puts those
  two next to each other and makes you look at them. It is the single most
  useful line here and the reason the per-site table lists every enabled site
  rather than only the ones with something to show.
* **What the catalog learned.** A caliber, a country or a maker seen for the
  first time is either a genuinely new kind of stock or a classification rule
  that has started matching something it should not.

**Every count is over the window, and the window is closed at both ends.**
Anything else double-counts against a page somebody reloads: "since a week ago"
moves while you read it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Item, ScanRun, ScanStatus, Site, utcnow

#: How far back the page looks by default, and the most it will look.
#:
#: Capped because the queries are unbounded scans over `items` and the page is
#: reachable by every signed-in user. A year of "what changed" is a report, not
#: a page, and wants writing as one.
DEFAULT_DAYS = 7
MAX_DAYS = 90

#: How many listings each highlight list carries.
#:
#: Short on purpose. This is a page somebody reads in a minute before deciding
#: whether to go looking properly, and a hundred rows is the browse view with
#: extra steps.
HIGHLIGHTS = 8

#: A price drop has to be worth a line. Below this it is a rounding change or a
#: shipping recalculation, and the catalog has plenty of both.
MIN_DROP = 5.0


@dataclass
class SiteWeek:
    """One shop's week."""

    site_id: int
    slug: str
    name: str
    added: int = 0
    sold: int = 0
    delisted: int = 0
    reduced: int = 0
    #: Live listings right now, for scale: three new guns out of nine is a busy
    #: week and out of nine hundred is a quiet one.
    active: int = 0
    enabled: bool = True
    last_success_at: datetime | None = None
    #: A scan ran and failed inside the window. Distinct from "nothing
    #: happened" and the difference the operator is actually looking for.
    failed_scans: int = 0

    @property
    def silent(self) -> bool:
        """Nothing at all changed here this week.

        Not an error on its own -- plenty of shops restock monthly -- but it is
        what a broken scraper looks like too, and the two are only told apart
        by looking.
        """
        return not (self.added or self.sold or self.delisted or self.reduced)


@dataclass
class Highlight:
    """One listing worth a line, with the reason it earned one."""

    item_id: int
    title: str
    site_name: str
    url: str
    currency: str
    price: float | None = None
    was: float | None = None
    photo_url: str | None = None

    @property
    def drop(self) -> float | None:
        if self.was is None or self.price is None:
            return None
        return round(self.was - self.price, 2)

    @property
    def drop_percent(self) -> float | None:
        if self.was is None or self.price is None or self.was <= 0:
            return None
        return round((self.was - self.price) / self.was * 100, 1)


@dataclass
class Week:
    """Everything the page shows."""

    since: datetime
    until: datetime
    days: int
    added: int = 0
    sold: int = 0
    delisted: int = 0
    reduced: int = 0
    active_now: int = 0
    #: Sum of the reductions, which is the one number that says how much the
    #: week was worth in the only unit the catalog has.
    total_reduction: float = 0.0
    sites: list[SiteWeek] = field(default_factory=list)
    biggest_drops: list[Highlight] = field(default_factory=list)
    arrivals: list[Highlight] = field(default_factory=list)
    new_calibers: list[str] = field(default_factory=list)
    new_countries: list[str] = field(default_factory=list)
    new_manufacturers: list[str] = field(default_factory=list)


def window(days: int = DEFAULT_DAYS, until: datetime | None = None) -> tuple[datetime, datetime]:
    """The closed interval the whole page is computed over."""
    end = until or utcnow()
    return end - timedelta(days=max(1, min(days, MAX_DAYS))), end


def _reduced_clause(since: datetime, until: datetime):
    """Listings whose price fell inside the window, by enough to matter.

    ``previous_price`` holds one step of history, so this is "the last change
    was a reduction and it happened this week" rather than "the price is lower
    than it was a week ago". The second question needs `price_history` and a
    different page; this one matches what the digest means by a price drop, so
    the two never disagree in front of somebody comparing them.
    """
    return (
        Item.price_changed_at.is_not(None),
        Item.price_changed_at > since,
        Item.price_changed_at <= until,
        Item.previous_price.is_not(None),
        Item.current_price.is_not(None),
        Item.current_price < Item.previous_price,
        Item.previous_price - Item.current_price >= MIN_DROP,
    )


def _counts_by_site(session: Session, *clauses) -> dict[int, int]:
    rows = session.execute(
        select(Item.site_id, func.count(Item.id)).where(*clauses).group_by(Item.site_id)
    ).all()
    return {int(site_id): int(count) for site_id, count in rows}


def _first_seen_values(
    session: Session, column, since: datetime, until: datetime, limit: int = 12
) -> list[str]:
    """Values whose *first* listing anywhere arrived inside the window.

    Asked as "the earliest listing carrying this value is recent" rather than
    "this value appears on a recent listing", which would name every caliber in
    the catalog every week. The subquery is over the whole of `items` because
    a value is new to the catalog or it is not -- a per-site version of this
    would call a Mosin new every time a second shop stocked one.
    """
    earliest = (
        select(column.label("value"), func.min(Item.first_seen_at).label("first_at"))
        .where(column.is_not(None), column != "")
        .group_by(column)
        .subquery()
    )
    rows = session.execute(
        select(earliest.c.value)
        .where(earliest.c.first_at > since, earliest.c.first_at <= until)
        .order_by(earliest.c.first_at.desc())
        .limit(limit)
    ).all()
    return [str(value) for (value,) in rows]


def _highlight(item: Item, site_names: dict[int, str]) -> Highlight:
    return Highlight(
        item_id=item.id,
        title=item.title,
        site_name=site_names.get(item.site_id, ""),
        url=item.url,
        currency=item.currency,
        price=item.current_price,
        was=item.previous_price,
    )


def summarize(session: Session, days: int = DEFAULT_DAYS, until: datetime | None = None) -> Week:
    """The whole page, in one pass per question."""
    since, end = window(days, until)
    week = Week(since=since, until=end, days=(end - since).days or 1)

    sites = session.execute(select(Site).order_by(Site.name)).scalars().all()
    site_names = {site.id: site.name for site in sites}

    added_clauses = (Item.first_seen_at > since, Item.first_seen_at <= end)
    sold_clauses = (
        Item.is_sold.is_(True),
        Item.last_seen_at > since,
        Item.last_seen_at <= end,
    )
    gone_clauses = (
        Item.delisted_at.is_not(None),
        Item.delisted_at > since,
        Item.delisted_at <= end,
    )
    reduced_clauses = _reduced_clause(since, end)

    added = _counts_by_site(session, *added_clauses)
    sold = _counts_by_site(session, *sold_clauses)
    gone = _counts_by_site(session, *gone_clauses)
    reduced = _counts_by_site(session, *reduced_clauses)
    active = _counts_by_site(session, Item.is_active.is_(True), Item.is_sold.is_(False))

    failures = {
        int(site_id): int(count)
        for site_id, count in session.execute(
            select(ScanRun.site_id, func.count(ScanRun.id))
            .where(
                ScanRun.status == ScanStatus.FAILED,
                ScanRun.started_at > since,
                ScanRun.started_at <= end,
            )
            .group_by(ScanRun.site_id)
        ).all()
    }

    # Every enabled site, including the ones with nothing to report -- a shop
    # that went quiet is the finding, and it can only be found by listing the
    # shops that reported nothing. Plus any *disabled* site that nonetheless
    # had activity in the window, because a site turned off on Wednesday still
    # had a Monday and dropping it would lose those rows from a total the
    # headline numbers still count.
    for site in sites:
        stirred = bool(
            added.get(site.id) or sold.get(site.id) or gone.get(site.id) or reduced.get(site.id)
        )
        if not site.enabled and not stirred:
            continue
        week.sites.append(
            SiteWeek(
                site_id=site.id,
                slug=site.slug,
                name=site.name,
                enabled=site.enabled,
                added=added.get(site.id, 0),
                sold=sold.get(site.id, 0),
                delisted=gone.get(site.id, 0),
                reduced=reduced.get(site.id, 0),
                active=active.get(site.id, 0),
                last_success_at=site.last_success_at,
                failed_scans=failures.get(site.id, 0),
            )
        )

    week.added = sum(added.values())
    week.sold = sum(sold.values())
    week.delisted = sum(gone.values())
    week.reduced = sum(reduced.values())
    week.active_now = sum(active.values())

    total = session.execute(
        select(func.sum(Item.previous_price - Item.current_price)).where(*reduced_clauses)
    ).scalar()
    week.total_reduction = round(float(total or 0.0), 2)

    drops = (
        session.execute(
            select(Item)
            .where(*reduced_clauses)
            .order_by((Item.previous_price - Item.current_price).desc())
            .limit(HIGHLIGHTS)
        )
        .scalars()
        .all()
    )
    week.biggest_drops = [_highlight(item, site_names) for item in drops]

    # Arrivals are ranked by price, not by recency. "Newest" is what the browse
    # view already answers and answers better; what a week in review is for is
    # the thing that turned up and is worth crossing the room for.
    arrivals = (
        session.execute(
            select(Item)
            .where(
                *added_clauses,
                Item.is_active.is_(True),
                Item.is_sold.is_(False),
                Item.current_price.is_not(None),
            )
            .order_by(Item.current_price.desc())
            .limit(HIGHLIGHTS)
        )
        .scalars()
        .all()
    )
    week.arrivals = [
        Highlight(
            item_id=item.id,
            title=item.title,
            site_name=site_names.get(item.site_id, ""),
            url=item.url,
            currency=item.currency,
            price=item.current_price,
        )
        for item in arrivals
    ]

    week.new_calibers = _first_seen_values(session, Item.caliber, since, end)
    week.new_countries = _first_seen_values(session, Item.country, since, end)
    week.new_manufacturers = _first_seen_values(session, Item.manufacturer, since, end)
    return week
