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
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import FirearmModel, Item, ScanRun, ScanStatus

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


# ---------------------------------------------------------------------------
# How long a gun takes to sell
# ---------------------------------------------------------------------------
#: What the time-to-sell figures can be grouped by. A model is the finer
#: question -- "how fast do K31s go" -- and a caliber the one with more data.
TURNOVER_DIMENSIONS = ("model", "caliber")


@dataclass
class Turnover:
    """One value of the chosen dimension, and how long its listings lasted."""

    value: str
    sold: int
    #: Days on the shelf: the median, and the quarter that went fastest and
    #: slowest. Quartiles rather than the tenth and ninetieth percentiles the
    #: price bands use, because these samples are small and the tails of a
    #: small sample are one listing each.
    median_days: float
    fast_days: float
    slow_days: float
    sites: int = 0
    top_site_share: float = 0.0

    @property
    def concentrated(self) -> bool:
        return self.top_site_share >= CONCENTRATED


@dataclass
class TurnoverSummary:
    dimension: str
    min_sample: int
    #: Listings whose whole time on the shelf was watched, and went into this.
    measured: int
    #: Listings that left the shelf but were already there when we started
    #: watching their shop. Their duration is a floor, not a measurement, so
    #: they are counted here and kept out of every figure.
    floors: int
    thin_groups: int
    thin_listings: int
    rows: list[Turnover] = field(default_factory=list)


def _watching_since(session: Session) -> dict[int, datetime | None]:
    """When each site's first completed scan finished.

    A listing first seen *after* this arrived while we were watching, so its
    time on the shelf is a measurement. One seen by the first scan was already
    there, for however long, and its duration is only an "at least".
    """
    return dict(
        session.execute(
            select(ScanRun.site_id, func.min(ScanRun.finished_at))
            .where(ScanRun.status.in_([ScanStatus.SUCCESS, ScanStatus.PARTIAL]))
            .group_by(ScanRun.site_id)
        ).all()
    )


def time_to_sell(
    session: Session,
    dimension: str = "model",
    *,
    min_sample: int = MIN_SAMPLE,
    limit: int = 60,
) -> TurnoverSummary:
    """How long each kind of gun stays on the shelf, fastest first.

    **What counts as leaving the shelf** is whichever came first: the listing
    marked sold (``sold_at``) or the listing gone from its shop
    (``delisted_at``). Most shops that sell a gun simply take it down, and a
    figure built on ``sold_at`` alone would describe only the few that mark
    one sold and leave it up.

    **What is left out, and counted instead:** a listing already on the shelf
    when we first scanned its shop (its duration is a floor), one that was
    already sold the first time we saw it (we never saw it for sale), and
    anything that is not a firearm, for the reason the price bands give.

    Worked out in Python, as the price bands are, so both engines answer.
    """
    if dimension not in TURNOVER_DIMENSIONS:
        raise ValueError(f"Unknown dimension: {dimension}")
    watching = _watching_since(session)
    column = FirearmModel.name if dimension == "model" else Item.caliber
    statement = select(
        column, Item.site_id, Item.first_seen_at, Item.sold_at, Item.delisted_at
    ).where(
        Item.is_rifle.is_(True) | Item.is_pistol.is_(True),
        Item.sold_at.is_not(None) | Item.delisted_at.is_not(None),
        column.is_not(None),
        column != "",
    )
    if dimension == "model":
        statement = statement.join(FirearmModel, FirearmModel.id == Item.firearm_model_id)

    durations: dict[str, list[float]] = {}
    by_site: dict[str, Counter[int]] = {}
    floors = 0
    for value, site_id, first_seen, sold_at, delisted_at in session.execute(statement).all():
        left = min(moment for moment in (sold_at, delisted_at) if moment is not None)
        since = watching.get(site_id)
        if since is None or first_seen is None or first_seen <= since:
            floors += 1
            continue
        elapsed = (left - first_seen).total_seconds() / 86400
        if elapsed <= 0:
            # Already sold, or gone, the first time we saw it.
            continue
        name = str(value)
        durations.setdefault(name, []).append(elapsed)
        by_site.setdefault(name, Counter())[site_id] += 1

    thin = {value: days for value, days in durations.items() if len(days) < min_sample}
    rows = []
    for value, days in durations.items():
        if len(days) < min_sample:
            continue
        days.sort()
        shops = by_site.get(value, Counter())
        rows.append(
            Turnover(
                value=value,
                sold=len(days),
                median_days=round(_percentile(days, 0.50), 1),
                fast_days=round(_percentile(days, 0.25), 1),
                slow_days=round(_percentile(days, 0.75), 1),
                sites=len(shops),
                top_site_share=round(max(shops.values()) / len(days), 3) if shops else 0.0,
            )
        )
    rows.sort(key=lambda row: (row.median_days, -row.sold))
    return TurnoverSummary(
        dimension=dimension,
        min_sample=min_sample,
        measured=sum(len(days) for days in durations.values()),
        floors=floors,
        thin_groups=len(thin),
        thin_listings=sum(len(days) for days in thin.values()),
        rows=rows[:limit],
    )
