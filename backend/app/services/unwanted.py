"""Guns this catalog does not carry, by the owner's choice.

Not a judgment the classifier makes -- these are firearms, correctly read --
but a decision about what the catalog is for. Asked for on 2026-10-25:
"please remove heritage rough rider revolvers and any hi-point pistol from the
database and prevent them from coming in on future scans." A scan files every
listing as usual, then drops one this module names before it is saved for
good (``scan_service.run_scan``), and ``cli.py items purge-unwanted`` removes
any already stored.

Each rule reads the settled listing -- maker, kind, title, the armory's model --
so it decides on the same facts the browse page shows, not on a guess from
the title alone.

**Heritage Rough Rider.** Distributor titles rarely spell it out: "HER
RR22NI4BW", "HER RGH RDR 22LR", "HTG ROUGH RIDER RANCHER" (whose maker was
read as Colt), "Heritage Arms .22 LR Revolver - 6.5 inch Barrel". So a listing is
one when it is Heritage's -- by maker, or a title that opens with Heritage,
HTG or HER (not "Colt Aztec Mexican Heritage 1911") -- and either names the
Rough Rider in one of its forms or is a Heritage .22 or .17 that names none
of Heritage's other lines (the Roscoe, Ranch Hand, Settler and 92) -- every
other Heritage rimfire is a Rough Rider.
On production on 2026-10-25: 154 with "Rough Rider" in the title and about 60
more under a code.

**Hi-Point pistols.** Hi-Point's by maker or by title (one CF380 had its maker
read as Ruger), and a pistol by its kind or its armory model's -- a "JHP GEN2
45ACP" was filed as a rifle, and is caught by its model code. Hi-Point's
carbines (995TS, 4095, 1095, 3895) stay: the request was for the pistols. A
995 sold with a brace is sold as a pistol, and goes with them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from ..models import Item

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_HERITAGE_MAKER = re.compile(r"^\s*heritage\b", re.I)
_HERITAGE_TITLE = re.compile(r"^\s*(?:used\s+|new\s+)?(?:heritage|htg|her)\b", re.I)
#: "Heritage" anywhere with "Rough Rider" beside it is unambiguous.
_HERITAGE_ROUGH_RIDER = re.compile(r"\bheritage\b.*\brough\s*riders?\b", re.I)
_ROUGH_RIDER = re.compile(
    r"\brough\s*riders?\b|\brgh\s*rdr\b|\brr(?:\s|\d|$|\b)|\btac(?:tical)?\s+cowboy\b|"
    r"\brancher\b|\bbarkeep\b",
    re.I,
)
#: Heritage's lines that are not the Rough Rider.
_OTHER_HERITAGE = re.compile(
    r"\broscoe\b|\branch\s*hand\b|\bsettler\b|\bmares?\s*leg\b|\b92\b|\bsml\d", re.I
)
_RIMFIRE = re.compile(r"(?<![\d.])\.?(?:22|17)\s*(?:lr|wmr|mag|m\b|hmr|cal|long)|\.22\b", re.I)

_HI_POINT = re.compile(r"\bhi[\s-]?point\b|\bhipoint\b", re.I)
#: Hi-Point's pistols by model, for a title that names only the model: "JHP
#: GEN2 45ACP M81 CAMO", filed as a rifle, with Hi-Point only as its maker.
_HI_POINT_PISTOL_MODEL = re.compile(r"\b(?:c9|cf380|jhp|jcp|jxp\s?10|yc9|yc380|\d{3,4}p)\b", re.I)
_CARBINE = re.compile(r"\bcarbine\b", re.I)


def is_heritage_rough_rider(title: str, manufacturer: str | None) -> bool:
    """Whether a listing is a Heritage Rough Rider revolver."""
    title = title or ""
    if _HERITAGE_ROUGH_RIDER.search(title):
        return True
    if not (_HERITAGE_MAKER.search(manufacturer or "") or _HERITAGE_TITLE.search(title)):
        return False
    if _ROUGH_RIDER.search(title):
        return True
    # Every Heritage rimfire outside those other lines is a Rough Rider:
    # "HERITAGE 22LR 6.5\" FS NICKEL COCOBOLO GRIPS" says neither word.
    return not _OTHER_HERITAGE.search(title) and bool(_RIMFIRE.search(title))


def is_hi_point_pistol(
    title: str, manufacturer: str | None, *, is_pistol: bool, model_kind: str | None
) -> bool:
    """Whether a listing is a Hi-Point pistol."""
    title = title or ""
    if not (_HI_POINT.search(manufacturer or "") or _HI_POINT.search(title)):
        return False
    # The carbines stay -- but a 995 sold with a brace is sold as a pistol
    # ("Hi-Point 995 9mm Pistol with M81 Brace"), and goes with the pistols.
    if _CARBINE.search(title) and not is_pistol:
        return False
    return (
        is_pistol
        or (model_kind or "").upper() == "PISTOL"
        or bool(_HI_POINT_PISTOL_MODEL.search(title))
    )


def reason(item: Item) -> str | None:
    """Why the catalog does not carry this listing, or None if it does."""
    if is_heritage_rough_rider(item.title, item.manufacturer):
        return "Heritage Rough Rider"
    model = getattr(item, "firearm_model", None)
    kind = getattr(getattr(model, "kind", None), "value", getattr(model, "kind", None))
    if is_hi_point_pistol(
        item.title, item.manufacturer, is_pistol=bool(item.is_pistol), model_kind=kind
    ):
        return "Hi-Point pistol"
    return None


#: What a listing must contain somewhere for either rule to be worth asking --
#: the narrowing that keeps a pass over the whole catalog from loading it all.
_CANDIDATE_WORDS = ("heritage", "htg", "her ", "hi-point", "hi point", "hipoint")


def stored(session: Session) -> list[tuple[int, str]]:
    """Every listing already stored that the catalog does not carry, with why."""
    text = [
        column.ilike(f"%{word}%")
        for word in _CANDIDATE_WORDS
        for column in (Item.title, Item.manufacturer)
    ]
    rows = (
        session.execute(select(Item).options(selectinload(Item.firearm_model)).where(or_(*text)))
        .scalars()
        .all()
    )
    found = []
    for item in rows:
        why = reason(item)
        if why:
            found.append((item.id, why))
    return found
