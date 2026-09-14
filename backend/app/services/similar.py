"""Other listings worth looking at beside the one on screen.

The price spectrum answers "is this a good deal?" and stops one step short: it
says *cheaper than 8% of them* and gives no way to reach the them. A reader
told their rifle is dear has to retype the model into the search box to find
out where the cheap one is. This is that step.

**Graded, not boolean.** "Similar" is a spectrum of its own, and a page that
mixed the same rifle at another vendor in with a different rifle in the same
cartridge -- unlabeled, in one list -- would be worse than useful. So every
result carries the rung it came in on, and the page prints it:

    the same gun, elsewhere      same model, same cartridge
    the same model               same model, a different cartridge
    the same cartridge, country  a different gun a buyer would weigh against it
    the same cartridge           the widest net still worth casting

The order is the value order. A K98k buyer wants the other K98ks first, then
the other 8mm Mauser German rifles -- a VZ-24, a Gewehr 98 -- and a German
pistol in 9mm is not an alternative to a rifle, which is why the country never
appears without the cartridge beside it.

**The cartridge is the spine.** It is the one field that is nearly always
stated, nearly always right, and that a buyer genuinely will not cross: somebody
shopping for 8mm Mauser is not in the market for 7.62x54R, whatever else the
two rifles have in common. Country and maker only ever narrow within it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import Item

#: How many to offer. Enough to be worth scrolling, few enough to be read --
#: and the detail page has a price spectrum above it already.
DEFAULT_LIMIT = 8

#: Slots held back from the closest band so a wider one can be seen.
#:
#: 3,978 of 8,690 active firearms -- 46% -- sit in a model-and-cartridge group
#: of nine or more, so without this the list is *entirely* the same gun on
#: nearly half the catalog. That is the most useful answer and it is not the
#: only one: a K98k buyer is well served by the other K98ks and also by knowing
#: a VZ-24 is on the shelf. Held back rather than fixed, because a listing
#: whose wider bands are empty should still get a full list.
RESERVED_FOR_WIDER = 2


@dataclass(frozen=True)
class Rung:
    """One band of similarity, and the words the page uses for it."""

    key: str
    label: str


SAME_GUN = Rung("same_gun", "The same model and cartridge")
SAME_MODEL = Rung("same_model", "The same model, another cartridge")
SAME_ROUND_AND_PLACE = Rung("same_round_and_place", "Same cartridge, same country")
SAME_ROUND = Rung("same_round", "Same cartridge")


@dataclass(frozen=True)
class Similar:
    """One listing worth looking at, and why."""

    item: Item
    rung: Rung


def _base(item: Item) -> Select:
    """Active listings that are not this one, newest price first later."""
    return (
        select(Item)
        .options(selectinload(Item.photos), selectinload(Item.site))
        .where(Item.id != item.id, Item.is_active.is_(True))
    )


def _rungs(item: Item) -> list[tuple[Rung, list]]:
    """Each band and the clauses that select it, closest first.

    **The bands exclude each other in SQL**, rather than being narrowed
    afterwards by dropping rows already picked. They are nested by nature --
    every "same gun" row is also a "same cartridge" row -- so a row the closest
    band's LIMIT cut off would turn up in the next one wearing the wrong label:
    twelve K98ks and a limit of ten produced two K98ks announced as "the same
    model, another cartridge". Written this way a band cannot mislabel anything
    it did not select.

    Built as a list so the order is readable at a glance: this is the whole of
    the feature's judgment.
    """
    model_id, cartridge, country = item.firearm_model_id, item.caliber, item.country
    bands: list[tuple[Rung, list]] = []

    if model_id:
        if cartridge:
            bands.append((SAME_GUN, [Item.firearm_model_id == model_id, Item.caliber == cartridge]))
            bands.append(
                (
                    SAME_MODEL,
                    [
                        Item.firearm_model_id == model_id,
                        or_(Item.caliber.is_(None), Item.caliber != cartridge),
                    ],
                )
            )
        else:
            bands.append((SAME_MODEL, [Item.firearm_model_id == model_id]))

    if cartridge:
        # A different gun, so a row already covered by the two bands above is
        # excluded here by its model rather than by having been seen.
        elsewhere = (
            [or_(Item.firearm_model_id.is_(None), Item.firearm_model_id != model_id)]
            if model_id
            else []
        )
        if country:
            bands.append(
                (
                    SAME_ROUND_AND_PLACE,
                    [Item.caliber == cartridge, Item.country == country, *elsewhere],
                )
            )
            bands.append(
                (
                    SAME_ROUND,
                    [
                        Item.caliber == cartridge,
                        or_(Item.country.is_(None), Item.country != country),
                        *elsewhere,
                    ],
                )
            )
        else:
            bands.append((SAME_ROUND, [Item.caliber == cartridge, *elsewhere]))
    return bands


def find(session: Session, item: Item, limit: int = DEFAULT_LIMIT) -> list[Similar]:
    """Listings like this one, closest band first, each labeled with its band.

    A listing appears once, on the closest rung that reaches it -- so the same
    rifle at another vendor is never repeated further down as "same cartridge".

    Returns [] for a listing with neither a model nor a cartridge, which is an
    honest answer: with nothing stated there is nothing to be similar to, and
    filling the space with whatever shares a vendor would be noise wearing the
    costume of a recommendation.
    """
    # Accessories are excluded wholesale rather than by band. A bayonet that
    # fits an 8mm Mauser rifle is not an alternative to the rifle, and the
    # cartridge on it is the rifle's -- see armory.fill_in.
    if not (item.is_rifle or item.is_pistol):
        return []

    seen: set[int] = {item.id}
    bands: list[list[Similar]] = []
    for rung, clauses in _rungs(item):
        rows = session.execute(
            _base(item)
            .where(*clauses, Item.is_rifle.is_(item.is_rifle))
            # Cheapest first within a band: the reason somebody follows one of
            # these is usually the price, and a listing with none sorts last
            # rather than first, which is what NULLS LAST is for.
            .order_by(Item.current_price.is_(None), Item.current_price.asc())
            .limit(limit + RESERVED_FOR_WIDER)
        ).scalars()
        band = []
        for row in rows:
            if row.id in seen:
                continue
            seen.add(row.id)
            band.append(Similar(item=row, rung=rung))
        bands.append(band)

    if not bands:
        return []

    # The closest band gives up its last couple of slots *only* if a wider one
    # can use them, so a gun nothing else resembles still gets a full list.
    wider = sum(len(band) for band in bands[1:])
    keep = limit if not wider else max(1, limit - min(RESERVED_FOR_WIDER, wider))

    found = bands[0][:keep]
    for band in bands[1:]:
        found.extend(band[: limit - len(found)])
        if len(found) >= limit:
            return found
    # Short because the wider bands had less than they promised: top up from
    # the closest one rather than return a half-empty list.
    if len(found) < limit:
        taken = {entry.item.id for entry in found}
        found.extend(entry for entry in bands[0] if entry.item.id not in taken)
    return found[:limit]
