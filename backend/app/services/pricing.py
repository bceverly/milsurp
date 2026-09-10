"""Where one listing sits among the others of the same gun.

The question this catalog exists to answer is "is this a good deal?", and until
now nothing in it did. The armory makes the answer possible: a listing matched
to a model, carrying a maker and a cartridge, has *peers* -- 123 such groups
cover 1,220 active listings, the largest being 169 Karabiner 98ks across eight
vendors.

**The hard part is not finding the peers, it is drawing them.** Surplus prices
are violently skewed, and not in one shape:

    Walther PP    n=95   min $280  Q1 $375    median $600    Q3 $2,245  max $11,995
    Karabiner 98k n=169  min $125  Q1 $750    median $850    Q3 $950    max $6,995
    M1 Garand     n=48   min $6    Q1 $74     median $1,800  Q3 $3,070  max $6,000

An axis drawn in *dollars* from the cheapest to the dearest puts nine listings
in ten inside the leftmost tenth of the bar: one collector-grade rifle decides
the whole scale. Clipping it to the 5th and 95th percentiles was tried and does
not rescue it either -- the Walther PP's 95th is $4,788 against a median of
$600, so a $350 pistol still lands at one percent of the way along.

**So the axis is the rank, not the price.** A listing sits where its own
position in the sorted list puts it, the graduations carry the dollar values at
the quarter, the half and the three-quarter marks, and the ends are labeled
with the true cheapest and dearest. Every distribution above draws legibly that
way, the median is always the middle of the bar -- which is a reading somebody
can learn once -- and "cheaper than 8% of them" is exactly the sentence the
picture is making. The spacing is by rank and the page says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FirearmModel, Item

#: Below this there is no spectrum to sit in -- two listings are a pair, not a
#: distribution, and a marker halfway between them says nothing. Three is the
#: smallest number for which "cheaper than most" is a sentence worth printing.
MIN_PEERS = 3


def percentile(ordered: list[float], point: float) -> float:
    """The value at *point* percent through an ascending list.

    Linear interpolation between neighbors, which is the ordinary definition
    and which degrades gracefully: with three values the 5th percentile is
    within a hair of the smallest, so the same formula draws a sensible axis
    for a group of three and for a group of a hundred and sixty-nine.
    """
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (point / 100.0)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass
class PricePosition:
    """One listing's place among the others of the same gun."""

    count: int
    vendors: int
    #: The ends of the bar: the cheapest and dearest peer, outliers included.
    low: float
    high: float
    #: The graduations, at the quarter, half and three-quarter marks. The bar
    #: is scaled by rank, so these sit at 25%, 50% and 75% along it whatever
    #: the prices are -- see the module docstring.
    q1: float
    median: float
    q3: float
    #: This listing.
    price: float
    #: How many peers this listing *undercuts*, as a percentage -- the ones
    #: dearer than it. Named for what it says, because the first version was
    #: named "percentile", held the fraction *below* this price, and was then
    #: printed as "cheaper than N% of them": a $350 pistol with 2 peers below
    #: it and 24 above read "cheaper than 7%" when it undercut 83% of them.
    #:
    #: A statistic, and not where the marker goes. The dearest of five is
    #: dearer than four of them and a marker at 80% of a bar whose right end
    #: carries its own price is simply wrong -- that is :attr:`position`.
    cheaper_than: int
    #: Where the marker goes, 0 to 100. The rank mapped across the whole bar,
    #: so the cheapest sits hard left and the dearest hard right -- which is
    #: what a bar labeled with the cheapest and dearest prices promises. It is
    #: the same mapping the graduations use, so the tick at 25% really does
    #: mark the value :func:`percentile` returns for 25.
    position: float
    #: What made these listings peers, for the caption to say out loud.
    model: str | None = None
    manufacturer: str | None = None
    caliber: str | None = None
    prices: list[float] = field(default_factory=list)


def maker_distinguishes(model: FirearmModel | None) -> bool:
    """Whether two listings of this model can be different guns by their maker.

    **The armory already knows.** A model row names every firm known to have
    built it, and the same rule the rest of the catalog runs on applies here:
    with exactly one there is nothing to distinguish, with several there is.

    * ``M1 Carbine`` names nine firms, and an Inland is not a Winchester --
      those are different guns and belong in different groups.
    * ``Karabiner 98k`` names one, so the maker is settled by the model; asking
      the listings to agree about it adds nothing.
    * ``M57`` names none, so the maker on a listing is a *derivation* rather
      than a fact, and demanding agreement compares derivations instead of guns.

    That last case is what this function exists for. Seven Yugoslav M57
    Tokarevs, all in 7.62x25mm, split into groups of two and three because
    three vendors' titles read as Zastava (who built them) and two as Tokarev
    (who designed the pattern) -- so the page showed nothing at all for a gun
    six vendors were selling.
    """
    return model is not None and len(model.manufacturers) > 1


def peers(session: Session, item: Item) -> list[Item]:
    """Active, priced listings of the same gun.

    The model and the cartridge always. The maker only where it tells two guns
    apart -- see :func:`maker_distinguishes`. The cartridge always, because a
    model built in two of them is two guns to a buyer: an 8x50mmR Steyr M95 is
    not an 8x56mmR one.

    The item itself is one of its own peers. It is one of the listings on the
    shelf, and taking it out would move the median by its own absence.
    """
    if not (item.firearm_model_id and item.caliber and item.current_price):
        return []
    clauses = [
        Item.firearm_model_id == item.firearm_model_id,
        Item.caliber == item.caliber,
        Item.is_active.is_(True),
        Item.current_price.is_not(None),
    ]
    if maker_distinguishes(item.firearm_model):
        # Only now does a listing with no maker fall out of its own group: it
        # cannot be told apart from the others, and guessing costs more than
        # leaving it alone.
        if not item.manufacturer:
            return []
        clauses.append(Item.manufacturer == item.manufacturer)
    return list(session.execute(select(Item).where(*clauses)).scalars().all())


def position(session: Session, item: Item) -> PricePosition | None:
    """Where this listing sits among its peers, or None when it has too few."""
    found = peers(session, item)
    if len(found) < MIN_PEERS:
        return None

    prices = sorted(float(other.current_price) for other in found if other.current_price)
    price = float(item.current_price or 0)
    # Both strict, so a shelf of identical prices reports 0% either way rather
    # than every one of them claiming to undercut the others.
    cheaper = sum(1 for other in prices if other < price)
    dearer = sum(1 for other in prices if other > price)
    # Where it sits on the bar. Ties share the middle of their own block, so
    # three listings at one price all get the same marker rather than being
    # spread across the run they occupy by an accident of sort order.
    matching = sum(1 for other in prices if other == price)
    rank = cheaper + (matching - 1) / 2
    spread = len(prices) - 1
    return PricePosition(
        count=len(prices),
        vendors=len({other.site_id for other in found}),
        low=prices[0],
        high=prices[-1],
        q1=percentile(prices, 25.0),
        median=percentile(prices, 50.0),
        q3=percentile(prices, 75.0),
        price=price,
        cheaper_than=round(100 * dearer / len(prices)),
        position=round(100 * rank / spread, 1) if spread else 50.0,
        model=item.firearm_model.name if item.firearm_model else None,
        manufacturer=item.manufacturer,
        caliber=item.caliber,
        prices=prices,
    )
