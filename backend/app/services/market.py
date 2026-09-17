"""What a kind of gun goes for, across every dealer at once.

The detail page already answers "is this a good deal?" for one listing, by
placing it among the others of the same model. This asks the same question one
level up -- what does a 7.5x55 Swiss rifle cost anywhere, what does a Walther
cost -- which is the question somebody has before they have a listing in front
of them.

**Four decisions, each of which the naive version gets wrong.**

*The median, not the mean.* "Goes for" means what a typical one costs. One
dealer listing two hundred parts kits at forty dollars drags a mean and leaves
a median where it was.

*Firearms only, by default.* A caliber's listings mix six-hundred-dollar
rifles with forty-dollar bayonets, magazines and parts kits, and averaging
across them describes nothing that exists. The browse filters make the same
distinction and for the same reason.

*The tenth and ninetieth percentiles, not the range.* A single mislabeled
$750,000 Gatling gun sets the maximum for .45-70 and says nothing about the
.45-70s anybody is going to buy. The percentiles describe the bulk, which is
what a spread is for.

*A minimum sample.* Below a handful of listings a median is an anecdote with a
decimal point. Groups under the threshold are counted and not shown.

**And every band says how concentrated it is**, which is the finding that came
out of building this. A `price_history` row is written only when a price
*changes* -- the right storage, since a row per scan would be eleven thousand
duplicates a day -- so a time series has to be reconstructed rather than read.
That is straightforward, and it is not the problem: there is not yet enough
history to reconstruct. The obvious substitute, comparing what is on the shelf
against what has left it, was tried and is not sound at this volume -- at most
three calibers have both a live and a sold sample worth the name, and their
gaps run from -39% to +33%, which is noise wearing a percent sign.

What the data *does* show, and what turned out to matter more, is that many
bands are one dealer. ".22 Caliber" is a single shop, 6.5x55mm Swedish is 98%
one shop and 7.5x55mm Swiss 93%. A median drawn from one shelf is that shop's
pricing and not the market's, and a page that did not say so would be inviting
exactly the wrong conclusion. So every band carries the number of shops behind
it and the share held by the largest.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item

#: What a group can be cut by. Each is a column on the listing, so a group is
#: exactly what the browse filter of the same name would return.
DIMENSIONS = ("caliber", "country", "manufacturer")

#: Fewer listings than this and the median is an anecdote. Groups below it are
#: counted in `thin` rather than shown, so the page can say how much it left
#: out instead of quietly showing less.
MIN_SAMPLE = 5

#: At or above this share from one shop, a band is that shop's pricing rather
#: than the market's, and is marked. Measured rather than picked: the bands
#: above it are the ones whose medians move when a single dealer restocks.
CONCENTRATED = 0.70


def _percentile(ordered: list[float], fraction: float) -> float:
    """Nearest-rank percentile of an already-sorted list.

    Nearest-rank rather than interpolated: these are asking prices, and a
    number halfway between two real prices is not one anybody is asking. The
    tenth percentile of a Swiss K31 ought to be a price somebody has actually
    written down.
    """
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


@dataclass
class Band:
    """One value of the chosen dimension, and what it costs."""

    value: str
    listings: int
    low: float
    median: float
    high: float
    currency: str = "USD"
    #: How many shops the band is drawn from, and the share held by the
    #: largest. A median from one shelf is that shop's pricing, not the
    #: market's.
    sites: int = 0
    top_site_share: float = 0.0

    @property
    def concentrated(self) -> bool:
        """Whether one dealer dominates this band enough to be its author."""
        return self.top_site_share >= CONCENTRATED


@dataclass
class Market:
    dimension: str
    firearms_only: bool
    min_sample: int
    #: Listings that went into the answer, after every filter.
    considered: int
    #: Groups dropped for being too small, and the listings in them.
    thin_groups: int
    thin_listings: int
    bands: list[Band] = field(default_factory=list)


def summarize(
    session: Session,
    dimension: str = "caliber",
    *,
    firearms_only: bool = True,
    min_sample: int = MIN_SAMPLE,
    limit: int = 60,
) -> Market:
    """The price bands for one dimension, commonest first.

    Percentiles are worked out in Python rather than in SQL. ``percentile_cont``
    is PostgreSQL-only and this schema has to answer on SQLite too -- see the
    two-engines rule -- and the whole catalog is ten thousand floats, which is
    not a quantity worth writing two queries for.
    """
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unknown dimension: {dimension}")
    column = getattr(Item, dimension)

    def constrain(stmt):
        stmt = stmt.where(column.is_not(None), column != "", Item.current_price.is_not(None))
        if firearms_only:
            stmt = stmt.where(Item.is_rifle.is_(True) | Item.is_pistol.is_(True))
        return stmt

    live: dict[str, list[float]] = {}
    currencies: dict[str, str] = {}
    by_site: dict[str, Counter[int]] = {}
    for value, price, currency, site_id in session.execute(
        constrain(
            select(column, Item.current_price, Item.currency, Item.site_id).where(
                Item.is_active.is_(True), Item.is_sold.is_(False)
            )
        )
    ).all():
        name = str(value)
        live.setdefault(name, []).append(float(price))
        currencies.setdefault(name, currency or "USD")
        by_site.setdefault(name, Counter())[site_id] += 1

    considered = sum(len(prices) for prices in live.values())
    thin = {value: prices for value, prices in live.items() if len(prices) < min_sample}

    bands = []
    for value, prices in live.items():
        if len(prices) < min_sample:
            continue
        prices.sort()
        shops = by_site.get(value, Counter())
        bands.append(
            Band(
                value=value,
                listings=len(prices),
                low=_percentile(prices, 0.10),
                median=_percentile(prices, 0.50),
                high=_percentile(prices, 0.90),
                currency=currencies.get(value, "USD"),
                sites=len(shops),
                top_site_share=(round(max(shops.values()) / len(prices), 3) if shops else 0.0),
            )
        )

    bands.sort(key=lambda band: -band.listings)
    return Market(
        dimension=dimension,
        firearms_only=firearms_only,
        min_sample=min_sample,
        considered=considered,
        thin_groups=len(thin),
        thin_listings=sum(len(prices) for prices in thin.values()),
        bands=bands[:limit],
    )
