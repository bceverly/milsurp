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

#: The same words, matched whole.
#:
#: These were substring tests, and one of them was quietly wrong for every
#: Springfield in the catalog: "spring" is inside "Springfield", so a
#: Springfield Model 1903 was an accessory and never got a caliber at all —
#: 23 of the 28 in the database. "cover" inside "recovered" and "rail" inside
#: "trail" are the same trap waiting to be walked into.
#:
#: The exception, and the reason this is a rule rather than a list of words:
#: an optic is named by what it is on the end of. A telescope, a periscope and
#: a riflescope are all the same kind of thing and none of them is spelled
#: "scope", so this one keeps its prefix.
_ACCESSORY_SUFFIXES = ("scope",)

#: Longest first so a phrase is preferred to a word inside it, and the phrases
#: keep their spaces: \b works around "en bloc clip" as readily as around
#: "helmet".
_ACCESSORY_WORDS = re.compile(
    r"\b(?:"
    + "|".join(
        [rf"\w*{re.escape(k)}" for k in _ACCESSORY_SUFFIXES]
        + [
            re.escape(k)
            for k in sorted(ACCESSORY_KEYWORDS, key=len, reverse=True)
            if k not in _ACCESSORY_SUFFIXES
        ]
    )
    + r")\b"
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
    (r"gew\.?\s*(?:71|88|91|98)|kar\s*88", "8mm Mauser"),
    (r"gewehr\s+(?:71|88|98)", "8mm Mauser"),
    (r"mg\s*34", "8mm Mauser"),
    (r"zb\s*(?:26|37)", "8mm Mauser"),
    (r"lee\s*-?\s*enfield|lee\s*-?\s*speed", ".303 British"),
    (r"\bberthier\b", "8mm Lebel"),
    (r"8\s*mm\s*lebel", "8mm Lebel"),
    (r"\bnambu\b|8\s*mm\s*nambu", "8mm Nambu"),
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
    # The hyphenated cartridge names, first of all — bore and powder charge in
    # grains, joined by a hyphen. They go above everything because the rules
    # below match their first half: ".32-20" read by the ".32" rule becomes a
    # .32 ACP, and ".44-40" read by the bare-bore rule becomes a .44. Either
    # way the half of the name that says *which* one is thrown away.
    (r"\.?44-40\b", ".44-40 Winchester"),
    (r"\.?38-40\b", ".38-40 Winchester"),
    (r"\.?38-55\b", ".38-55 Winchester"),
    (r"\.?32-20\b", ".32-20 Winchester"),
    (r"\.?45-70\b", ".45-70 Government"),
    (r"\.?45-90\b", ".45-90 Winchester"),
    (r"\.?30-40\s*krag\b|\.?30-40\b", ".30-40 Krag"),
    (r"\.?30-30\b", ".30-30 Winchester"),
    (r"\.40\s*s\s*&\s*w|\.40\s*sw\b", ".40 S&W"),
    (r"\b10\s*mm\s*auto\b|\b10\s*mm\b", "10mm Auto"),
    (r"9\s*[x×]\s*19", "9mm"),
    (r"9\s*[x×]\s*18", "9x18 Makarov"),
    (r"\.38\s*special", ".38 Special"),
    (r"8\s*[x×]\s*57", "8mm Mauser"),
    # The same cartridge under its metric name, which is how a Yugoslav or
    # Czech rifle is usually described.
    (r"7\.92\s*[x×]\s*57", "8mm Mauser"),
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
    (r"6\.5\s*[x×]\s*50", "6.5x50mm Arisaka"),
    (r"cal\.?\s*\.?303\s+british|\.303\s+british|\.303(?!\s*\d)", ".303 British"),
    (r"\.45\s*acp", ".45 ACP"),
    # .25 ACP is 6.35x16mm Browning; a dealer writes it either way, and often
    # both at once — "BAYARD MODEL 1908 .25ACP/6.35". No space is required
    # after the dot: that is how it is actually typed.
    # The "mm" is spelled out rather than left to a word boundary, for the same
    # reason the generic metric rule now does: there is no boundary between the
    # 35 and the mm of "6.35mm".
    (r"\.25\s*acp|\b6\.35\s*mm\b|\b6\.35\b|\.25\b", ".25 ACP"),
    (r"\.380\s*acp|\.380\b", ".380 ACP"),
    # After .380, so the longer number is read first.
    (r"\.38\s*(?:special|spl)\b|\.38\b", ".38 Special"),
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
    # Bare "8mm", and it has to come last of all.
    #
    # A dealer writes "Yugoslavian M48 Bolt Action Rifle 8mm" and means 8x57,
    # every time — but "8mm" on its own is also how 8mm Lebel and 8mm Nambu are
    # abbreviated, so this rule is only allowed what those two, and 8x57 and
    # 7.92x57 above them, have already declined.
    (r"\b8\s*mm\b", "8mm Mauser"),
)

#: Bore diameters in inches that a dealer writes as a bare number.
#:
#: The percussion and early-cartridge end of the catalog is described this way
#: and no other: "Bacon 1st Model Excelsior Pocket Percussion Revolver - .31",
#: "Burnside Saddle Ring Carbine - .54 Burnside". The list is closed rather
#: than a pattern for any two digits because any two digits also matches the
#: cents of a price and the last two digits of a year.
#:
#: Only the ones CALIBER_NORMALIZATIONS does not already name, so this can
#: never overrule a cartridge that was actually identified.
#: The trailing (?!-\d) is the whole of what was wrong with the first version:
#: it read "Winchester Model 1873, .44-40" as a .44 and dropped the half of the
#: name that says which .44 it is. Anything hyphenated to a second number is a
#: cartridge with a proper name, and belongs in the table above.
_BARE_BORE = re.compile(r"(?<![\d.])\.(?:31|36|40|41|44|450|455|46|50|54|577|58)\b(?!-\d)")

#: A metric bore written without a case length: "4.25MM SEMI AUTO PISTOL".
#: Bounded to what a small arm can be, because "50mm" is artillery and "35mm"
#: is a photograph of the rifle.
_BARE_METRIC = re.compile(r"\b(\d{1,2}(?:\.\d+)?)\s*mm\b")
_METRIC_BORE_RANGE = (4.0, 15.0)


def _looks_like_accessory(title_lower: str) -> bool:
    if any(phrase in title_lower for phrase in PROMOTIONAL_PHRASES):
        return False
    if any(word in title_lower for word in FIREARM_WORDS):
        return False
    return bool(_ACCESSORY_WORDS.search(title_lower))


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

    # Carcano is settled ahead of everything else: its detailed descriptions
    # routinely mention other calibers in passing, and the generic rules below
    # would happily label one .30-06.
    if "carcano" in haystack:
        return _carcano(haystack)

    for pattern, caliber in MODEL_CALIBERS:
        if re.search(pattern, haystack):
            return caliber

    for pattern, caliber in CALIBER_NORMALIZATIONS:
        if re.search(pattern, haystack):
            return caliber

    # An unrecognized but well-formed metric caliber.
    #
    # The trailing "mm" is optional and *inside* the match, because it was the
    # word boundary that broke this: "10.35x22mm" has no boundary between the
    # 22 and the mm, so a pattern ending in \b matched nothing at all. Three
    # calibers in the catalog were being missed for that reason alone.
    match = re.search(r"\b\d{1,2}(?:\.\d+)?\s*[x×]\s*\d{2,3}\s*(?:r\b|mm\b|\b)", haystack)
    if match:
        # Upper-cased for the "R" of a rimmed cartridge (7.62x54R), then the
        # two letters that are conventionally lower put back: "10.35x22MM" is
        # not how anybody writes it.
        normalized = re.sub(r"\s+", "", match.group(0)).replace("×", "x").upper()
        return normalized.replace("X", "x").replace("MM", "mm")

    # A bore written on its own. Weaker than a named cartridge, so it is tried
    # only once every cartridge rule has declined — but it is still something
    # the listing actually says, which is why it comes before guessing from the
    # maker's name.
    bore = _bare_bore(haystack)
    if bore:
        return bore

    # Last of all, the maker's name — and never for a handgun, whose maker's
    # famous cartridge is not its own.
    if not _names_a_handgun(title_lower):
        for pattern, caliber in MAKER_CALIBERS:
            if re.search(pattern, haystack):
                return caliber
    return None


def _carcano(haystack: str) -> str:
    """Which of the two Carcano cartridges a listing means."""
    return "7.35x51mm Carcano" if "7.35" in haystack else "6.5x52mm Carcano"


def _bare_bore(haystack: str) -> str | None:
    """A bore diameter with no cartridge named after it, in inches or mm."""
    inches = _BARE_BORE.search(haystack)
    if inches:
        return inches.group(0)

    metric = _BARE_METRIC.search(haystack)
    if metric and _METRIC_BORE_RANGE[0] <= float(metric.group(1)) <= _METRIC_BORE_RANGE[1]:
        return f"{metric.group(1)}mm"
    return None


#: A blade, as the thing being sold.
#:
#: Deliberately not "the title contains the word": a third of the listings that
#: mention one are firearms that come with one. Nor is "the listing is not
#: already a rifle" enough of a guard, which is what this rule tried first —
#: "Springfield Model 1884 Trapdoor w/ Ramrod Bayonet" names no word the
#: classifier knows to be a firearm, so under one vendor's category it reads as
#: a rifle and under another's it reached this rule and came back a blade.
#:
#: What actually separates them is "with". A bayonet introduced by "with" or
#: "w/" is what comes in the box; a bayonet named without one is what is for
#: sale. Order matters: "Bayonet with scabbard" is still a bayonet, so only a
#: "with" that appears *before* the word counts.
_BAYONET = re.compile(r"\bbayonets?\b", re.I)

#: A listing saying what it does *not* come with.
#:
#: "Russian Tula SKS - No Import Marks - Numbers Matching - No Bayonet" is a
#: rifle described by what is missing, and it came back a bayonet: the word was
#: there and nothing looked at the "No" in front of it.
#:
#: The leading \b is load-bearing and not decoration. Without it this matches
#: inside "Carca-no Bayonet", and every Carcano bayonet in the catalog becomes
#: a rifle that has none.
#: Anchored to the end, so it only matches a negation that runs right up to the
#: word it negates. Unanchored, "No Import Marks - Numbers Matching - No
#: Bayonet" found the *first* "No" forty characters earlier and concluded
#: nothing, which is how the rifle that prompted all this stayed a bayonet.
_LACKING = re.compile(
    r"\b(?:no|without|w/o|less|minus|missing|sans|lack(?:s|ing)?)\s+"
    r"(?:a\s+|an\s+|the\s+|its\s+|original\s+)*$",
    re.I,
)


def _lacks(title: str, thing: re.Pattern[str]) -> bool:
    """Whether the title says this listing comes *without* the named thing."""
    return any(_LACKING.search(title[: found.start()]) for found in thing.finditer(title or ""))


#: "w/" gets no trailing \b: there is no word boundary after a slash, so
#: r"\bw/\b" matches nothing at all — which is exactly how the first version of
#: this failed, silently, on the listings it was written for.
#: A bare "w" means "with" only when a space follows it. Without that lookahead
#: it also matches the W of "W+F Bern" — Waffenfabrik Bern — and their K31
#: Pioneer Sawback Bayonet stopped being a bayonet.
_COMES_WITH = re.compile(r"\bw/|\bw(?=\s)|\b(?:with|and|plus|incl(?:udes|uding)?)\b", re.I)

#: A parts kit, which is the one non-firearm category worth carrying: it is a
#: whole firearm minus the serialized part, and people watch for them the way
#: they watch for rifles. The vendor's own section name is the better signal
#: where there is one — Royal Tiger files them under "Parts Kit" — and the
#: title carries it otherwise.
_PARTS_KIT = re.compile(r"\bparts?\s+kits?\b", re.I)


def _is_a_bayonet(title: str) -> bool:
    found = _BAYONET.search(title or "")
    if found is None or _lacks(title, _BAYONET):
        return False
    return _COMES_WITH.search(title[: found.start()]) is None


def _is_a_parts_kit(title: str, category: str | None) -> bool:
    return bool(_PARTS_KIT.search(title or "") or _PARTS_KIT.search(category or ""))


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
    # The action, used as the name of the gun: "Springfield Model 1884
    # Trapdoor w/ Ramrod Bayonet" says nothing else that names a firearm, so
    # under one vendor's category it read as a rifle and under another's it
    # read as neither — and then as a bayonet.
    r"\btrap\s?door\b",
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
    #
    # "magazine" is spelled out in full and "mag" is deliberately not accepted:
    # ".44 Mag" is a cartridge and "Mag Fed Shotgun" is a shotgun, and both
    # would lead this rule straight past the firearm they are describing.
    r"\b(?:slings?|pouch(?:es)?|scabbards?|holsters?|bandoliers?|cleaning\s+kits?|"
    r"stripper\s+clips?|barrels?|handguards?|magazines?)\b",
    re.I,
)


#: Every way a title can name the firearm itself — the plain nouns above, and
#: the models that are used as nouns in their own right.
#:
#: Used only for the adjacency test below, never for the "which came first"
#: test. That distinction is load-bearing: teaching the order rule that "AK47"
#: names a firearm made "AK47 / AKM 16in Chrome Lined Barrels" a rifle, because
#: the AK47 is named before the barrels. It is not a rifle — it is a box of
#: barrels, and the AK47 is only saying what they fit.
_NAMES_A_FIREARM_OR_MODEL = re.compile(
    "|".join(
        [_NAMES_A_FIREARM.pattern]
        + [f"(?:{pattern})" for pattern in (*PISTOL_PATTERNS, *RIFLE_PATTERNS)]
    ),
    re.I,
)


#: Words that mark the accessory as this gun's own rather than as the product.
#:
#: A collector writes "matching" to mean the serial numbers agree, which is a
#: claim about a firearm that has the part, not an offer of the part. Anchored
#: to sit immediately before the accessory word so it cannot reach across a
#: whole title.
_BELONGS_TO_THE_GUN = re.compile(
    r"\b(?:matching|numbers[- ]matching|all[- ]matching|its|original|correct)\s+$", re.I
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

    # An accessory described as belonging to this particular firearm is not
    # the thing being sold — it is a fact about the thing being sold.
    #
    # "Rare 1925-Dated Simson Luger - Matching Magazine" is a $3,995 pistol
    # whose magazine carries its serial number, which is exactly why the
    # dealer mentioned it. "Erma Luger Magazine" is a $200 magazine. The two
    # titles are the same shape and only this tells them apart.
    if _BELONGS_TO_THE_GUN.search(title_lower[: accessory.start()]):
        return False

    # "Pistol holster" and "rifle sling" name one thing, not two. English puts
    # the head noun last, so when the accessory word follows the firearm word
    # immediately the accessory is the product and the firearm merely says
    # what it fits. Reading those two as "a firearm, mentioned first" made a
    # Mauser C96 holster a handgun.
    before = title_lower[: accessory.start()].rstrip()
    named = list(_NAMES_A_FIREARM_OR_MODEL.finditer(before))
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


#: An accessory the listing says it comes with, or says it comes without.
#:
#: Either way the words are about a part that is not the product, so they are
#: taken out of the title before the accessory vetoes read it. Two real
#: listings needed this and pull in opposite directions: "Enfield No4 Mk1 .303
#: British w Bayonet" is a rifle that includes one, and "Russian Tula SKS - No
#: Bayonet" is a rifle that does not — and both were filed as bayonets, because
#: every rule involved saw the word and none of them saw "w" or "No".
#:
#: Removing the phrase rather than special-casing each rule is what makes this
#: hold: the vetoes then simply never see a part that was never for sale.
_ATTACHED_PART = re.compile(
    r"\b(?:with|w/|w|no|without|w/o|less|minus|missing|sans|plus|and|incl(?:udes|uding)?)\s+"
    r"(?:the\s+|a\s+|an\s+|its\s+|original\s+|reproduction\s+|ramrod\s+|matching\s+)*"
    r"(?:bayonets?|scabbards?|slings?|holsters?|magazines?)\b",
    re.I,
)


def _without_attached_parts(title_lower: str) -> str:
    """The title with "w/ bayonet" and "no bayonet" taken out of it."""
    return _ATTACHED_PART.sub(" ", title_lower)


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

    # From here on, a part the listing says it comes with (or without) is not
    # evidence about what is being sold.
    title_lower = _without_attached_parts(title_lower)

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
#: and Relic license, and a Federal Firearms License. Every surplus listing
#: says which one a buyer needs, so these words are on the page constantly —
#: but they name a *permission*, not a thing, and nobody sells one.
#:
#: This matters because they behave like a product name otherwise. They are set
#: in capitals like one, they sit next to a price like one ("Add frame for
#: $38.88. C&R/FFL required."), and on a flyer read by OCR that was enough to
#: produce a $38.88 listing called "C&R/FFL".
#: The grammar a dealer wraps those words in. Checked by splitting the title
#: into words rather than with one big pattern.
#:
#: The pattern this replaces was `^[punct]*(?:(?:alt|alt|…)[punct]*)+$`, which
#: CodeQL flagged as an inefficient regular expression and was right to: the
#: alternatives overlap ("req" against "required", "license" against
#: "licence"), the separator can match nothing, and the whole thing is inside a
#: `+` anchored at the end. A title that *nearly* matches makes the engine try
#: every way of splitting it before giving up.
#:
#: Splitting on words first is linear, and easier to read besides.
_LICENSE_GRAMMAR = frozenset(
    ["no", "or", "and", "not", "only", "required", "require", "req", "needed"]
)

#: The words that actually name a license. One of these has to be present:
#: "required" on its own names nothing.
_LICENSE_NAMES = frozenset(
    [
        "c&r",
        "ffl",
        "curio",
        "curios",
        "relic",
        "relics",
        "license",
        "licenses",
        "licensed",
        "licence",
        "licences",
        "licenced",
        "permit",
        "permits",
    ]
)

#: A word, keeping "&" so "C&R" survives as one. Dots are dropped afterwards,
#: which turns "F.F.L." into "ffl" and "req." into "req".
_LICENSE_TOKEN = re.compile(r"[a-z0-9&.]+")


def license_words(text: str) -> list[str]:
    """A licence line split into comparable words.

    Public because the flyer reader asks the same question of a line of OCR,
    and one definition of "what counts as a word here" is better than two.
    """
    spaced = re.sub(r"\s*&\s*", "&", text.lower())
    return [word for word in (t.replace(".", "") for t in _LICENSE_TOKEN.findall(spaced)) if word]


def names_only_a_license(title: str) -> bool:
    """Whether a title says nothing but which ATF license a buyer needs.

    A listing cannot be a C&R. It can *require* one, and almost all of them do.
    """
    words = license_words(title or "")
    if not words:
        return False
    if not all(word in _LICENSE_GRAMMAR or word in _LICENSE_NAMES for word in words):
        return False
    return any(word in _LICENSE_NAMES for word in words)


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
    is_bayonet: bool
    is_parts_kit: bool


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
        # Both are kinds of "neither a rifle nor a handgun", so they are only
        # ever asked about a listing that is already neither. "Springfield
        # Trapdoor Rifle w/ Ramrod Bayonet" says bayonet and is a rifle.
        "is_bayonet": not (is_rifle or is_pistol) and _is_a_bayonet(title),
        "is_parts_kit": _is_a_parts_kit(title, category),
    }
