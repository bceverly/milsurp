"""Suppressors: a Type of their own.

Asked for on 2026-10-25 ("what would be some good sites to add for the
purchase of suppressors and the addition of them to the application?") with the
shops that sell them. Until then a suppressor was an accessory by design --
"Edged weapons and suppressors stop being rifles" in ROADMAP.md -- and fell
into "Other parts & accessories" with the slings and the scope rings. This
takes the suppressors themselves out of that bucket and leaves everything
that goes on one (a mount, a front cap, a cover) where it was.

**How a listing qualifies**: not a gun -- a rifle sold with a can on it, or
integrally suppressed, is a rifle -- nor a parts kit or a bayonet; and either
its title names a suppressor or silencer as the thing sold, or the shop filed
it in a suppressor section and the title does not name a part. A distributor's
title often names only the model ("SilencerCo Omega 36M", "Dead Air Sandman-S
Stainless"), so the section carries those.

**Not** an accessory for one: mounts, adapters, muzzle devices sold to take a
can, front caps, end caps, pistons, boosters, spacers, covers and wraps,
cleaning gear, "suppressor-ready" anything and "suppressor height" sights.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..models import Item

#: The thing itself named in a title.
_NAMED = re.compile(r"\b(?:suppressors?|silencers?|moderators?)\b", re.I)
#: A shop's section of them: "Suppressors", "Silencers", "Rifle Suppressors",
#: "NFA / Suppressors".
_SECTION = re.compile(r"\b(?:suppressors?|silencers?)\b", re.I)
#: What goes on one -- a part, when it is what the title is about.
_PART_WORD = re.compile(
    r"\b(?:mounts?|adapters?|adaptors?|caps?|pistons?|boosters?|spacers?|covers?|wraps?|"
    r"sleeves?|shrouds?|pouch(?:es)?|bags?|cases?|wipes?|cleaning|cleaner|solvent|parts?|"
    r"tools?|wrench(?:es)?|brakes?|flash\s*hiders?|compensators?|muzzle\s+devices?|"
    r"thread\s+protectors?|rings?|shims?|mono[\s-]?cores?|baffles?|tubes?|"
    r"blast\s+chambers?|sights?|optics?|barrels?|handguards?|rails?)\b",
    re.I,
)
#: A section the shop keeps for registered cans only.
_NFA_SECTION = re.compile(r"\bnfa\b.*\b(?:suppressors?|silencers?)\b", re.I)
#: A gun readied for one, or something sold for one: never the can itself.
_FOR_ONE = re.compile(
    r"\b(?:suppressor|silencer)[\s-]+(?:ready|height|host|compatible|sights?)\b"
    r"|\bfor\s+(?:a\s+|your\s+|the\s+)?(?:suppressors?|silencers?)\b",
    re.I,
)
#: What a can is sold *with*: "Suppressor w/ Key-Micro Mount", "Suppressor
#: with Muzzle Brake" (AIM Surplus, 2026-10-25) -- the can, and a part in the
#: box. Everything from here on is set aside before the title is read.
_SOLD_WITH = re.compile(r"\s(?:w/|with|incl\.?|including|\+)\s.*$|\s-\s.*\bincluded\b.*$", re.I)


def names_a_part(title: str) -> bool:
    """Whether the title names a part for a suppressor, or a gun readied for
    one, rather than a suppressor.

    Read by which noun is the head. A part word *before* "suppressor"
    describes the can ("Griffin EXPLORR .30Cal Taper Mount Silencer"); one
    right *after* it is the thing sold ("Suppressor Cover"); with no
    suppressor named at all, a part word is the thing sold ("Dead Air Key
    Mount") -- unless the shop's section says these are NFA items. The
    suppressor shops' sections sell mounts, caps and covers beside the cans,
    and those are left out at the shop, as other shops' accessories are.
    """
    title = _SOLD_WITH.sub("", title or "")
    if _FOR_ONE.search(title):
        return True
    nouns = list(_NAMED.finditer(title))
    if not nouns:
        return bool(_PART_WORD.search(title))
    # A suppressor is named: only a part word right after it is the thing
    # sold ("Suppressor Cover", "Silencer Mount"). One further on is what the
    # can comes with -- "Nomad LTi 7.62mm Silencer Xeno Adapter", "Inconel
    # Suppressor 5.56 K Hard Case" (KY Gun Co, 2026-10-25).
    after = title[nouns[-1].end() :]
    return bool(re.match(r"\s*[-:]?\s*" + _PART_WORD.pattern, after, re.I))


def is_suppressor(
    title: str,
    *,
    category: str | None = None,
    is_firearm: bool = False,
    is_parts_kit: bool = False,
    is_bayonet: bool = False,
) -> bool:
    """Whether a listing is a suppressor. See the module docstring."""
    if is_firearm or is_parts_kit or is_bayonet:
        return False
    title = title or ""
    # The shop's own word that this is a registered NFA item settles it: a
    # mount or a cap is not one. KY Gun Co files these as "Silencer", AIM
    # Surplus under NFA Items, Silencer Central in its Silencers tree, and
    # their scrapers say so in the section ("NFA Suppressors").
    if _NFA_SECTION.search(category or ""):
        return True
    if names_a_part(title):
        return False
    if _NAMED.search(title):
        return True
    return bool(_SECTION.search(category or ""))


def decide(session: Session, item: Item) -> bool:  # noqa: ARG001 - the Types' signature
    """The answer for a stored listing, from the fields already settled. The
    scan and ``reclassify`` both call this last, as they do blackpowder.decide."""
    return is_suppressor(
        item.title,
        category=item.category,
        is_firearm=bool(item.is_rifle or item.is_pistol),
        is_parts_kit=bool(item.is_parts_kit),
        is_bayonet=bool(item.is_bayonet),
    )
