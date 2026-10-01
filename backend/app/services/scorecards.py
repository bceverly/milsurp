"""How each shop behaves: what it stocks, when, at what price, and how it sells.

Everything here was already in the database and only ever read per listing.
Read per *shop*, it answers the questions a regular buyer learns the hard way:
does this dealer price above the market, does stock last there, which day do
the new guns go up, and will they mark it down if I wait.

**Measured, and said to be measured from when we started watching.** Every
figure is drawn from what the scans have seen since each shop's first
completed scan. A shop's first scan finds its whole shelf at once, which is
not "new stock", so it is left out of the arrivals; and a listing already on
the shelf then has an unknown age, so it is left out of time-to-sell, as on
the Market page.

**Price against the market** compares each of a shop's guns with the *other*
shops' listings of the same armory model -- at least five of them, across at
least two shops -- and reports the shop's median ratio. Never with its own:
Simpson holds half the catalog, and against medians that included its guns it
came out at exactly 1.0, which said nothing. "8% above the market" means its typical gun
costs 8% more than the typical one of the same model elsewhere.

**The price-cut habit** ("will it drop?") is each shop's reductions: how many
of its listings have been cut, typically how far into the listing, and by how
much. Measured on production 2026-10-01, only four shops had cut ten or more
listings -- Simpson typically about 10% around day 18, Legacy about 9% around
day 8 -- and below ten the habit is not stated, because two reductions are not
a habit.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, PriceHistory, Site, utcnow
from .market import _watching_since

#: Fewer reductions than this and a shop has no habit worth stating.
MIN_DROPS = 10

#: A model's market median needs this many listings, across this many shops.
MIN_MODEL_LISTINGS = 5
MIN_MODEL_SHOPS = 2

#: And a shop's own comparison needs this many of its guns to say anything.
MIN_COMPARED = 5

#: How far back the arrivals by weekday look.
ARRIVAL_DAYS = 28

#: How long a computed habit table is reused. It is read on every listing
#: page, and it moves only when a scan records a reduction.
HABIT_TTL_SECONDS = 3600

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Habit:
    """How a shop cuts prices."""

    drops: int
    #: Days from a listing appearing to its first reduction, the median.
    median_day: float
    #: The size of that first reduction, the median percentage.
    median_pct: float
    #: Of the listings watched at least median_day days, the share cut.
    share: float


@dataclass
class Scorecard:
    site_id: int
    name: str
    slug: str
    guns_for_sale: int = 0
    new_this_week: int = 0
    #: Arrivals over the last ARRIVAL_DAYS by weekday, Monday first.
    arrivals_by_weekday: list[int] = field(default_factory=lambda: [0] * 7)
    #: Median of this shop's price / the model's market median, over the guns
    #: that could be compared, and how many could.
    price_vs_market: float | None = None
    compared: int = 0
    #: Median days on the shelf before selling or coming down, and how many.
    sell_days: float | None = None
    sold_measured: int = 0
    left_last_30_days: int = 0
    habit: Habit | None = None

    @property
    def busiest_day(self) -> str | None:
        if not any(self.arrivals_by_weekday):
            return None
        return WEEKDAYS[max(range(7), key=lambda day: self.arrivals_by_weekday[day])]


def _firearm():
    return (Item.is_rifle.is_(True) | Item.is_pistol.is_(True)) & Item.is_parts_kit.is_(False)


# ---------------------------------------------------------------------------
# Price-cut habits
# ---------------------------------------------------------------------------
_habit_cache: tuple[float, dict[int, Habit]] | None = None


def forget_habits() -> None:
    """Drop the cached table. For the tests, and after a bulk change."""
    global _habit_cache
    _habit_cache = None


def habits(session: Session) -> dict[int, Habit]:
    """Each shop's price-cut habit, by site id, for shops with MIN_DROPS or more."""
    global _habit_cache
    now = time.monotonic()
    if _habit_cache is not None and now - _habit_cache[0] < HABIT_TTL_SECONDS:
        return _habit_cache[1]

    seen = {
        item_id: (site_id, first_seen)
        for item_id, site_id, first_seen in session.execute(
            select(Item.id, Item.site_id, Item.first_seen_at).where(_firearm())
        ).all()
    }
    history: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for item_id, observed_at, price in session.execute(
        select(PriceHistory.item_id, PriceHistory.observed_at, PriceHistory.price).order_by(
            PriceHistory.item_id, PriceHistory.observed_at
        )
    ).all():
        if item_id in seen:
            history[item_id].append((observed_at, float(price)))

    firsts: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for item_id, points in history.items():
        site_id, first_seen = seen[item_id]
        for (_before_at, before), (at, after) in pairwise(points):
            if after < before and before > 0 and at > first_seen:
                days = (at - first_seen).total_seconds() / 86400
                firsts[site_id].append((days, (before - after) / before * 100))
                break

    now_at = utcnow().replace(tzinfo=None)
    found: dict[int, Habit] = {}
    for site_id, cuts in firsts.items():
        if len(cuts) < MIN_DROPS:
            continue
        median_day = statistics.median(days for days, _pct in cuts)
        old_enough = sum(
            1
            for item_site, first_seen in seen.values()
            if item_site == site_id
            and first_seen is not None
            and (now_at - first_seen.replace(tzinfo=None)).days >= median_day
        )
        found[site_id] = Habit(
            drops=len(cuts),
            median_day=round(median_day, 1),
            median_pct=round(statistics.median(pct for _days, pct in cuts), 1),
            share=round(min(1.0, len(cuts) / old_enough), 3) if old_enough else 0.0,
        )
    _habit_cache = (now, found)
    return found


# ---------------------------------------------------------------------------
# Scorecards
# ---------------------------------------------------------------------------
class _OtherShops:
    """Each model's market median *without* one shop, worked out on demand.

    A shop compared with a market it is part of is partly compared with itself:
    Simpson holds half of all listings, and against medians that include its
    own guns it came out at exactly 1.0. So each shop's guns are set against
    the other shops' listings of the same model -- and only where those number
    at least MIN_MODEL_LISTINGS across at least MIN_MODEL_SHOPS shops.
    """

    def __init__(self, session: Session) -> None:
        self.prices: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        for model_id, price, site_id in session.execute(
            select(Item.firearm_model_id, Item.current_price, Item.site_id).where(
                _firearm(),
                Item.is_active.is_(True),
                Item.is_sold.is_(False),
                Item.firearm_model_id.is_not(None),
                Item.current_price.is_not(None),
                Item.current_price > 0,
            )
        ).all():
            if model_id is None or price is None:
                continue  # excluded by the query; this tells the type checker
            self.prices[model_id][site_id].append(float(price))
        self._cache: dict[tuple[int, int], float | None] = {}

    def median(self, model_id: int, site_id: int) -> float | None:
        key = (model_id, site_id)
        if key not in self._cache:
            others = {
                shop: found
                for shop, found in self.prices.get(model_id, {}).items()
                if shop != site_id
            }
            pooled = [price for found in others.values() for price in found]
            enough = len(pooled) >= MIN_MODEL_LISTINGS and len(others) >= MIN_MODEL_SHOPS
            self._cache[key] = statistics.median(pooled) if enough else None
        return self._cache[key]


def scorecards(session: Session) -> list[Scorecard]:
    """Every enabled shop's scorecard, the shops with most guns for sale first."""
    now = utcnow().replace(tzinfo=None)
    watching = {
        site_id: (since.replace(tzinfo=None) if since else None)
        for site_id, since in _watching_since(session).items()
    }
    cards = {
        site.id: Scorecard(site_id=site.id, name=site.name, slug=site.slug)
        for site in session.execute(select(Site).where(Site.enabled.is_(True))).scalars()
    }
    medians = _OtherShops(session)
    ratios: dict[int, list[float]] = defaultdict(list)
    durations: dict[int, list[float]] = defaultdict(list)
    arrivals: dict[int, Counter[int]] = defaultdict(Counter)

    for row in session.execute(
        select(
            Item.site_id,
            Item.firearm_model_id,
            Item.current_price,
            Item.is_active,
            Item.is_sold,
            Item.first_seen_at,
            Item.sold_at,
            Item.delisted_at,
        ).where(_firearm())
    ).all():
        card = cards.get(row.site_id)
        if card is not None:
            _count(card, row, now, watching, medians, ratios, durations, arrivals)

    cut_habits = habits(session)
    for site_id, card in cards.items():
        found = ratios.get(site_id, [])
        if len(found) >= MIN_COMPARED:
            card.price_vs_market = round(statistics.median(found), 3)
            card.compared = len(found)
        lasted = durations.get(site_id, [])
        if lasted:
            card.sell_days = round(statistics.median(lasted), 1)
            card.sold_measured = len(lasted)
        card.arrivals_by_weekday = [arrivals[site_id][day] for day in range(7)]
        card.habit = cut_habits.get(site_id)
    return sorted(cards.values(), key=lambda card: (-card.guns_for_sale, card.name))


def _count(
    card: Scorecard,
    row: Any,
    now: datetime,
    watching: dict[int, datetime | None],
    medians: _OtherShops,
    ratios: dict[int, list[float]],
    durations: dict[int, list[float]],
    arrivals: dict[int, Counter[int]],
) -> None:
    """Add one of a shop's firearm listings to its tallies."""
    seen = row.first_seen_at.replace(tzinfo=None) if row.first_seen_at else None
    since = watching.get(row.site_id)
    arrived_watching = since is not None and seen is not None and seen > since
    if row.is_active and not row.is_sold:
        card.guns_for_sale += 1
        market = medians.median(row.firearm_model_id, row.site_id) if row.firearm_model_id else None
        if market and row.current_price and row.current_price > 0:
            ratios[row.site_id].append(float(row.current_price) / market)
    if arrived_watching and seen is not None:
        age = (now - seen).days
        if age < 7:
            card.new_this_week += 1
        if age < ARRIVAL_DAYS:
            arrivals[row.site_id][seen.weekday()] += 1
    left = min(
        (moment.replace(tzinfo=None) for moment in (row.sold_at, row.delisted_at) if moment),
        default=None,
    )
    if left is None:
        return
    if (now - left).days < 30:
        card.left_last_30_days += 1
    if arrived_watching and seen is not None and left > seen:
        durations[row.site_id].append((left - seen).total_seconds() / 86400)


def listed_days(item: Item) -> int | None:
    """How many days this listing has been up, for "this one is on day N"."""
    if item.first_seen_at is None:
        return None
    first = item.first_seen_at.replace(tzinfo=None)
    return max(0, (utcnow().replace(tzinfo=None) - first).days)
