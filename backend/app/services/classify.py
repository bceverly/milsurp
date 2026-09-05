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
    (r"lee\s*-?\s*enfield|lee\s*-?\s*speed|\benfield\b", ".303 British"),
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
    (r"mauser.*8mm|mauser\s+rifle|\bmauser\b", "8mm Mauser"),
    (r"\.22\s*long\s*rifle|trainer.*\.22|\.22.*trainer", ".22 LR"),
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

    # Last resort: an unrecognized but well-formed metric caliber.
    match = re.search(r"\b\d{1,2}(?:\.\d+)?\s*[x×]\s*\d{2,3}\s*r?\b", haystack)
    if match:
        return re.sub(r"\s+", "", match.group(0)).replace("×", "x").upper().replace("X", "x")
    return None


# ---------------------------------------------------------------------------
# Rifle / pistol classification
# ---------------------------------------------------------------------------
# Listings that mention a firearm but are really parts or accessories.
NON_FIREARM_PATTERNS = (
    r"holster\s+for.*pistol",
    r"\bammo\b",
    r"\bpistol\s+grip\b",
    r"\bstock\s+set\b",
    r"\bcleaning\s+kit\b",
    r"\bwinter\s+trigger\b",
    r"\bscope\s+mount\b",
    r"\bfurniture\s+set\b",
    r"\btripod\b",
    r"\bmonte\s+carlo\s+stock\b",
    r"\bhandguard\s+for\b",
    r"\brifle\s+bolts?\b",
    r"\bgrips\b",
)

RIFLE_PATTERNS = (
    r"\brifle\b",
    r"\bcarbine\b",
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
    r"\bpistol\b",
    r"\brevolver\b",
    r"\bhandgun\b",
    r"\bluger\b",
    r"\bmakarov\b",
    r"\bwalther\s+p\w*\b",
    r"\bberetta\s+m?19\d{2}\b",
    r"\b(?:vz|cz)\s*[57]0\b",
    r"\btokarev\b",
    r"\btt-?33\b",
    r"\bcolt\s+1911\b",
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

#: Below this price a listing is a part or accessory, whatever it is called.
MIN_FIREARM_PRICE = 70.0


def classify_firearm(  # noqa: PLR0911 - a flat list of exclusion rules
    title: str,
    description: str | None = None,
    caliber: str | None = None,
    price: float | None = None,
) -> tuple[bool, bool]:
    """Return ``(is_rifle, is_pistol)``. Both false means "not a firearm"."""
    title_lower = (title or "").lower()
    haystack = f"{title or ''} {description or ''}".lower()

    if price is not None and price < MIN_FIREARM_PRICE:
        return (False, False)

    for pattern in NON_FIREARM_PATTERNS:
        if re.search(pattern, haystack):
            return (False, False)

    # Bayonets, magazines and bolts are sold both standalone and as part of a
    # firearm listing; only the standalone case should be filtered out.
    if "bayonet" in title_lower and not re.search(r"\b(?:rifle|pistol|carbine)\b", title_lower):
        return (False, False)
    if (
        re.search(r"\bmagazine\b", title_lower)
        and not re.search(r"\bwith\s+magazine\b", title_lower)
        and not any(word in title_lower for word in FIREARM_WORDS)
    ):
        return (False, False)
    if (
        re.search(r"\bbolts?\b", title_lower)
        and not re.search(r"w(?:ithout|/o)\s+bolt", title_lower)
        and not any(word in title_lower for word in FIREARM_WORDS)
    ):
        return (False, False)

    if _looks_like_accessory(title_lower):
        return (False, False)

    is_rifle = any(re.search(p, haystack) for p in RIFLE_PATTERNS)
    is_pistol = any(re.search(p, haystack) for p in PISTOL_PATTERNS)

    # A description that mentions both wins for whichever the *title* leads with.
    if is_rifle and is_pistol:
        rifle_at = min(
            (title_lower.find(w) for w in ("rifle", "carbine") if title_lower.find(w) >= 0),
            default=10_000,
        )
        pistol_at = min(
            (title_lower.find(w) for w in ("pistol", "revolver") if title_lower.find(w) >= 0),
            default=10_000,
        )
        if rifle_at <= pistol_at:
            is_pistol = False
        else:
            is_rifle = False

    # A rifle caliber overrules a pistol keyword: "holster, Mauser pistol
    # cartridge" style prose otherwise mislabels rifles.
    if is_pistol and caliber:
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
    (r"\bMosin[- ]?Nagant\b", "Mosin-Nagant"),
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
    (r"\bArisaka\b", "Arisaka"),
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
    (r"\bCZ\b|\bBrno\b", "CZ"),
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
) -> EnrichedFields:
    """Derive every structured field at once.

    Values a scraper already parsed off the page are trusted and passed through;
    only the gaps are filled by the heuristics.
    """
    caliber = caliber or extract_caliber(title, description)
    is_rifle, is_pistol = classify_firearm(title, description, caliber, price)
    return {
        "caliber": caliber,
        "country": country or extract_country(title, description),
        "manufacturer": manufacturer or extract_manufacturer(title, description),
        "condition": extract_bore_condition(description),
        "is_rifle": is_rifle,
        "is_pistol": is_pistol,
    }
