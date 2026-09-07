"""Heuristics that turn listing prose into structured fields.

Vendors publish free text, not data, so caliber / country / manufacturer and the
rifle-vs-pistol split have to be inferred. These rules are the accumulated
result of watching real listings from Royal Tiger Imports and Empire Arms, and
they are deliberately ordered most-specific-first: the first pattern that
matches wins, so a "7.35 Carcano" is not swallowed by the generic Carcano rule.

Everything here is pure and side-effect free, which keeps it cheap to test and
lets scrapers call it without a database session.
"""

from __future__ import annotations

import re
from typing import TypedDict

# ---------------------------------------------------------------------------
# Caliber
# ---------------------------------------------------------------------------
# Accessories that should never be assigned a caliber...
ACCESSORY_KEYWORDS = (
    "belt",
    "loading tool",
    "magazine catch",
    "spring",
    "stripper clip",
    "scope",
    "insert",
    "gas block",
    "handguard",
    "rail",
    "bipod",
    "ammo pouch",
    "canvas",
    "cover",
    "helmet",
    "stahlhelm",
    "binoculars",
    "en bloc clip",
    "enbloc clip",
    "bayonet",
    "certificate of authenticity",
)
# ...unless the listing is a firearm bundled *with* an accessory.
PROMOTIONAL_PHRASES = (
    "with free",
    "w/ free",
    "w/free",
    "with 1 free",
    "w/1 free",
    "with original holster",
    "with holster",
    "with sling",
)
FIREARM_WORDS = (
    "rifle",
    "pistol",
    "carbine",
    "revolver",
    "handgun",
    "firearm",
    "gun",
    "mauser",
    "mosin",
    "carcano",
    "enfield",
    "garand",
    "luger",
    "beretta",
)

# Model or family names that imply a caliber outright.
MODEL_CALIBERS: tuple[tuple[str, str], ...] = (
    (r"ar-?15", "5.56x45mm NATO"),
    (r"ak-?74|ak\s*74", "5.45x39mm"),
    (r"\bak\b(?!\d)", "7.62x39mm"),
    (r"5\.45\s*[x×]\s*39", "5.45x39mm"),
    (r"7\.62\s*[x×]\s*39", "7.62x39mm"),
    (r"7[.,]62\s*[x×]\s*54\s*r", "7.62x54R"),
    (r"7\.62\s*[x×]\s*45", "7.62x45mm"),
    (r"7\.62\s*[x×]\s*51", "7.62x51mm NATO"),
    (r"\bpsl\b", "7.62x54R"),
    (r"m1919", "7.62x51mm NATO"),
    (r"m1\s+carbine", ".30 Carbine"),
    (r"m1\s+garand", ".30-06"),
    (r"u\.?s\.?\s+model\s+of\s+1917", ".30-06"),
    (r"k\.?98|kar\.?98", "8mm Mauser"),
    (r"m48\s+mauser", "8mm Mauser"),
    (r"gew\s*91|kar\s*88|gew\s*71", "8mm Mauser"),
    (r"gewehr\s+(?:71|88|98)", "8mm Mauser"),
    (r"mg\s*34", "8mm Mauser"),
    (r"zb\s*(?:26|37)", "8mm Mauser"),
    (r"lee\s*-?\s*enfield|lee\s*-?\s*speed", ".303 British"),
    (r"\bberthier\b", "8mm Lebel"),
    (r"st\.?\s*etienne\s*19(?:07|15)", "8mm Lebel"),
    (r"\bmakarov\b", "9x18 Makarov"),
    (r"\bskorpion\b", ".32 ACP"),
    (r"\bvigneron\b", "9mm"),
    (r"7\.65.*luger|luger.*7\.65", "7.65 Luger"),
    (r"walther\s+pp", ".32 ACP"),
    (r"(?:vz|cz)\s*[57]0", ".32 ACP"),
    (r"beretta\s+m1935", ".32 ACP"),
    (r"beretta\s+m1934", ".380 ACP"),
    (r"\bbreda\b", "6.5x52mm Carcano"),
    (r"mas\s*49|aa\s*52", "7.5x54mm French"),
    (r"mannlicher.*8\s*[x×]\s*56|8\s*[x×]\s*56.*mannlicher", "8x56mmR"),
    (r"\bmannlicher\b", "8x50mmR"),
    (r"force\s+publique.*mauser|mauser.*force\s+publique", ".30-06"),
    (r"\bkropatschek\b", "11.15x58mmR Kropatschek"),
    (r"m17-38.*flare|flare.*m17-38|34\s*mm.*flare|flare.*34\s*mm", "34mm Flare"),
    (r"26\.5\s*mm.*flare|flare.*26\.5\s*mm", "26.5mm Flare"),
    (r"fusil\s+gras|mle.*1874.*gras|1874.*gras|st\.?\s*etienne", "11mm Gras"),
    (r"vetterli.*6\.5|6\.5.*vetterli", "6.5x52mm Carcano"),
    (r"\bvetterli\b", "10.4x47mmR"),
    (r"\bsks\b", "7.62x39mm"),
    (r"swiss.*7\.5\s*[x×]\s*55|7\.5\s*[x×]\s*55.*swiss", "7.5x55 Swiss"),
    (r"\bg1911\b|swiss.*rifle", "7.5x55 Swiss"),
    (r"\barisaka\b|\btype\s*99\b", "7.7x58mm Arisaka"),
    (r"\btype\s*38\b", "6.5x50mm Arisaka"),
    (r"\bmosin\b", "7.62x54R"),
    (r"\btokarev\b|\btt-?33\b", "7.62x25mm Tokarev"),
    (r"schmidt-?rubin", "7.5x55 Swiss"),
    (r"mauser.*8mm|mauser\s+rifle", "8mm Mauser"),
    (r"\.22\s*long\s*rifle|trainer.*\.22|\.22.*trainer", ".22 LR"),
)

#: A maker's name and nothing else. Tried last, and not at all for a handgun.
#:
#: Both of these firms made a famous rifle and a famous revolver, and the name
#: alone points at the rifle. "MAUSER C96 PISTOL KITS" came back in 8mm Mauser,
#: which is the 98's cartridge and not the C96's, and "ENFIELD NO1 MK2 PARTS
#: KITS" — a .38 revolver — came back in .303 British.
#:
#: They are also demoted below the explicit spellings, which is a fix in its
#: own right: a title reading "Spanish Mauser 7x57" was answered "8mm Mauser"
#: because the maker rule was reached first.
#: Plural, because a dealer sells lots: "1903 TURKISH CONTRACT MAUSERS".
MAKER_CALIBERS: tuple[tuple[str, str], ...] = (
    (r"\benfields?\b", ".303 British"),
    (r"\bmausers?\b", "8mm Mauser"),
)


# Explicit caliber spellings, normalized to one canonical label each.
CALIBER_NORMALIZATIONS: tuple[tuple[str, str], ...] = (
    # Gauges first, so "12 ga" is not mistaken for a metric measurement.
    # "guage" is a common vendor misspelling.
    (r"12\s*(?:ga|gauge|guage)\b", "12-gauge"),
    (r"16\s*(?:ga|gauge|guage)\b", "16-gauge"),
    (r"20\s*(?:ga|gauge|guage)\b", "20-gauge"),
    (r"28\s*(?:ga|gauge|guage)\b", "28-gauge"),
    (r"\.410", ".410 bore"),
    (r"9\s*[x×]\s*19", "9mm"),
    (r"9\s*[x×]\s*18", "9x18 Makarov"),
    (r"\.38\s*special", ".38 Special"),
    (r"8\s*[x×]\s*57", "8mm Mauser"),
    # Its actual name, and it matters: this table names the maker wherever the
    # cartridge does, and that is where a listing like "SPANISH 1916 SHORT
    # RIFLES 7x57" gets its maker from. Left as a bare "7x57" by the generic
    # metric fallback, it named nobody.
    (r"7\s*[x×]\s*57", "7x57mm Mauser"),
    (r"8\s*[x×]\s*56\s*r", "8x56mmR"),
    (r"8\s*[x×]\s*50\s*r", "8x50mmR"),
    (r"7\.5\s*[x×]\s*55", "7.5x55 Swiss"),
    (r"7\.35\s*[x×]\s*51", "7.35x51mm Carcano"),
    (r"6\.5\s*[x×]\s*52", "6.5x52mm Carcano"),
    (r"6\.5\s*[x×]\s*55", "6.5x55 Swedish"),
    (r"10\.4\s*[x×]\s*47\s*r", "10.4x47mmR"),
    (r"7\.7\s*[x×]\s*58", "7.7x58mm Arisaka"),
    (r"cal\.?\s*\.?303\s+british|\.303\s+british|\.303(?!\s*\d)", ".303 British"),
    (r"\.45\s*acp", ".45 ACP"),
    (r"\.380\s*acp|\.380\b", ".380 ACP"),
    (r"\.32\s*acp|\.\s*32\s*acp|\.32\b", ".32 ACP"),
    (r"7\.65\s*mm\b", ".32 ACP"),
    (r"\.22\s*lr|\.22(?!\s*\d)", ".22 LR"),
    (r"\.30-06|\b30-06\b|cal\.?\s*30-06", ".30-06"),
    (r"\.30\s*carbine", ".30 Carbine"),
    (r"\.308\s*win|\.308\b", ".308 Winchester"),
    (r"\.357\s*mag", ".357 Magnum"),
    (r"\.44\s*mag", ".44 Magnum"),
    (r"5\.56\s*[x×]\s*45|\b5\.56\b", "5.56x45mm NATO"),
    (r"\.50\s*bmg", ".50 BMG"),
    (r"\b9\s*mm\b", "9mm"),
)


def _looks_like_accessory(title_lower: str) -> bool:
    if any(phrase in title_lower for phrase in PROMOTIONAL_PHRASES):
        return False
    if any(word in title_lower for word in FIREARM_WORDS):
        return False
    return any(keyword in title_lower for keyword in ACCESSORY_KEYWORDS)


def extract_caliber(  # noqa: PLR0911 - each return is one distinct rule class
    title: str, description: str | None = None
) -> str | None:
    """Best-effort caliber for a listing, or ``None`` when there isn't one."""
    title_lower = (title or "").lower()
    haystack = f"{title or ''} {description or ''}".lower()
    if not haystack.strip():
        return None

    if _looks_like_accessory(title_lower):
        return None

    # Carcano is handled ahead of everything else: its detailed descriptions
    # routinely mention other calibers in passing, and the generic rules below
    # would happily label one .30-06.
    if "carcano" in haystack:
        if re.search(r"7\.35", title_lower) or re.search(r"7\.35", haystack):
            return "7.35x51mm Carcano"
        return "6.5x52mm Carcano"

    for pattern, caliber in MODEL_CALIBERS:
        if re.search(pattern, haystack):
            return caliber

    for pattern, caliber in CALIBER_NORMALIZATIONS:
        if re.search(pattern, haystack):
            return caliber

    # An unrecognized but well-formed metric caliber.
    match = re.search(r"\b\d{1,2}(?:\.\d+)?\s*[x×]\s*\d{2,3}\s*r?\b", haystack)
    if match:
        return re.sub(r"\s+", "", match.group(0)).replace("×", "x").upper().replace("X", "x")

    # Last of all, the maker's name — and never for a handgun, whose maker's
    # famous cartridge is not its own.
    if not _names_a_handgun(title_lower):
        for pattern, caliber in MAKER_CALIBERS:
            if re.search(pattern, haystack):
                return caliber
    return None


def _names_a_handgun(title_lower: str) -> bool:
    """Whether the title says outright, or by designation, that this is one."""
    known = _known_designation(title_lower)
    if known is not None:
        return known[1]
    return any(re.search(pattern, title_lower) for pattern in PISTOL_PATTERNS)


# ---------------------------------------------------------------------------
# Rifle / pistol classification
# ---------------------------------------------------------------------------
# Listings that mention a firearm but are really parts or accessories.
NON_FIREARM_PATTERNS = (
    r"holster\s+for.*pistol",
    r"\bammo\b",
    r"\bpistol\s+grip\b",
    r"\bstock\s+set\b",
    r"\bbutt\s?stocks?\b",
    # A parts kit is parts, whatever it is a kit for. The dealer files every
    # one of them under parts and accessories, including the ones priced like
    # a rifle: an Ethiopian Gafat AK kit at $449 is still a box of parts.
    # A kit named for a *handgun* -- "Revolver Kits", "Pistol Kits" -- is the
    # dealer's own way of selling a handgun, and is deliberately not caught
    # here; only the literal phrase "parts kit" is.
    r"\bparts\s*kits?\b",
    r"\bcleaning\s+kit\b",
    r"\bwinter\s+trigger\b",
    r"\bscope\s+mount\b",
    r"\bfurniture\s+set\b",
    r"\btripod\b",
    r"\bmonte\s+carlo\s+stock\b",
    r"\bhandguard\s+for\b",
    r"\brifle\s+bolts?\b",
    # Dealers who sell firearms sell other things beside them. These have
    # nothing to do with a rifle or a pistol however the surrounding prose
    # reads — a Hunter's Lodge listing for hand-woven Vaquero blankets was
    # filed as a rifle because the neighbouring panel's text bled into its
    # description.
    r"\bblankets?\b",
    r"\bshirts?\b",
    r"\bhats?\b",
    r"\bcaps?\b",
    r"\bposters?\b",
    r"\bbooks?\b",
    r"\bmanuals?\b",
    r"\bpatch(?:es)?\b",
    r"\bmedals?\b",
    r"\bgrips\b",
)

# The common nouns take an optional plural. A word boundary after
# "rifle" does not match "rifles", so the singular-only patterns missed
# every title that named more than one — which on a dealer's catalog is
# most of them ("1893 SPANISH MAUSER LONG RIFLES", "10 PISTOLS").
# Model names are left singular: nobody writes "SKSs" or "C96s".
RIFLE_PATTERNS = (
    r"\brifles?\b",
    r"\bcarbines?\b",
    r"\bgarand\b",
    r"\bsks\b",
    r"\bak-?\d{2}\b",
    r"\bak\b(?!\d)",
    r"\bar-?15\b",
    r"\bk\.?98\b",
    r"\bkar\.?98\b",
    r"\benfield\b",
    r"\bmosin\b",
    r"\bcarcano\b",
    r"\bgewehr\b",
    r"\barisaka\b",
    r"\barisika\b",  # as OCR and dealers both spell it
    r"\bvetterli\b",
    r"\bschmidt.?rubin\b",
    r"\bvz\.?\s?24\b",
    r"\bgahendra\b",
    r"\bmartini\b",
    # Mauser made the C96 pistol as well, but on a surplus catalog the name
    # means a rifle unless something else in the title says otherwise — and
    # when it does, the leading-word tie-break below settles it.
    r"\bmauser\b",
    r"\bgew\s*\d+\b",
    r"\bmas\s*49\b",
    r"\bberthier\b",
    r"\bmannlicher\b",
    r"\bvetterli\b",
    r"\bkropatschek\b",
    r"\bfusil\s+gras\b",
    r"\bbreda\b",
    r"\bzb\s*\d+\b",
    r"\bm1919\b",
    r"\bmg\s*34\b",
    r"\baa\s*52\b",
    r"\bpsl\b",
    r"\barisaka\b",
    r"\bmusket\b",
    r"\bschmidt-?rubin\b",
    r"\bmodel\s+1917\b",
    r"\bg1911\b",
    r"\bshotgun\b",
    r"\bmauser\s+rifle\b",
)

PISTOL_PATTERNS = (
    r"\bpistols?\b",
    r"\brevolvers?\b",
    r"\bhandguns?\b",
    r"\bluger\b",
    r"\bmakarov\b",
    r"\bwalther\s+p\w*\b",
    r"\bberetta\s+m?19\d{2}\b",
    r"\b(?:vz|cz)\s*[57]0\b",
    r"\btokarev\b",
    r"\btt-?33\b",
    r"\bcolt\s+1911\b",
    # Colt's Police Positive, written "Colt PP" on a dealer's flyer. Without
    # this the frames read as neither rifle nor pistol.
    r"\bcolt\s+p\.?\s?p\.?\b",
    r"\bpolice\s+positive\b",
    r"\bbroomhandle\b",
    r"\bc96\b",
    r"\bmauser\s+pistol\b",
    r"\bwebley\b",
    r"\bflare\s+pistol\b",
    r"\bskorpion\b",
    r"\bvigneron\b",
    r"\bnagant\s+revolver\b",
)

# Calibers that only ever appear in handguns. Anchored so "9mm" does not match
# inside "7.62x39mm".
PISTOL_CALIBERS = (
    r"\b\.?32\s*acp\b",
    r"\b\.?380\b",
    r"\b9\s*mm\b",
    r"\b9x18\b",
    r"\b9x19\b",
    r"\b\.?45\s*acp\b",
    r"\b\.?38\s*special\b",
    r"\b\.?357\b",
    r"\b\.?44\b",
    r"\bflare\b",
    r"\bluger\b",
    r"\bmakarov\b",
    r"\btokarev\b",
)

#: Below this price a listing is a part or an accessory, whatever it is called.
#: A $25 "Mosin Nagant rifle" is a book, a toy or a mislabelled part.
MIN_FIREARM_PRICE = 70.0

#: ...with one exception. A frame or a receiver *is* the firearm — it is the
#: serialised part, and it is what the law regulates — so a cheap one is a
#: handgun or a rifle in a way that a cheap sling is not. Without this a
#: dealer's "COLT PP .38 FRAMES" at $29 came back as neither.
#: A barrelled receiver is the same thing again: the serialised part with a
#: barrel on it. Dealers write it "BBL REC", "bbl action" or in full.
_FRAME_PATTERN = re.compile(
    r"\b(?:frames?|receivers?|bbl\.?\s*rec\.?|bbl\.?\s*action|barrell?ed\s+(?:receiver|action))\b",
    re.I,
)

#: A title that says outright what it is selling also outranks the floor. The
#: floor exists to keep slings and pouches out of the firearm filters, and it
#: should not be deciding against a listing headed "WW2 RUSSIAN 91/30 RIFLES" —
#: on a flyer read by OCR the *price* is the least reliable field on the page,
#: and using it to overrule the plainest statement of what something is had
#: excluded five genuine firearms from one page.
#: The words a listing uses to say outright what it is, as opposed to the
#: maker and model names that only imply it.
_RIFLE_NOUN = re.compile(r"\b(?:rifles?|carbines?|muskets?|shotguns?)\b", re.I)

#: Makers who built both, so their name alone settles nothing. A C96 is a
#: Mauser and a handgun; without this the maker outvoted the model and the
#: broomhandle came back a rifle.
_AMBIGUOUS_MAKERS = (r"\bmauser\b",)

_NAMES_A_FIREARM = re.compile(
    r"\b(?:rifles?|carbines?|muskets?|pistols?|revolvers?|handguns?|shotguns?)\b", re.I
)

#: ...unless the listing says it has none. "Parts kit, no frame" is precisely
#: the thing that is *not* a firearm.
_NO_FRAME_PATTERN = re.compile(
    r"\b(?:no|without|less|minus|w/?o)\s+(?:the\s+)?(?:frames?|receivers?)\b", re.I
)


#: Category names that state the firearm type outright.
_CATEGORY_RIFLE = re.compile(r"\b(?:rifles?|carbines?|muskets?|long\s*guns?)\b", re.I)
_CATEGORY_PISTOL = re.compile(r"\b(?:handguns?|pistols?|revolvers?|sidearms?)\b", re.I)


def kind_from_category(category: str | None) -> tuple[bool, bool] | None:
    """Read the firearm type off the vendor's own category, when it says one.

    A dealer who files a listing under "Handguns" has told us something no
    heuristic can reliably infer from a title like "BELGIAN Model 1910/22
    Browning" — which reads as neither a rifle nor a pistol to a pattern
    matcher, and is a pistol.

    Returns ``None`` when the category is missing, says nothing about type
    ("Antique", "Deal of the Day", "Shop All"), or contradicts itself, leaving
    the decision to the heuristics.
    """
    if not category:
        return None
    rifle = bool(_CATEGORY_RIFLE.search(category))
    pistol = bool(_CATEGORY_PISTOL.search(category))
    if rifle == pistol:
        return None
    return (rifle, pistol)


#: Things sold both on their own and bundled with a firearm. Whether the
#: listing is one or the other is decided by which is named first.
_BUNDLED_ACCESSORY = re.compile(
    # "barrel" is here rather than among the outright vetoes because whether it
    # decides anything depends on what came before it: a bare "AK47 16in
    # Chrome Lined Barrel" is a part, while a "Berthier barreled action,
    # shortened barrel" is a firearm that happens to mention its own barrel.
    # The order rule below tells the two apart. Note \bbarrels?\b does not
    # match "barreled", so a barreled action is never read as a loose barrel.
    r"\b(?:slings?|pouch(?:es)?|scabbards?|holsters?|bandoliers?|cleaning\s+kits?|"
    r"stripper\s+clips?|barrels?|handguards?)\b",
    re.I,
)


def _accessory_leads(title_lower: str) -> bool:
    """Whether the title offers an accessory rather than a firearm with one.

    "Leather sling for a Mauser rifle" and "Mosin Nagant rifle with sling" both
    name an accessory and a firearm; the difference is the order. A listing is
    titled for the thing being sold, so whichever comes first is the thing.
    """
    accessory = _BUNDLED_ACCESSORY.search(title_lower)
    if not accessory:
        return False

    # "Pistol holster" and "rifle sling" name one thing, not two. English puts
    # the head noun last, so when the accessory word follows the firearm word
    # immediately the accessory is the product and the firearm merely says
    # what it fits. Reading those two as "a firearm, mentioned first" made a
    # Mauser C96 holster a handgun.
    before = title_lower[: accessory.start()].rstrip()
    named = list(_NAMES_A_FIREARM.finditer(before))
    if named and named[-1].end() == len(before):
        return True
    # A frame or a receiver counts as the thing being sold here for the same
    # reason it survives the price floor: it is the serialized part, so a
    # listing that leads with one is selling a firearm even though it has not
    # used the word.
    firearm_at = [
        match.start()
        for match in (
            _NAMES_A_FIREARM.search(title_lower),
            _FRAME_PATTERN.search(title_lower),
        )
        if match is not None
    ]
    return not firearm_at or accessory.start() < min(firearm_at)


def _is_not_a_firearm(title_lower: str) -> bool:
    r"""True when the *title* says this listing is a part or an accessory.

    Reads the title only, never the description.

    A title is where a vendor says what they are selling; a description is
    where they talk about it. The description of a genuine Vetterli rifle says
    "the rifle bolt is matching", which tripped the ``\brifle\s+bolts?\b``
    accessory veto and filed the rifle under "other". Measured against the live
    catalogs, reading the description here wrongly rejected 17 of 58 Empire
    Arms listings and 61 of 210 Royal Tiger listings — every one of them a
    firearm whose own prose happened to mention a part.
    """
    if any(re.search(pattern, title_lower) for pattern in NON_FIREARM_PATTERNS):
        return True

    # Bayonets, magazines and bolts are sold both standalone and as part of a
    # firearm listing; only the standalone case should be filtered out.
    if "bayonet" in title_lower and not re.search(r"\b(?:rifle|pistol|carbine)\b", title_lower):
        return True
    if (
        re.search(r"\bmagazine\b", title_lower)
        and not re.search(r"\bwith\s+magazine\b", title_lower)
        and not any(word in title_lower for word in FIREARM_WORDS)
    ):
        return True
    if (
        re.search(r"\bbolts?\b", title_lower)
        and not re.search(r"w(?:ithout|/o)\s+bolt", title_lower)
        and not any(word in title_lower for word in FIREARM_WORDS)
    ):
        return True

    if _accessory_leads(title_lower):
        return True

    return _looks_like_accessory(title_lower)


#: Designations whose type cannot be read from the words themselves, each one
#: here because somebody who knows the trade said so. This is the place for
#: facts about the market rather than facts about English, and it is expected
#: to grow.
KNOWN_DESIGNATIONS: tuple[tuple[str, bool, bool], ...] = (
    # On a surplus flyer "Enfield No1 Mk2" is the revolver, not the SMLE rifle
    # that shares most of that designation. Reported by the site's owner.
    (r"\benfield\s*n[o0]\.?\s*1\s*mk\.?\s*2\b", False, True),
)


def _known_designation(title_lower: str) -> tuple[bool, bool] | None:
    for pattern, is_rifle, is_pistol in KNOWN_DESIGNATIONS:
        if re.search(pattern, title_lower):
            return (is_rifle, is_pistol)
    return None


def _is_a_bare_frame(title_lower: str) -> bool:
    """Whether the title offers a frame or receiver, which is the firearm itself."""
    if not _FRAME_PATTERN.search(title_lower) or _NO_FRAME_PATTERN.search(title_lower):
        return False
    return any(re.search(pattern, title_lower) for pattern in RIFLE_PATTERNS + PISTOL_PATTERNS)


#: The licenses the ATF issues, and the ways a dealer writes them: an 03 Curio
#: and Relic license, and a Federal Firearms License. Every surplus listing says
#: which one a buyer needs, so these words are on the page constantly — but they
#: name a *permission*, not a thing, and nobody sells one.
#:
#: This matters because they behave like a product name otherwise. They are set
#: in capitals like one, they sit next to a price like one ("Add frame for
#: $38.88. C&R/FFL required."), and on a flyer read by OCR that was enough to
#: produce a $38.88 listing called "C&R/FFL".
LICENSE_PATTERN = re.compile(
    r"\b(?:C\s*&\s*R|F\.?\s?F\.?\s?L\.?|curios?\s*(?:&|and)\s*relics?)\b",
    re.I,
)

#: The same words plus the grammar a dealer wraps them in, anchored: a title
#: that is *only* this is not a title.
_LICENSE_ONLY = re.compile(
    r"^[\s.,:;/&()-]*"
    r"(?:(?:C\s*&\s*R|F\.?\s?F\.?\s?L\.?|curios?|relics?|license[sd]?|licence[sd]?|"
    r"permits?|required?|req\.?|needed|no|or|and|not|only)"
    r"(?![A-Za-z0-9])[\s.,:;/&()-]*)+$",
    re.I,
)


def names_only_a_license(title: str) -> bool:
    """Whether a title says nothing but which ATF license a buyer needs.

    A listing cannot be a C&R. It can *require* one, and almost all of them do.
    """
    text = (title or "").strip()
    return bool(text) and bool(LICENSE_PATTERN.search(text)) and bool(_LICENSE_ONLY.match(text))


def is_ruled_out(title: str) -> bool:
    """True when the title itself says this is not a firearm.

    The difference between "we decided this is a scabbard" and "we could not
    tell what this is" matters to anything that wants to fill the gap from
    elsewhere: the first is an answer, and borrowing over it would turn a
    sling into the rifle it is a sling for.
    """
    title_lower = (title or "").lower()
    return (
        names_only_a_license(title)
        or _is_not_a_firearm(title_lower)
        or _accessory_leads(title_lower)
    )


def _break_the_tie(title_lower: str) -> tuple[bool, bool]:
    """Decide between rifle and handgun when the text names both.

    The title is the claim; the description is context. When only one of the
    two is named in the title, that is the answer — a listing headed "COLT PP
    .38 FRAMES" is a handgun even if the paragraph beneath it wanders onto
    rifles, which on a flyer read by OCR it routinely does, because the
    neighboring panel's prose bleeds into it.
    """
    rifle_hits = [pattern for pattern in RIFLE_PATTERNS if re.search(pattern, title_lower)]
    rifle_in_title = bool(rifle_hits)
    pistol_in_title = any(re.search(pattern, title_lower) for pattern in PISTOL_PATTERNS)

    if rifle_in_title != pistol_in_title:
        return (rifle_in_title, pistol_in_title)

    # The rifle signal is only a maker's name and the pistol signal is a model.
    # "Mauser C96 Broomhandle" is a Mauser and a C96, and the C96 is the more
    # specific of the two — without this the maker outvoted the model and the
    # broomhandle came back a rifle.
    if pistol_in_title and rifle_hits and all(hit in _AMBIGUOUS_MAKERS for hit in rifle_hits):
        return (False, True)

    # Named in both, or in neither: go with whichever the title leads with, and
    # with rifle when the title settles nothing.
    rifle_at = min(
        (title_lower.find(word) for word in ("rifle", "carbine") if title_lower.find(word) >= 0),
        default=10_000,
    )
    pistol_at = min(
        (title_lower.find(word) for word in ("pistol", "revolver") if title_lower.find(word) >= 0),
        default=10_000,
    )
    return (True, False) if rifle_at <= pistol_at else (False, True)


def classify_firearm(
    title: str,
    description: str | None = None,
    caliber: str | None = None,
    price: float | None = None,
    category: str | None = None,
) -> tuple[bool, bool]:
    """Return ``(is_rifle, is_pistol)``. Both false means "not a firearm"."""
    title_lower = (title or "").lower()

    # A designation somebody has told us about outranks everything, including
    # the vendor's own category: it is the most specific knowledge available.
    known = _known_designation(title_lower)
    if known is not None:
        return known

    # Before anything else, including the vendor's category: a listing whose
    # name is only a license is not a listing at all, and a category cannot
    # make it one.
    if names_only_a_license(title):
        return (False, False)

    stated = kind_from_category(category)
    if stated is not None:
        return stated

    haystack = f"{title or ''} {description or ''}".lower()

    if _is_not_a_firearm(title_lower):
        return (False, False)

    if (
        price is not None
        and price < MIN_FIREARM_PRICE
        and not _is_a_bare_frame(title_lower)
        and not _NAMES_A_FIREARM.search(title_lower)
    ):
        return (False, False)

    is_rifle = any(re.search(p, haystack) for p in RIFLE_PATTERNS)
    is_pistol = any(re.search(p, haystack) for p in PISTOL_PATTERNS)

    if is_rifle and is_pistol:
        is_rifle, is_pistol = _break_the_tie(title_lower)

    # A rifle caliber overrules a pistol *keyword*: "holster, Mauser pistol
    # cartridge" style prose otherwise mislabels rifles.
    #
    # Only a keyword, though — never a title that names a pistol and nothing
    # else. The caliber is often extracted from the description, and on an
    # OCR'd flyer the description carries whatever the neighbouring panel said:
    # "MAUSER C96 PISTOL KITS" picked up "8mm Mauser" from the column beside it
    # and stopped being a handgun on the strength of it. A title naming *both*
    # ("Mauser pistol carbine") is genuinely ambiguous, and there the caliber
    # is still the best evidence available.
    pistol_alone_in_title = any(
        re.search(p, title_lower) for p in PISTOL_PATTERNS
    ) and not _RIFLE_NOUN.search(title_lower)
    if is_pistol and caliber and not pistol_alone_in_title:
        caliber_lower = caliber.lower()
        if not any(re.search(p, caliber_lower) for p in PISTOL_CALIBERS):
            is_pistol = False

    return (is_rifle, is_pistol)


# ---------------------------------------------------------------------------
# Country of origin and manufacturer
# ---------------------------------------------------------------------------
# Nationality words, checked against the start of the title first: these
# vendors reliably lead with it ("ITALIAN Model 1935 ..."). Brand names are
# deliberately excluded -- a Browning may be Belgian or American.
COUNTRY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bFinn(?:ish)?\b", "Finland"),
    (r"\bGerman(?:y|ic)?\b|\bNazi\b|\bPrussian\b", "Germany"),
    (r"\bRussian?\b|\bSoviet\b|\bUSSR\b|\bTula\b|\bIzhevsk\b", "Russia"),
    (r"\bSwedish\b|\bSweden\b", "Sweden"),
    (r"\bSwiss\b|\bSwitzerland\b", "Switzerland"),
    (r"\bBritish\b|\bEnglish\b|\bBritain\b|\bU\.?K\.?\b", "United Kingdom"),
    (r"\bAmerican\b|\bU\.?\s?S\.?\s?A?\.?\b|\bUnited States\b", "United States"),
    (r"\bJapanese\b|\bJapan\b", "Japan"),
    (r"\bItalian\b|\bItaly\b", "Italy"),
    (r"\bFrench\b|\bFrance\b", "France"),
    (r"\bCzech\b|\bCzechoslovak(?:ian)?\b", "Czech Republic"),
    (r"\bAustrian?\b|\bAustro-Hungarian\b", "Austria"),
    (r"\bBelgian?\b|\bBelgium\b", "Belgium"),
    (r"\bSpanish\b|\bSpain\b", "Spain"),
    (r"\bYugoslav(?:ian)?\b|\bSerbian?\b", "Yugoslavia"),
    (r"\bPolish\b|\bPoland\b", "Poland"),
    (r"\bRomanian?\b", "Romania"),
    (r"\bHungarian?\b", "Hungary"),
    (r"\bChinese\b|\bChina\b", "China"),
    (r"\bTurkish\b|\bTurkey\b|\bOttoman\b", "Turkey"),
    (r"\bGreek\b|\bGreece\b", "Greece"),
    (r"\bArgentin(?:e|ian)\b", "Argentina"),
    (r"\bBrazil(?:ian)?\b", "Brazil"),
    (r"\bPeruvian?\b", "Peru"),
    (r"\bChilean?\b", "Chile"),
    (r"\bPersian?\b|\bIranian?\b|\bIran\b", "Persia"),
    (r"\bNorwegian?\b|\bNorway\b", "Norway"),
    (r"\bDanish\b|\bDenmark\b", "Denmark"),
    (r"\bDutch\b|\bNetherlands\b|\bHolland\b", "Netherlands"),
    (r"\bPortuguese\b|\bPortugal\b", "Portugal"),
    (r"\bMexican?\b|\bMexico\b", "Mexico"),
    (r"\bSouth African\b", "South Africa"),
    (r"\bCanadian?\b|\bCanada\b", "Canada"),
    (r"\bIndian?\b|\bIshapore\b", "India"),
    (r"\bEgyptian?\b", "Egypt"),
    (r"\bEthiopian?\b", "Ethiopia"),
    (r"\bBulgarian?\b", "Bulgaria"),
)

MANUFACTURER_PATTERNS: tuple[tuple[str, str], ...] = (
    # The model designations too, because a dealer often gives only those:
    # "RUSSIAN M44 CARBINES" and "WW2 RUSSIAN 91/30 RIFLES" name no maker at
    # all. Deliberately not M38, which is a Carcano as often as it is a Mosin.
    (r"\bMosin[- ]?Nagant\b|\bM?91/30\b|\bM44\b", "Mosin-Nagant"),
    (r"\bTikka\b", "Tikka"),
    (r"\bVKT\b", "VKT"),
    (r"\bSAKO\b", "SAKO"),
    (r"\bMauser\b", "Mauser"),
    (r"\bEnfield\b", "Enfield"),
    (r"\bSpringfield\b", "Springfield"),
    (r"\bWinchester\b", "Winchester"),
    (r"\bRemington\b", "Remington"),
    (r"\bMarlin\b", "Marlin"),
    (r"\bSavage\b", "Savage"),
    (r"\bColt\b", "Colt"),
    (r"\bSmith\s*&?\s*Wesson\b|\bS&W\b", "Smith & Wesson"),
    (r"\bRuger\b", "Ruger"),
    (r"\bBeretta\b", "Beretta"),
    (r"\bBrowning\b", "Browning"),
    (r"\bGlock\b", "Glock"),
    (r"\bWalther\b", "Walther"),
    (r"\bLuger\b|\bP-?08\b", "Luger"),
    # "Arisika" is not a spelling anyone uses; it is what OCR makes of a
    # flyer's "ARISAKA", and a scanned page is a source like any other.
    (r"\bArisaka\b|\bArisika\b", "Arisaka"),
    (r"\bCarcano\b", "Carcano"),
    (r"\bSchmidt-?Rubin\b", "Schmidt-Rubin"),
    (r"\bHusqvarna\b", "Husqvarna"),
    (r"\bCarl Gustaf\b", "Carl Gustaf"),
    (r"\bSteyr\b", "Steyr"),
    (r"\bZastava\b", "Zastava"),
    (r"\bRadom\b", "Radom"),
    (r"\bTokarev\b|\bTT-?33\b", "Tokarev"),
    (r"\bNagant\b", "Nagant"),
    (r"\bIzhevsk\b", "Izhevsk"),
    (r"\bTula\b", "Tula"),
    (r"\bFN\b", "FN"),
    # ZB is Zbrojovka Brno, the same firm. Named by model because a bare "ZB"
    # is two letters that turn up inside other things; ZB26 and ZB37 are what
    # a dealer actually writes. Without this a ZB37 machine gun took its maker
    # from its cartridge and came back a Mauser.
    (r"\bCZ\b|\bBrno\b|\bZB\s?(?:26|37|30)\b", "CZ"),
    (r"\bVetterli\b", "Vetterli"),
    (r"\bBerthier\b", "Berthier"),
    (r"\bMannlicher\b", "Mannlicher"),
)


def _match_first(patterns: tuple[tuple[str, str], ...], text: str) -> str | None:
    for pattern, label in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return None


def extract_country(title: str, description: str | None = None) -> str | None:
    """Country of origin, preferring the nationality that leads the title."""
    lead = (title or "")[:48]
    country = _match_first(COUNTRY_PATTERNS, lead)
    if country:
        return country
    return _match_first(COUNTRY_PATTERNS, f"{title or ''} {description or ''}")


def extract_manufacturer(title: str, description: str | None = None) -> str | None:
    return _match_first(MANUFACTURER_PATTERNS, f"{title or ''} {description or ''}")


# ---------------------------------------------------------------------------
# Bore condition
# ---------------------------------------------------------------------------
#: Ordered most-specific-first; the first match wins.
BORE_GRADES: tuple[tuple[str, str], ...] = (
    (r"\bpoor\s+to\s+fair\b|\bfair\s+to\s+poor\b", "Poor to Fair"),
    (r"\bpoor\s+to\s+good\b", "Poor to Good"),
    (r"\bfair\s+to\s+good\b|\bgood\s+to\s+fair\b", "Fair to Good"),
    (r"\bpoor\b", "Poor"),
    (r"\bfair\b", "Fair"),
    (r"\bexcellent\b|\bvery\s+good\b|\bmint\b", "Excellent"),
    (r"\bgood\b", "Good"),
)


def extract_bore_condition(description: str | None) -> str | None:
    """Grade the bore from the description, or ``None`` if it isn't mentioned.

    Only sentences that actually contain the word "bore" are graded. Judging the
    whole description instead would pick up "overall condition is excellent" and
    report it as an excellent bore.
    """
    if not description:
        return None
    text = description.lower()
    if "bore" not in text:
        return None
    bore_sentences = " ".join(s for s in re.split(r"[.!?]+", text) if "bore" in s)
    if not bore_sentences:
        return None
    for pattern, grade in BORE_GRADES:
        if re.search(pattern, bore_sentences):
            return grade
    return None


class EnrichedFields(TypedDict):
    """The structured fields derived from a listing's free text."""

    caliber: str | None
    country: str | None
    manufacturer: str | None
    condition: str | None
    is_rifle: bool
    is_pistol: bool


def enrich(
    title: str,
    description: str | None = None,
    price: float | None = None,
    caliber: str | None = None,
    country: str | None = None,
    manufacturer: str | None = None,
    category: str | None = None,
    trust_description: bool = True,
) -> EnrichedFields:
    """Derive every structured field at once.

    Values a scraper already parsed off the page are trusted and passed through;
    only the gaps are filled by the heuristics. ``category`` is the vendor's own
    section name, which outranks the heuristics when it names a firearm type.

    ``trust_description`` is false for a source whose prose is not about the
    listing it is attached to — a flyer read by OCR, where the text beside a
    product bleeds in from the panel next to it. The description is still used
    to tell a rifle from a handgun, which is a judgement about the whole block
    of text and survives some contamination; it is barred from supplying a
    caliber, a country, a maker or a condition, which are specific claims and
    do not.
    """
    evidence = description if trust_description else None
    caliber = caliber or extract_caliber(title, evidence)
    is_rifle, is_pistol = classify_firearm(title, description, caliber, price, category)
    return {
        "caliber": caliber,
        "country": country or extract_country(title, evidence),
        "manufacturer": manufacturer or extract_manufacturer(title, evidence),
        "condition": extract_bore_condition(evidence),
        "is_rifle": is_rifle,
        "is_pistol": is_pistol,
    }
