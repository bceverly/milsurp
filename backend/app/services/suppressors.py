"""Suppressors: a Type of their own.

Asked for on 2026-10-25 ("what would be some good sites to add for the
purchase of suppressors and the addition of them to the application?") with the
shops that sell them. Until then a suppressor was an accessory by design --
"Edged weapons and suppressors stop being rifles" in ROADMAP.md -- and fell
into "Other parts & accessories" with the slings and the scope rings. This
takes the suppressors themselves out of that bucket and leaves everything
that goes on one (a mount, a front cap, a cover) where it was.

**How a listing qualifies**: not a gun by its own title -- a rifle sold with a
can on it, or integrally suppressed, is a rifle -- nor a parts kit or a
bayonet; and either its title names a suppressor or silencer as the thing
sold, or the shop filed it in a suppressor section and the title does not name
a part. It overrules the classifier's guess that a can is a rifle. A distributor's
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


#: A gun named in a title: the noun, not as a word describing a can ("Rifle
#: Suppressor", "Shotgun Silencer"), and not inside what the can comes with.
#: Not "firearms", which is in makers' names: "Diamondback Firearms DBS-30i",
#: "Faxon Firearms Twenty-Toucan".
_GUN_NOUN = re.compile(
    r"\b(?:rifles?|carbines?|pistols?|handguns?|revolvers?|shotguns?|sbrs?|sbs|uppers?)\b"
    r"(?!\s*[-:]?\s*(?:suppressors?|silencers?|cans?|mounts?|adapters?))",
    re.I,
)
#: A magazine count is a gun's: no can has rounds ("16in 30rd w/ ZEROED 556K
#: Suppressor" is a CMMG rifle, KY Gun Co, 2026-10-25).
_ROUNDS = re.compile(r"\b\d+\s*(?:rd|rds|rnd|rnds|rounds?)\b|\b\d+\+1\b", re.I)


def names_a_gun(title: str) -> bool:
    """Whether the title, before anything it is sold *with*, names a gun:
    "B&T Station Six-9 Suppressed Pistol", "GHM9 SD2 Pistol, 9mm, Kit",
    "Ruger 10/22 Integrally Suppressed Rifle"."""
    title = _SOLD_WITH.sub("", title or "")
    return bool(_GUN_NOUN.search(title) or _ROUNDS.search(title))


def is_suppressor(
    title: str,
    *,
    category: str | None = None,
    is_parts_kit: bool = False,
    is_bayonet: bool = False,
) -> bool:
    """Whether a listing is a suppressor. See the module docstring.

    **It overrules the classifier's rifle-or-handgun reading**, which a can's
    title often provokes -- "Rifle Suppressor", ".30 Cal", "Flow 762", or a
    model name and nothing else -- so only the title itself naming a gun
    (:func:`names_a_gun`) keeps a listing out. On production's first scans of
    the suppressor shops on 2026-10-26, 96 of Silencer Central's 326 cans and
    87 of Capitol Armory's first 109 had been read as rifles.
    """
    if is_parts_kit or is_bayonet:
        return False
    title = title or ""
    if names_a_gun(title):
        return False
    # The shop's own word that this is a registered NFA item settles it: a
    # mount or a cap is not one. KY Gun Co files these as "Silencer", AIM
    # Surplus under NFA Items, Silencer Central in its Silencers tree, Primary
    # Arms by its own flag, and their scrapers say so in the section ("NFA
    # Suppressors").
    if _NFA_SECTION.search(category or ""):
        return True
    if names_a_part(title):
        return False
    if _NAMED.search(_SOLD_WITH.sub("", title)):
        return True
    return bool(_SECTION.search(category or ""))


#: What a gun has and a can does not, cleared when a listing turns out to be
#: one: the armory's model and variant, the finer kind, and the readings the
#: barrel, frame and capacity rules took from a can's length and caliber.
_GUN_FIELDS = (
    ("is_rifle", False),
    ("is_pistol", False),
    ("is_police_surplus", False),
    ("kind", None),
    ("firearm_model_id", None),
    ("variant_id", None),
    ("barrel_inches", None),
    ("barrel_threaded", None),
    ("frame_size", None),
    ("capacity", None),
)


def settle(item: Item) -> bool:
    """Decide a stored listing, and make a suppressor stop being a gun.

    Called before the gun Types (carry, black powder) by the scan and by
    ``reclassify``, so they see a can as what it is. Returns the answer.
    """
    can = is_suppressor(
        item.title,
        category=item.category,
        is_parts_kit=bool(item.is_parts_kit),
        is_bayonet=bool(item.is_bayonet),
    )
    if can:
        for name, value in _GUN_FIELDS:
            if getattr(item, name, value) != value:
                setattr(item, name, value)
    return can


def decide(session: Session, item: Item) -> bool:  # noqa: ARG001 - the Types' signature
    """The answer for a stored listing, without changing it."""
    return is_suppressor(
        item.title,
        category=item.category,
        is_parts_kit=bool(item.is_parts_kit),
        is_bayonet=bool(item.is_bayonet),
    )


#: Words that say nothing about which can it is: the noun, the finish, the
#: maker's corporate tail, and what a can is sold with or rated for.
_KEY_NOISE = re.compile(
    r"\b(?:suppressors?|silencers?|moderators?|armament|arms|industries|defense|usa|inc|llc|co|"
    r"black|blk|fde|flat\s+dark\s+earth|od\s+green|odg|green|tan|gray|grey|graphite|bronze|"
    r"cerakote|raw|patina|nitride|gold|silver|tungsten|camo|"
    r"direct\s+thread|thread(?:ed)?|dt|qd|hub|taper|mount|cal(?:iber)?|multi|"
    r"rifle|pistol|rimfire|shotgun|new|used)\b",
    re.I,
)
#: A thread pitch, a length, a caliber: "1/2x28", "5/8-24", "1.375x24", '7.6"',
#: "9mm", ".30", "5.56", "7.62x39", "300blk".
_KEY_MEASURE = re.compile(
    r"\d+/\d+\s*[-x]\s*\d+|\d+\.\d+\s*x\s*\d+|\d+(?:\.\d+)?\s*(?:\"|in\b|inch(?:es)?\b|″)"
    r"|\b\d+(?:\.\d+)?\s*mm\b|(?<![\w])\.\d{2,3}\b|\b\d\.\d{2}\b|\b\d+(?:\.\d+)?x\d+\b"
    r"|\b\d{3}\s*(?:blk|blackout|win|wm|rem|nato|acp|auto)\b",
    re.I,
)


#: The can makers, by the spellings their titles use, for a listing whose own
#: maker was not read: the key needs to know whose can it is.
_CAN_MAKERS = (
    ("silencerco", r"silencer\s*co"),
    ("deadair", r"dead\s*air"),
    ("griffin", r"griffin(?:\s+armament)?"),
    ("rugged", r"rugged(?:\s+suppressors)?"),
    ("surefire", r"sure\s*fire"),
    ("huxwrx", r"huxwrx|hux\s*wrx"),
    ("thunderbeast", r"thunder\s*beast|tbac"),
    ("banish", r"banish"),
    ("cgs", r"cgs(?:\s+suppressors)?|cgs\s+group"),
    ("aac", r"aac|advanced\s+armament"),
    ("otter", r"otter\s+creek(?:\s+labs)?|ocl"),
    ("sig", r"sig\s*sauer|sig"),
    ("bt", r"b\s*&\s*t|brugger\s*(?:&|and)?\s*thomet"),
    ("q", r"q\s*llc|q"),
    ("yhm", r"yhm|yankee\s+hill(?:\s+machine)?"),
    ("gemtech", r"gemtech"),
    ("sonicore", r"sonicore"),
    ("kgm", r"kgm"),
    ("jk", r"jk\s+armament"),
    ("maxim", r"maxim\s+defense"),
    ("pws", r"primary\s+weapons(?:\s+systems)?|pws"),
    ("diligent", r"diligent\s+defense(?:\s+co)?"),
    ("knights", r"knight'?s(?:\s+armament)?"),
    ("danieldefense", r"daniel\s+defense"),
    ("faxon", r"faxon(?:\s+firearms)?"),
    ("diamondback", r"diamondback(?:\s+firearms)?"),
    ("abel", r"abel"),
    ("hausken", r"hausken"),
    ("ase", r"ase\s+utra"),
    ("nosler", r"nosler"),
    ("barrett", r"barrett"),
    ("magco", r"magco"),
    ("anechoic", r"anechoic"),
    ("tacsol", r"tactical\s+solutions"),
    ("bowers", r"bowers(?:\s+group)?"),
    ("liberty", r"liberty(?:\s+suppressors)?"),
    ("ambient", r"ambient\s+arms"),
    ("allen", r"allen\s+engineering"),
    ("angledspade", r"angled\s+spade"),
    ("eotech", r"eotech"),
    ("hk", r"heckler\s*(?:&|and)\s*koch|h&k|hk"),
)
_CAN_MAKER = re.compile(
    r"^\W*(?:" + "|".join(f"(?P<{slug}>{pattern})" for slug, pattern in _CAN_MAKERS) + r")\b",
    re.I,
)


def _maker_of(title: str, manufacturer: str | None) -> tuple[str | None, str]:
    """Whose can, as a short slug, and the title with the maker's name off."""
    found = _CAN_MAKER.match(title)
    if found:
        return found.lastgroup, title[found.end() :]
    if manufacturer:
        slug = re.sub(r"[^a-z0-9]", "", manufacturer.lower())
        for word in re.findall(r"[a-z0-9]+", manufacturer.lower()):
            title = re.sub(rf"\b{re.escape(word)}\b", " ", title, flags=re.I)
        return slug or None, title
    return None, title


def can_key(title: str | None, manufacturer: str | None = None) -> str | None:
    """Which can a listing is, as a key two shops' listings of it share.

    A suppressor has no armory model -- the armory is for guns -- so the hot
    deals pass groups cans by this instead: the maker, then the first two
    words left once everything that describes rather than names is taken off.
    "SILENCERCO Omega 36M 7.6in Silencer / Suppressor - Black" and "SilencerCo
    Omega 36M" are both ``silencerco:omega36m``; "Rugged Obsidian 9 9mm" and
    "Rugged Suppressors Obsidian9" are both ``rugged:obsidian9``. Close enough
    to compare a can's price across shops, and None when whose can it is, or
    which, cannot be told.
    """
    text = _SOLD_WITH.sub("", title or "")
    text = re.split(r"\s[-\u2013|]\s|\s/\s", text)[0]
    maker, text = _maker_of(text, manufacturer)
    if not maker:
        return None
    text = _KEY_MEASURE.sub(" ", text.lower())
    text = _KEY_NOISE.sub(" ", text)
    words = re.findall(r"[a-z0-9]+", text)
    model = "".join(words[:2])
    return f"{maker}:{model}" if model else None
