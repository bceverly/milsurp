"""A listing's barrel and finish, and the variant of its model they point to.

Slice 2 of "New-gun prices, and the makers' own pages" (ROADMAP.md). A model
is a design and a variant a product within it (``ModelVariant``); a listing is
matched to its model as it always was, and then narrowed: by caliber, then by
the barrel length its title states, then by the finish. It is linked to a
variant only when that leaves exactly one -- "TAURUS TRACKER M44 PRE OWNED"
narrows to the .44s and no further, and the page shows those as a range,
where '4" STAINLESS' would narrow to one. A listing whose title names a barrel
or a finish no approved variant has matches none: an unknown version is not
the nearest known one.

The used-gun shops write both in fixed places -- Greentop's
'3" MATTE', '4.75" FDE', '1.875" BLUED'; We Buy Guns' "TWO TONE"; the police
shops' "4in Stainless" -- and finish is a short vocabulary, kept to the
handful of words a buyer chooses between.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..models import ArmoryStatus, Item, ModelVariant
from . import barrels, frames
from .carry import _FRACTIONS

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: The finishes a variant can be, and how titles write each. Order matters:
#: "two tone" before "black", "stainless" before the bare "ss", "hard chrome"
#: before "chrome".
FINISHES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Two-tone", re.compile(r"\b(?:two[\s-]?tone|2[\s-]?tone|duo|bi[\s-]?tone)\b", re.I)),
    ("FDE", re.compile(r"\b(?:fde|flat\s+dark\s+earth|dark\s+earth|coyote)\b", re.I)),
    ("OD Green", re.compile(r"\b(?:od\s*green|odg|olive\s+drab)\b", re.I)),
    ("Hard Chrome", re.compile(r"\bhard\s+chrome\b", re.I)),
    ("Stainless", re.compile(r"\b(?:stainless|sts|ss|satin\s+silver)\b", re.I)),
    ("Nickel", re.compile(r"\b(?:nickel|nkl)\b", re.I)),
    ("Chrome", re.compile(r"\bchrome\b", re.I)),
    ("Blued", re.compile(r"\b(?:blued?|bluing|blu)\b", re.I)),
    ("Parkerized", re.compile(r"\bparkeri[sz]ed\b", re.I)),
    ("Cerakote", re.compile(r"\bcerakote\b", re.I)),
    ("Black", re.compile(r"\b(?:black|blk|matte|nitron|tenifer|nitride|melonite)\b", re.I)),
    ("Gray", re.compile(r"\b(?:gr[ae]y|tungsten|sniper\s+gr[ae]y)\b", re.I)),
)
FINISH_NAMES = tuple(name for name, _pattern in FINISHES)

#: A barrel length, in inches: the carry rule's pattern (carry._BARREL) with
#: room for a long gun's two digits -- '18.5"', '20 inch', '16-inch'.
_BARREL = re.compile(
    r"(?<![\d.])(\d{1,2}(?:\.\d+)?)(?:\s*(?:-|\s)?\s*(\d)/(\d)|\s*([¼½¾]))?\s*"
    r"(?:\"|”|″|''|-?\s*inch(?:es)?\b|\s*in\.?(?=\s|$|,)|\s*bbl\b)",
    re.I,
)

#: How close two barrel lengths must be to be the same barrel: 3.1" and 3.12"
#: are one P365, 3" and 4" are two Trackers.
BARREL_TOLERANCE = 0.15


def read_finish(title: str | None) -> str | None:
    """The finish a title states, in the vocabulary of :data:`FINISHES`."""
    for name, pattern in FINISHES:
        if pattern.search(title or ""):
            return name
    return None


def normalize_finish(text: str | None) -> str | None:
    """A typed or scraped finish in the vocabulary: "matte black" -> "Black"."""
    if not text:
        return None
    if text in FINISH_NAMES:
        return text
    return read_finish(text)


def read_barrel(title: str | None, *, long_gun: bool = False) -> float | None:
    """The barrel length a title states, in inches.

    At a handgun's lengths or a long gun's. The shortest stated: a title that
    gives a barrel and an overall length gives the barrel first and shorter.
    """
    low, high = (10.0, 34.0) if long_gun else (1.0, 8.5)
    lengths = []
    for found in _BARREL.finditer(title or ""):
        whole, num, den, glyph = found.group(1), found.group(2), found.group(3), found.group(4)
        length = float(whole)
        if num and den and float(den):
            length += float(num) / float(den)
        if glyph:
            length += _FRACTIONS[glyph]
        if low <= length <= high:
            lengths.append(length)
    return min(lengths) if lengths else None


def candidates(session: Session, item: Item) -> list[ModelVariant]:
    """The approved variants of the listing's model that it could be.

    Narrowed by caliber, barrel and finish in turn, each only where the
    listing states it. A stated value that no variant has leaves nothing.
    """
    if item.firearm_model_id is None:
        return []
    found = list(
        session.execute(
            select(ModelVariant).where(
                ModelVariant.model_id == item.firearm_model_id,
                ModelVariant.status == ArmoryStatus.APPROVED,
                ModelVariant.enabled.is_(True),
            )
        ).scalars()
    )
    if item.caliber:
        wanted = item.caliber.strip().lower()
        found = [
            v
            for v in found
            if v.caliber is None or wanted in (s.lower() for s in v.caliber.spellings)
        ]
    if item.barrel_inches is not None:
        found = [
            v
            for v in found
            if v.barrel_inches is None
            or abs(v.barrel_inches - item.barrel_inches) <= BARREL_TOLERANCE
        ]
    if item.finish:
        found = [v for v in found if v.finish is None or v.finish == item.finish]
    # The frame size only where it settles something (asked for on
    # 2026-10-14): both sides know it and a version has the listing's. A size
    # no version has narrows nothing rather than everything -- the variants
    # may simply not have been given theirs.
    frame = getattr(item, "frame_size", None)
    if frame and any(v.frame_size == frame for v in found):
        found = [v for v in found if v.frame_size is None or v.frame_size == frame]
    return found


def settle(session: Session, item: Item) -> None:
    """Read the listing's barrel, frame and finish and link it to its variant.

    The barrel for every gun (app.services.barrels, 2026-10-13) and the frame
    size for every handgun (app.services.frames, 2026-10-14), both read from
    the description too; the finish and the variant only for a firearm whose
    model is in modern production, the only ones with variants.
    """
    barrels.apply(item)
    frames.apply(item)
    model = item.firearm_model
    if model is None or not model.modern_production or not (item.is_rifle or item.is_pistol):
        item.variant_id = None
        return
    item.finish = read_finish(item.title)
    found = candidates(session, item)
    item.variant_id = found[0].id if len(found) == 1 else None
