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
    # And the ones that share a bore with a different cartridge entirely. A
    # bare ".38" used to answer ".38 Special" for all of them, which filed a
    # Colt 1911 in .38 Super as a revolver round; ".45 Colt" and ".45 LC" are
    # not .45 ACP either.
    (r"\.?38\s*super\b", ".38 Super"),
    (r"\.?38\s*s\s*&\s*w\b|\.?38\s*smith\b", ".38 S&W"),
    (r"\.?45\s*(?:lc\b|long\s+colt\b|colt\b)", ".45 Colt"),
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
    # The bare-bore fallback, which must not answer for a cartridge that
    # merely starts with the same number. The named ones above are tried
    # first, and this refuses the rest rather than guessing.
    (
        (
            r"\.38\s*(?:special|spl)\b"
            r"|\.38\b(?!\s*(?:super|s\s*&\s*w|smith|acp|auto|colt|long|short|-))"
        ),
        ".38 Special",
    ),
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
#: The negative lookahead is not decoration: a bayonet *lug* is a fitting on
#: the rifle's barrel, and "JRA Gallant Rifle ... W/ Comp & Bayonet Lug" and
#: "BM-59 Paratrooper ... Bipod, Bayonet Lug" are both rifles.
_BAYONET = re.compile(r"\bbayonets?\b(?!\s+lugs?\b)", re.I)

#: The sheath. On its own it says nothing -- see _is_a_bayonet().
_SCABBARD = re.compile(r"\bscabbards?\b", re.I)

#: The bolt, which a rifle listing names as often to say it is missing.
_BOLT = re.compile(r"\bbolts?\b", re.I)


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

#: A receiver that has been cut apart, which is a parts kit whatever the law
#: calls it. The site's owner asked for this explicitly: a torch-cut ZB37
#: receiver is the remains of a machine gun, and nobody watching for a rifle
#: wants one in the results.
#:
#: Every word here is anchored, because "cut" is a minefield in this catalog.
#: It sits inside *conse-cut-ive*, which would have taken a pair of consecutive
#: serial-numbered Lugers; "CNC Billet Cut" is how a receiver was machined;
#: and a "Cutaway" or "Cutdown" rifle is a rifle -- the first a factory
#: teaching aid, the second simply shortened. \bcut\b matches none of those
#: three, and the qualifiers in front of it rule out the fourth.
#:
#: A bare "cut receiver" was tried and taken straight back out. JRA sell a
#: BM-59 and a BM-62 built on a "New Steel Billet Cut Receiver" -- a receiver
#: freshly machined out of billet, which is the opposite of a demilled one and
#: reads identically. Only the destructive qualifiers are kept.
_DEMILLED = re.compile(
    r"\b(?:torch|saw|flame|plasma|acetylene)[\s-]*cut\b"
    r"|\bcut[\s-]*(?:up|apart)\b"
    r"|\bde-?mil(?:led|itari[sz]ed)?\b",
    re.I,
)

#: A muzzleloader sold as a kit to build. It belongs with the parts kits for
#: the same reason they do: it is a whole gun that is not yet a gun, and
#: somebody watching for a finished 1861 Springfield does not want one in the
#: results.
#:
#: Muzzleloader words specifically, and not the gun nouns. "Pistol Kits" and
#: "Revolver Kits" are a surplus dealer's own way of advertising handguns --
#: "CZ 50/70 PISTOL KITS", "MAUSER C96 PISTOL KITS" -- and reading those as
#: kits to build turns three listings of handguns into boxes of parts. Nobody
#: writes "flintlock" or "sidelock" about a finished gun they are selling as a
#: gun; the words only turn up on the kits.
_MUZZLELOADER = re.compile(
    r"\b(?:flintlock|percussion|matchlock|caplock|sidelock|musket"
    r"|muzzle\s?load(?:er|ing|ers)?|black\s?powder)\b",
    re.I,
)

#: What is being sold as a kit, or a kit of something else entirely. A
#: flintlock rifle offered *with* a cleaning kit is a rifle.
_KIT = re.compile(r"\bkits?\b", re.I)
_KIT_OF_SOMETHING_ELSE = re.compile(
    r"\b(?:cleaning|clean|spare|repair|tool|nipple|maintenance|care|starter)\s+$", re.I
)


def _is_a_bayonet(title: str, description: str | None = None) -> bool:
    found = _BAYONET.search(title or "")
    if found is None:
        # A scabbard is the bayonet's sheath and belongs with them -- but the
        # word alone will not do it, because a scabbard is also what a rifle
        # rides in: "U.S. WWII M1 Carbine Leather Scabbard Holster" is a case
        # for the carbine. So the listing has to say bayonet somewhere.
        #
        # The description is read here and nowhere else in this module, and it
        # is safe for one reason: enrich() only asks this about a listing that
        # is already neither a rifle nor a handgun, so prose mentioning a
        # bayonet cannot take a rifle away from the rifles.
        return bool(_SCABBARD.search(title or "") and _BAYONET.search(description or ""))
    if _lacks(title, _BAYONET):
        return False
    return _COMES_WITH.search(title[: found.start()]) is None


def _is_a_parts_kit(title: str, category: str | None) -> bool:
    return bool(
        _PARTS_KIT.search(title or "")
        or _PARTS_KIT.search(category or "")
        or _is_a_muzzleloader_kit(title or "")
        or _DEMILLED.search(title or "")
    )


def _is_a_muzzleloader_kit(title: str) -> bool:
    """A muzzleloader offered as a kit to build rather than a gun to shoot."""
    if not _MUZZLELOADER.search(title):
        return False
    return any(
        not _KIT_OF_SOMETHING_ELSE.search(title[: found.start()]) for found in _KIT.finditer(title)
    )


#: The nouns that name a kind of gun outright, split the way the browse filter
#: splits them. Deliberately not the model designations: those live in
#: RIFLE_PATTERNS and PISTOL_PATTERNS and are the thing being checked.
_LONG_GUN_NOUN = re.compile(
    r"\b(?:rifles?|carbines?|muskets?|shotguns?|machine\s?guns?|combination\s+guns?)\b", re.I
)
_HANDGUN_NOUN = re.compile(r"\b(?:pistols?|revolvers?|handguns?)\b", re.I)


def stated_kind(title: str) -> str | None:
    """What the title's own words say it is: "rifle", "handgun", or nothing.

    Only when they settle it. A title naming both -- "Percussion Pistol
    Carbine" -- and a title naming neither both return None, because in
    either case the words are not an answer.

    This exists for the armory to check itself against. A model designation is
    not unique: "Model 1911" is a Colt and a Schmidt-Rubin, "Model 1917" is a
    Colt revolver and an Enfield rifle, "Model 1873" is a Winchester and a
    Colt. When a matched model disagrees with what the listing plainly says,
    the match is wrong -- not merely its kind, but its caliber and its maker
    too -- and it has to be discarded rather than trusted.
    """
    title_lower = (title or "").lower()
    # The nouns first, and they are authoritative. RIFLE_PATTERNS and
    # PISTOL_PATTERNS carry model designations as well as nouns, and a
    # designation is exactly what is in dispute here: "COLT MODEL 1917
    # REVOLVER" matches the rifle list on "model 1917" and the pistol list on
    # "revolver", which read as ambiguous and settled nothing -- when the
    # listing could hardly be plainer.
    if _HANDGUN_NOUN.search(title_lower) and not _LONG_GUN_NOUN.search(title_lower):
        return "handgun"
    if _LONG_GUN_NOUN.search(title_lower) and not _HANDGUN_NOUN.search(title_lower):
        return "rifle"

    # No noun, or both. Fall back to the full vocabulary, which still answers
    # for a title that names only a model: "Schmidt Rubin Model 1911 with
    # Matching Bayonet" says rifle by way of Schmidt-Rubin and nothing else.
    rifle = any(re.search(pattern, title_lower) for pattern in RIFLE_PATTERNS)
    pistol = any(re.search(pattern, title_lower) for pattern in PISTOL_PATTERNS)
    if rifle == pistol:
        return None
    return "rifle" if rifle else "handgun"


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
    # Inert rounds, sold for display and for function-checking, are handled by
    # _DEACTIVATED rather than here. That test outranks the vendor's category,
    # which this one does not, and it exempts a gun that has merely been made
    # safe -- an inert M2HB display is still an M2HB.
    r"\bwinter\s+trigger\b",
    r"\bscope\s+mount\b",
    r"\bfurniture\s+set\b",
    r"\bmonte\s+carlo\s+stock\b",
    r"\bhandguard\s+for\b",
    r"\brifle\s+bolts?\b",
    r"\bmanuals?\b",
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
    # --- Long guns a collector's dealer names by model alone ---------------
    #
    # Legacy Collectibles, CO Gun Sales and Centerfire Systems title a listing
    # the way the trade speaks: "ANIB FN SCAR 16S - Desert Camo", "Like-New
    # DSA SA 58 FALO", "Winchester Model 1873, .44-40 - 1882 mfg". Not one of
    # those says "rifle" anywhere, and without the model there was nothing in
    # the title to read, so every one of them was filed under parts and
    # accessories at four figures.
    #
    # Models, not makers: Colt, Winchester, Remington, Springfield, Beretta
    # and CZ all build both, so a bare maker decides nothing.
    r"\bscar\s?1[67]\w?\b",
    r"\bgalil\b",
    r"\bcetme\b",
    r"\bm1a\b",
    r"\bsp1\b",
    r"\bhbar\b",
    r"\bakm\b",
    r"\bsar-?\d\b",
    r"\bfalo?\b|\bsa\s?58\b",
    r"\bdraco\b",
    r"\bbren\b",
    r"\blebel\b",
    r"\bk\.?31\b|\bkar\s?31\b",
    r"\bstutzer\b",
    r"\bmas\s?mle\b",
    r"\bwinchester\s+(?:model\s+)?\d{2,4}\b",
    r"\bremington\s+(?:model\s+)?7\d{3}\b",
    r"\bmodel\s+1903\b|\b1903a\d\b",
    # A drilling and a combination gun are one gun with rifle and shotgun
    # barrels; a fowling piece and a blunderbuss are the older words for the
    # same class. All long guns, all filed here.
    # A machine gun is a long gun, and IMA sell deactivated ones at four
    # figures. There is no separate bucket for them, and "rifles" is where a
    # collector looks.
    r"\bmachine\s?guns?\b",
    r"\bdrilling\b",
    r"\bcombination\s+gun\b",
    r"\bfowling\s+piece\b",
    r"\bblunderbuss\b",
    # A gauge is a shotgun bore, and only a shotgun has one. Reached only
    # after the ammunition vetoes, so a box of shells does not come through
    # here as a firearm.
    r"\b(?:12|16|20|28|410)\s*(?:ga\b|gauge\b)",
)

PISTOL_PATTERNS = (
    r"\bpistols?\b",
    r"\brevolvers?\b",
    r"\bhandguns?\b",
    r"\bluger\b",
    r"\bmakarov\b",
    r"\bwalther\s+p\w*\b",
    r"\bberetta\s+(?:model\s+)?m?19\d{2}\b",
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
    # --- Handguns named by model alone, for the same reason -----------------
    r"\bglock\b",
    r"\bkimber\b",
    r"\bh&?k\s?\d+\b",
    r"\bxdm\b|\bxd-?s\b",
    r"\bwalther\s+model\s+\d+\b",
    r"\bmanurhin\b",
    r"\bintratec\b|\bab-?10\b",
    r"\btanfoglio\b|\bgt-?27\b",
    r"\bhammerli\b.{0,30}\bmodel\s+\d+\b",
    r"\bp\.?210\b",
    r"\bp\.?38\b",
    r"\bbrowning\s+m19\d\d\b",
    r"\bcz\s*(?:model\s*)?(?:27|38|46|50|52|75|82|83|85)\b",
    r"\batlas\s+gunworks\b",
    r"\bap-?5\b",
    # The German service revolvers, whose name is the word: a Reichsrevolver
    # is a revolver and nothing else is called one.
    r"\breichsrevolver\b",
    r"\bsmith\s*(?:&|and)\s*wesson\s+model\b",
    r"\bpepperbox\b",
    r"\bderringer\b",
    r"\bsingle\s+action\s+army\b|\bsaa\b",
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
    r"\b\.?38\s*super\b",
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

#: "gun" on its own is deliberately absent -- a prop gun, a gun cleaning kit
#: and a gun sling are all named with it -- but the compounds that can only be
#: a firearm are here.
_NAMES_A_FIREARM = re.compile(
    r"\b(?:rifles?|carbines?|muskets?|pistols?|revolvers?|handguns?|shotguns?"
    r"|machine\s?guns?|combination\s+guns?|flintlocks?|matchlocks?|wheel\s?locks?)\b",
    re.I,
)

#: The introducers that join two names rather than attach a part to a product.
#: "Garand *and* Springfield Scabbard" is one scabbard that fits two rifles;
#: "K98 Rifle *with* Bayonet" is a rifle that comes with one.
_JOINING_INTRO = re.compile(r"(?:and|&|,|plus)", re.I)

#: ...unless the listing says it has none. "Parts kit, no frame" is precisely
#: the thing that is *not* a firearm.
_NO_FRAME_PATTERN = re.compile(
    r"\b(?:no|without|less|minus|w/?o)\s+(?:the\s+)?(?:frames?|receivers?)\b", re.I
)


#: Category names that state the firearm type outright.
# "shotguns?" belongs here and was missing. The browse filter's split is long
# gun against handgun, not rifle against everything, and FirearmKind.SHOTGUN
# reports is_long_gun -- so a dealer's "Shotguns" section was the one type
# heading the classifier could read and did nothing with. SARCO file 73 of them
# there.
_CATEGORY_RIFLE = re.compile(r"\b(?:rifles?|carbines?|muskets?|shotguns?|long\s*guns?)\b", re.I)
_CATEGORY_PISTOL = re.compile(r"\b(?:handguns?|pistols?|revolvers?|sidearms?)\b", re.I)

#: A section that says "these are guns" without saying which kind. Read only
#: as a last resort -- see the end of classify_firearm().
_CATEGORY_FIREARM = re.compile(r"\b(?:firearms?|guns?)\b", re.I)

#: A category that is *only* a type word, with nothing else in it.
#:
#: The distinction this draws is between a section and a collection. SARCO's
#: "Pistols" holds pistols; IMA-USA's "M1 Garand & U.S. Rifles" holds anything
#: to do with an M1 Garand, slings and bayonets included -- which is why the
#: accessory vetoes outrank kind_from_category in general. A bare type word is
#: the case where they should not.
_CATEGORY_IS_ONLY_A_TYPE = re.compile(
    r"^\s*(?:handguns?|pistols?|revolvers?|rifles?|carbines?|shotguns?|muskets?"
    r"|long\s*guns?)\s*$",
    re.I,
)


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


#: An accessory named at the end and then said to be included: "Trainer Rifle,
#: .22 Long Rifle, 5 round magazine included". The rifle is the product.
#: Two nouns that can only name an accessory together, whatever comes after.
#: The head-noun rule needs nothing firearm-shaped to follow, which a title
#: like "BAR Magazine Belt - Browning Automatic Rifle" defeats by glossing its
#: own acronym at the end.
_ACCESSORY_COMPOUND = re.compile(
    r"\b(?:magazine|cartridge|ammunition|ammo)\s+"
    r"(?:belts?|bags?|pouch(?:es)?|bandol[ei]{1,3}rs?|cases?|boxes|box|carriers?)\b",
    re.I,
)

_INCLUDED = re.compile(r"\s*(?:is\s+|are\s+)?(?:included|incl\.?|come[sn]?\s+with)\b", re.I)

#: "for", "fits", "to suit" — everything after names what the part goes on.
_FITS = re.compile(r"\b(?:for|fits?|to\s+suit|suits?|used\s+(?:on|in|with))\b", re.I)


#: Accessory words the head-noun rule may be applied to.
#:
#: Deliberately not all of them, and the omissions are the point. "Barrel" and
#: "magazine" end a firearm's title constantly as *specifications* — "Swiss
#: K1911 Straight Pull Rifle 7.5x55 23.3in Barrel", "CZ82 Pistol 9x18 Makarov
#: 10 Round Magazine", "Colt Single Action Army Revolver with 4 3/4 barrel" —
#: and reading those as the product turned forty genuine firearms into
#: accessories the first time this rule ran against the catalog.
#:
#: What is left is the set that a dealer writes last only when it is what they
#: are selling.
_HEAD_NOUN_ACCESSORIES = re.compile(
    r"\b(?:slings?|scabbards?|holsters?|pouch(?:es)?|bandol[ei]{1,3}rs?|bayonets?"
    r"|bags?|covers?|pads?|hangers?|oilers?|handbooks?|manuals?"
    r"|tools?|keepers?|buckles?|frogs?|straps?|cases?|belts?|grips?|cartridges?"
    r"|barrels?|stocks?|handguards?"
    r"|cleaning\s+kits?|stripper\s+clips?|handguards?)\b",
    re.I,
)

#: Parts that end a firearm's title as a *specification* far more often than
#: they name a product: "Beretta Model 1934, .380 ACP, 3.5in Barrel, Fixed
#: Sights", "CZ75, 9MM, 16-Round Capacity, Square Sights". Reading those as the
#: product cost five pistols and two Swedish Mausers.
#:
#: They count as the head noun only in the one construction that settles it —
#: "Rear Sight **for** the M1903A1 Springfield Rifle" is a sight.
_HEAD_NOUN_IF_FITTED = re.compile(r"\b(?:sights?|clips?|springs?)\b", re.I)

#: A vocabulary word doing another job in the sentence. "Manual" in "Manual
#: Safety" is a control on a pistol; "Tool" in "by Victor Tool Company" is half
#: a maker's name. Both cost real firearms: three Classic Firearms pistols
#: whose spec list ends "Manual Safety - Surplus Good Condition".
#:
#: This has to be tested here rather than as a lookahead in the word lists
#: above, because those are matched with fullmatch() against the bare word --
#: a lookahead there only ever sees the end of the string, and always passes.
_ANOTHER_JOB = re.compile(
    r"[\s-]+(?:safet(?:y|ies)|compan(?:y|ies)|co\b|works\b|fed\b|harden)", re.I
)

#: What comes *before* the word, when that is what settles it. A presentation,
#: custom or hard case is sold with the firearm inside it -- "NIB Colt Dragoon
#: 3rd Model Signature Series - Presentation Case" is a revolver -- whereas a
#: carry case or a fleece-lined rifle case is the product.
_HOLDS_THE_FIREARM = re.compile(r"\b(?:presentation|custom|display|hard|fitted)\s+$", re.I)

#: The parts a dealer lists among a firearm's specifications.
#:
#: Two tiers, because they carry different risks. Grips and sights are hardly
#: ever sold loose here, so a model name before them is enough -- "ANIB Kimber
#: Micro 9 - Laser Grips" is a pistol. Barrels and stocks *are* sold loose, in
#: quantity, and "AK47 / AKM 16in Chrome Lined Barrels" is a box of barrels
#: however close the model name sits, so those need the firearm noun itself.
_SPECIFICATION_PART = re.compile(r"\b(?:grips?|sights?)\b", re.I)
_SPECIFICATION_PART_STRICT = re.compile(r"\b(?:barrels?|stocks?)\b", re.I)

#: A measurement immediately before the part, which is how a dealer writes a
#: specification and never how anybody names a product: "Straight Pull Rifle
#: 30.75in Barrel", "Revolver with 4 3/4in Barrel". Distance alone could not
#: tell those from "AK47 / AKM 16in Chrome Lined Barrels", where the same
#: measurement sits two adjectives further back and the barrels are the goods.
_MEASURED = re.compile(r"""[\d/.]+\s*(?:"|”|″|'|in\.?|inch(?:es)?|cm|mm)?[\s-]*$""")

#: How a dealer describes the barrel or stock a gun already has, rather than
#: one for sale on its own.
_FEATURE_QUALIFIED = re.compile(
    r"\b(?:threaded|ported|match|octagonal|octagon|bull|heavy|fluted|tapered|shrouded"
    r"|fixed|folding|fold|thumbhole|rejected|adjustable|collapsible"
    # How many barrels the gun has, which is a fact about the gun and not an
    # offer of a barrel: "KRICO SINGLE BARREL .22LR" and "HUSQVARNA SINGLE
    # BARREL .22LR" are rifles, and all three of these were filed under
    # accessories on the strength of the word "barrel".
    r"|single|double|twin|triple|over\s*/?\s*under|side\s+by\s+side)\s+$",
    re.I,
)

#: How far a part may sit from the firearm noun and still be the product.
#: "Colt Revolver Grips" is inside this; a spec list is not.
_SPEC_GAP = 6


#: Hyphen, en dash and em dash, as escapes: a dealer uses all three and they
#: are indistinguishable on the page.
_DASHES = (" - ", " \u2013 ", " \u2014 ")


def _last_dash(text: str) -> int:
    return max(text.rfind(dash) for dash in _DASHES)


def _first_dash(text: str) -> int:
    return min((at for at in (text.find(dash) for dash in _DASHES) if at != -1), default=-1)


def _is_a_specification(word: str, before: str) -> bool:
    """Whether a part word is describing a gun already named, not being sold.

    "Zastava M83 .357 Magnum Revolver 4 Inch Blued - Factory Wood Grips" is a
    revolver. A part sold on its own follows the name directly -- "Colt
    Revolver Grips" -- so what separates the two is the distance and the
    punctuation, not the order.

    Two tiers of vocabulary. For grips and sights a model name is enough,
    those being hardly ever sold loose in a surplus catalog. Barrels and
    stocks are sold loose in quantity, so those need the firearm noun itself:
    "AK47 / AKM 16in Chrome Lined Barrels" is a box of barrels, and its
    distance from "AK47" says nothing at all.
    """
    for part, vocabulary in (
        (_SPECIFICATION_PART, _NAMES_A_FIREARM_OR_MODEL),
        (_SPECIFICATION_PART_STRICT, _NAMES_A_FIREARM),
    ):
        if not part.fullmatch(word):
            continue
        # Singular only. A gun has one barrel, so "Micro Galil .223 8in
        # Barrel" is describing one; a listing selling them says "AK47 / AKM
        # 16in BARRELS" and means a box.
        if _MEASURED.search(before) and not word.endswith("s"):
            return True
        if _FEATURE_QUALIFIED.search(before):
            return True
        # A dash sets off what a dealer adds about a gun they have already
        # named: "Winchester Model 1873 - Octagonal Barrel", "Kimber Micro 9 -
        # Laser Grips", "Target Rifle - Hammerli Barrel". The model name
        # counts for both tiers here, the dash being the evidence.
        dash = _last_dash(before)
        if dash != -1 and _NAMES_A_FIREARM_OR_MODEL.search(before[:dash]):
            return True
        named = list(vocabulary.finditer(before))
        if named and len(before.rstrip()) - named[-1].end() > _SPEC_GAP:
            return True
    return False


def _what_follows(title_lower: str, found: re.Match[str]) -> str:
    """The part of the title that is still evidence about the head noun.

    A firearm named after "for" is what the part fits rather than what is on
    offer, and so is one after a colon or a dash: "Rear Sight *for* the
    M1903A1", "Handbook: U.S. .30 M1 Garand", "Allin Conversion Sling Made
    from Civil War Slings - M1868 Trapdoor Springfield". Each of those is the
    accessory, and the rest of the title says which gun it belongs to.
    """
    after = title_lower[found.end() :]
    fits = _FITS.search(after)
    if fits is not None:
        after = after[: fits.start()]
    if after.lstrip().startswith(":"):
        return ""
    tail = _first_dash(after)
    return after[:tail] if tail != -1 else after


def _is_a_list_entry(before: str, rest: str) -> bool:
    """Whether the word is one entry in a spec list rather than the head.

    "Bolt Action, Bayonet, Exc Cond, Ser # M40829" and "All Matching, Rare
    Handguard, As New" describe a rifle; an entry in a list like that is a
    comma, a word or two, the noun, and a comma. The last entry has no comma
    after it to give it away -- "JRA Gallant Rifle, 5.56 NATO, 18in BBL, ...,
    30 Rd Mag, Rifle Case" is a rifle sold with a case -- so the punctuation
    of the whole title stands in for the missing one. Three commas, not two,
    because "Boyle, Gamble, & McFee Bayonet Adapter" is a maker's name.

    Dashes make the same list, and some vendors prefer them: "Smith & Wesson
    Model 30-1 - .32 Long - Pachmayr Grips - 4 Inch Barrel - 1969 C&R" is a
    revolver whose third entry happens to be its grips. Three separators
    again, and only spaced ones, so the hyphen inside "30-1" is not one.
    """
    if _spaced_dashes(before) + _spaced_dashes(rest) >= 3:
        return True
    comma = before.rfind(",")
    if comma == -1 or len(before) - comma > _LIST_ENTRY:
        return False
    return rest.lstrip().startswith(",") or before.count(",") >= 3


def _spaced_dashes(text: str) -> int:
    return sum(text.count(dash) for dash in _DASHES)


def _is_the_head_noun(title_lower: str, found: re.Match[str]) -> bool:
    """Whether this accessory word is what the listing is actually selling.

    English puts the head noun last: "M1 Garand Rifle 1907 Pattern Leather
    Sling" is a sling, and the rifle only says what it fits. The rule that read
    whichever came *first* got this exactly backwards on nineteen IMA-USA
    slings, twenty-seven bayonets and nine boxes of dummy cartridges, all of
    which arrived as rifles — because those dealers name the firearm first as a
    matter of course.

    So: nothing that names a firearm may follow it. "Springfield Rifle Musket
    with Sling" does not reach here at all — the bundled phrase is removed
    before the vetoes read the title — and an accessory that is explicitly
    *included* is excluded here, which is what tells a rifle sold with a
    magazine from a magazine sold on its own.
    """
    word = found.group(0)
    fitted = _FITS.search(title_lower[found.end() :]) is not None
    if not _HEAD_NOUN_ACCESSORIES.fullmatch(word) and not (
        fitted and _HEAD_NOUN_IF_FITTED.fullmatch(word)
    ):
        return False
    # One entry in a list of a rifle's features — "Bolt Action, Bayonet, Exc
    # Cond, Ser # M40829", "All Matching, Rare Handguard, As New" — rather than
    # the thing being sold. A head noun does not have a feature list after it,
    # and an entry in one is a comma, a word or two, the noun, and a comma.
    before = title_lower[: found.start()]
    if _HOLDS_THE_FIREARM.search(before):
        return False
    if _is_a_specification(word, before):
        return False
    if _is_a_list_entry(before.rstrip(), title_lower[found.end() :]):
        return False
    rest = title_lower[found.end() :]
    if _ANOTHER_JOB.match(rest) or _INCLUDED.match(rest):
        return False
    after = _what_follows(title_lower, found)
    return not (_NAMES_A_FIREARM_OR_MODEL.search(after) or _FRAME_PATTERN.search(after))


def _accessory_leads(title_lower: str) -> bool:  # noqa: PLR0911 - each return is
    #                          one way a title can name a part without selling it
    """Whether the title offers an accessory rather than a firearm with one.

    "Leather sling for a Mauser rifle" and "Mosin Nagant rifle with sling" both
    name an accessory and a firearm; the difference is the order. A listing is
    titled for the thing being sold, so whichever comes first is the thing.
    """
    accessory = _BUNDLED_ACCESSORY.search(title_lower)
    if not accessory:
        return False

    # A part the title is using to describe the gun is not the thing being
    # sold, wherever in the sentence it sits. Order is the rule here and this
    # is the exception to it: "KRICO SINGLE BARREL .22LR" is a single-barrel
    # rifle, and reading the barrel as the product because nothing precedes it
    # filed three of them under accessories.
    if _is_a_specification(accessory.group(0), title_lower[: accessory.start()]):
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
    if (
        named
        and named[-1].end() == len(before)
        # ...unless a gun follows it too. "Erma Luger Magazine" is a magazine,
        # but "Matched Pair of Franco-Flemish Flintlock Holster Pistols" is a
        # pair of pistols, and only what comes after tells them apart.
        and not _NAMES_A_FIREARM_OR_MODEL.search(_what_follows(title_lower, accessory))
    ):
        return True
    # A frame or a receiver counts as the thing being sold here for the same
    # reason it survives the price floor: it is the serialized part, so a
    # listing that leads with one is selling a firearm even though it has not
    # used the word.
    # A model name counts here, not only a common noun. "Glock G23 Gen 4
    # .40cal Semi-Auto 4in Barrel Fixed Sights Factory Handgun" names its
    # barrel a third of the way in and its type at the end, and reading only
    # the noun put the barrel first and sold a handgun as a spare part.
    firearm_at = [
        match.start()
        for match in (
            _NAMES_A_FIREARM_OR_MODEL.search(title_lower),
            _FRAME_PATTERN.search(title_lower),
        )
        if match is not None
    ]
    if not firearm_at:
        return True
    # Order alone used to settle it here, on the reasoning that a listing is
    # titled for the thing being sold. That reads "Original U.S. Pennsylvania
    # Over & Under Double Barrel .44 Caliber Swivel Breech Percussion Rifle"
    # as a barrel, and "Matched Pair of Franco-Flemish Flintlock Holster
    # Pistols" as a holster, because those dealers put the part word early as
    # a description. The head-noun test below reaches the same answer on the
    # cases order was protecting -- "Leather sling for a Mauser rifle" stops
    # being evidence at "for" -- and the right one on these.
    if _FRAME_PATTERN.search(title_lower):
        # A frame, a receiver or a barrelled action is the serialized part, so
        # the listing is selling a firearm however it goes on to describe it.
        # "Berthier barreled action, shortened barrel" ends in an accessory
        # word and is not an accessory.
        return False
    # Named after the firearm, but with nothing firearm-shaped after it, so it
    # is the thing on offer rather than the thing it fits.
    return _is_the_head_noun(title_lower, accessory)


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
#: The vocabulary of things that are carried, worn, fitted or read — never the
#: firearm itself. Used both for stripping a part a listing comes with and, in
#: the head-noun test below, for spotting the part it is selling.
_ACCESSORY_NOUN = re.compile(
    r"\b(?:bayonets?|scabbards?|slings?|holsters?|magazines?|mags?|pouch(?:es)?"
    r"|ammo|ammunition|cases?|boxes|box|bipods?|clips?|bags?|covers?|pads?"
    r"|hangers?|oilers?|belts?|handbooks?|manuals?|sights?|tools?|keepers?|grips?"
    r"|cartridges?"
    r"|barrels?|stocks?|handguards?|scopes?"
    r"|buckles?|frogs?|straps?|bandol[ei]{1,3}rs?)\b",
    re.I,
)

#: What joins one attached part to the next: "with Two Magazines, Holster & Box".
#: Stripping only the first left ", holster & box" behind, and a holster at the
#: end of a title looks exactly like a holster for sale.
_ALSO = re.compile(r"^\s*(?:[,&+]|and|plus)\s*", re.I)

#: How far back a list entry's own comma may be: room for an adjective or two,
#: not for a clause.
_LIST_ENTRY = 26

#: What introduces a part the listing merely comes with, or without.
#: "and" is kept despite being ambiguous. It joins two things as readily as it
#: introduces one — "Garand *and* Springfield Scabbard Replacement Body" is a
#: scabbard for two rifles, and reading that "and" as an introducer strips the
#: scabbard away and leaves a Garand. Removing it costs more than it saves:
#: "New Barrel *and* Free Holster" then reads as a holster for sale, and that
#: shape is the commoner of the two. One scabbard is filed as a rifle for it.
_ATTACHED_INTRO = re.compile(
    r"\b(?:with|w/|w|no|without|w/o|less|minus|missing|sans|plus|and|incl(?:udes|uding)?"
    r"|(?:numbers[\s-]?)?matching|original|correct)\b"
    r"|(?<![\d.×x-])\b\d{1,2}\b(?![\d.×x\"”″'])|\+",
    re.I,
)

#: How much may sit between the introducer and the part: "w / Matching # "
#: is fourteen characters of adjectives and punctuation, and enumerating those
#: adjectives is what missed "with Spike Bayonet" the first time.
_ATTACHED_GAP = 26


def _without_attached_parts(title_lower: str) -> str:
    """The title with "w/ bayonet" and "no bayonet" taken out of it.

    The gap between the introducer and the part may hold adjectives and
    punctuation but never a firearm noun. Without that last rule "Springfield
    Trapdoor **and** Krag **Rifle** Leather **Sling**" reads as a rifle that
    comes with a sling, when it is a sling that fits two rifles.
    """
    out, cursor = [], 0
    for part in _ACCESSORY_NOUN.finditer(title_lower):
        window = title_lower[max(cursor, part.start() - _ATTACHED_GAP) : part.start()]
        # The last introducer in the window, so "w/ Ramrod Bayonet" is found
        # past the adjective rather than only when it sits flush against it.
        # The nearest introducer that actually reaches the part, working
        # back: a count introduces the part it counts and nothing further off,
        # so "Mark 1 Plastic Training Bayonet" is a bayonet rather than a Mark
        # that comes with one -- while "Pistol 2 Magazines" is a pistol.
        intro = gap = None
        for candidate in reversed(list(_ATTACHED_INTRO.finditer(window))):
            behind = window[candidate.end() :]
            if candidate.group(0).isdigit() and len(behind.split()) > 1:
                continue
            intro, gap = candidate, behind
            break
        if intro is None or gap is None:
            continue
        # A conjunction reaching another gun is the second entry in a list of
        # what the part fits, not an attachment: "Springfield Trapdoor *and*
        # Krag Rifle Leather Sling" is a sling for both, and "Garand *and*
        # Springfield Scabbard Replacement Body" is a scabbard body -- reading
        # that one the other way left "Garand replacement body" behind and
        # sold it as a rifle.
        #
        # Conjunctions only. "w/" and "with" genuinely attach, and applying
        # this to them read "Cape Combination *Gun* with *Rifle* & Shotgun
        # Barrels" as a pair of barrels rather than the gun that has them.
        if _JOINING_INTRO.fullmatch(intro.group(0).strip()) and (
            _NAMES_A_FIREARM.search(gap) or _NAMES_A_MAKER.search(gap)
        ):
            continue
        intro_at = part.start() - (len(window) - intro.start())
        # An introducer at the very start of the title attaches the part to
        # nothing -- there is no product before it to come *with* anything.
        # IMA-USA open every listing with "Original", so this read the head
        # off "Original U.S. WWII Rear Sight for the M1903A1", left behind
        # "for the M1903A1 Springfield Rifle", and sold a sight as a rifle.
        if intro_at == 0 and cursor == 0:
            continue
        out.append(title_lower[cursor : part.start() - (len(window) - intro.start())])
        cursor = part.end()
        # And the rest of the list it heads: "Magazines, Holster & Box".
        while True:
            joined = _ALSO.match(title_lower[cursor:])
            if joined is None:
                break
            rest = cursor + joined.end()
            nxt = _ACCESSORY_NOUN.match(title_lower[rest:])
            if nxt is not None:
                cursor = rest + nxt.end()
                continue
            # Allow one adjective: "& Leather Pouch".
            spaced = re.match(r"\w+\s+", title_lower[rest:])
            if spaced is None:
                break
            nxt = _ACCESSORY_NOUN.match(title_lower[rest + spaced.end() :])
            if nxt is None:
                break
            cursor = rest + spaced.end() + nxt.end()
    out.append(title_lower[cursor:])
    return " ".join("".join(out).split())


def _too_cheap_to_be_one(title_lower: str, price: float | None) -> bool:
    """Below the floor, and nothing in the title says otherwise."""
    return (
        price is not None
        and price < MIN_FIREARM_PRICE
        and not _is_a_bare_frame(title_lower)
        and not _NAMES_A_FIREARM.search(title_lower)
    )


#: The phrases allowed to outrank the vendor's own category.
#:
#: A short list on purpose, and much shorter than NON_FIREARM_PATTERNS. That
#: one holds entries like `\bgrips\b`, which is fine as a tie-breaker further
#: down and is not fine here: "Colt Model 1849 Pocket Revolver - Inscribed &
#: Real Ivory Grips" and "Kimber Micro 9 - Laser Grips" are both firearms, and
#: promoting the whole list above the category turned them into accessories.
#: The category had been quietly rescuing them all along.
#:
#: Everything here names the product outright and cannot describe a firearm.
_NEVER_A_FIREARM = (
    r"\bparts\s*kits?\b",
    r"\bcleaning\s+kits?\b",
    r"\bbandoli?ers?\b",
    r"\bammo\b",
    r"\b80\s*%",
)

#: Deactivated, inert, or made to look like a gun without being one.
#:
#: Conditional, unlike the list above, because the same words cover two very
#: different things. "Set of 8 Dummy .30-06 Cartridges in M1 Garand En-Bloc
#: Clip" is a box of cartridges. "Inert Display Machine Gun Built with
#: Original USGI Parts" is a deactivated M2HB at $9,995, and a collector
#: watching for one wants to see it under guns rather than under parts.
#:
#: So these veto only when the title is not *named* as a gun -- see
#: :func:`_is_gun_shaped`. That keeps IMA-USA's Mini-14 "Non-Firing Prop Gun"
#: out, which says prop gun and never says rifle, while letting through the
#: "Non-Firing Training Rifle" and the "Non-Firing Miniature Replica
#: Revolver" beside it.
#:
#: A *drill* rifle was never here at all. Those are real rifles with the
#: chamber welded, several vendors sell them as surplus, and somebody watching
#: for an Enfield No4 wants to see one.
_DEACTIVATED = (
    r"\bdummy\b|\binert\b|\bsnap\s*caps?\b",
    r"\bnon[- ]?firing\b|\bnonfiring\b",
    (
        r"\b(?:rubber|resin|plastic|replica|wood(?:en)?|movie|film|theatrical)"
        r"(?:\s+\w+){0,2}?\s+props?\b"
    ),
)

#: Words that name a product on their own, and describe a gun when one has
#: already been named.
#:
#: Conditional for that reason. "Single Action Revolver Grouping - As Featured
#: In The Story of Merwin, Hulbert & Co. Firearms Book" is a $8,295 revolver
#: grouping; "Flintlock Pistol with Grotesque Mask Butt Cap" is a pistol; and
#: "Inert Display Machine Gun Built with Original USGI Parts, Pintle and M3
#: Tripod" is a machine gun that comes on its tripod. A listing that names no
#: gun before the word -- "HAND WOVEN EXTRA LARGE VAQUERO BLANKETS",
#: "Reference book, Mauser rifles" -- is what these are for.
_NOT_THE_TRADE = (
    r"\btripod\b",
    r"\bblankets?\b",
    r"\bshirts?\b",
    r"\bhats?\b",
    r"\bcaps?\b",
    r"\bposters?\b",
    r"\bbooks?\b",
    r"\bpatch(?:es)?\b",
    r"\bmedals?\b",
)


def _is_other_merchandise(title_lower: str) -> bool:
    """Whether one of the :data:`_NOT_THE_TRADE` words is the thing on sale.

    The gun has to be named *before* the word, which is what separates
    "Single Action Revolver Grouping - As Featured In The Story of Merwin,
    Hulbert & Co. Firearms Book" from "Reference book, Mauser rifles". Both
    name a book and a gun; only in the first is the gun the product, and only
    in the first does it come first. The order matters here and nowhere else
    in this file because these are nouns competing to be the head, rather than
    the adjectives that :data:`_DEACTIVATED` holds.
    """
    for pattern in _NOT_THE_TRADE:
        found = re.search(pattern, title_lower)
        if found is None:
            continue
        named_first = _NAMES_A_FIREARM.search(title_lower[: found.start()]) is not None
        if not (named_first and _is_gun_shaped(title_lower)):
            return True
    return False


def _is_gun_shaped(stripped: str) -> bool:
    """Whether the title names a gun as the thing it is selling.

    A firearm noun, with no accessory sitting in the head-noun position after
    it. That is the whole of it: the point is to tell "Non-Firing Training
    *Rifle*" and "Inert Display Machine *Gun*" -- both guns, both deactivated
    -- from "Non-Firing Prop Gun" and "Dummy .30-06 *Cartridges*", which are
    not named as guns at all.
    """
    if not _NAMES_A_FIREARM.search(stripped):
        return False
    candidates = list(_ACCESSORY_NOUN.finditer(stripped))
    candidates += list(_BUNDLED_ACCESSORY.finditer(stripped))
    return not any(_is_the_head_noun(stripped, found) for found in candidates)


def _definitely_not_a_firearm(title_lower: str) -> bool:
    """The half of the accessory test that outranks the vendor's category.

    Two signals, both about what the title *says* rather than what it merely
    mentions: a phrase that can only name a part, and an accessory sitting
    where English puts the thing being sold — last, with nothing firearm-shaped
    after it.
    """
    stripped = _without_attached_parts(title_lower)
    if any(re.search(pattern, stripped) for pattern in _NEVER_A_FIREARM):
        return True
    if _ACCESSORY_COMPOUND.search(stripped):
        return True
    if any(re.search(pattern, stripped) for pattern in _DEACTIVATED) and not _is_gun_shaped(
        stripped
    ):
        return True
    if _FRAME_PATTERN.search(stripped) and not _NO_FRAME_PATTERN.search(stripped):
        return False
    # Every accessory noun in the title, not just the first. "PSYOP Chieu Hoi
    # Magazine Bag" leads with "magazine", which is a specification here and
    # not the head -- and testing only that one missed the "bag" that is.
    candidates = list(_ACCESSORY_NOUN.finditer(stripped))
    candidates += list(_BUNDLED_ACCESSORY.finditer(stripped))
    return any(_is_the_head_noun(stripped, found) for found in candidates)


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
    # A part the listing says it comes with — or without — is not evidence
    # about what is being sold, so it goes before every test rather than after
    # the first one. "Marlin 444S w/ Ammo" was tripping the bare `ammo` veto.
    title_lower = _without_attached_parts(title_lower)

    if any(re.search(pattern, title_lower) for pattern in NON_FIREARM_PATTERNS):
        return True
    if _is_other_merchandise(title_lower):
        return True

    if _is_a_standalone_part(title_lower):
        return True
    if _accessory_leads(title_lower):
        return True

    return _looks_like_accessory(title_lower)


def _is_a_standalone_part(title_lower: str) -> bool:
    """Bayonets, magazines and bolts, sold on their own rather than fitted.

    All three appear in a firearm's own title as often as they head a listing,
    so only the standalone case may be filtered out. A bayonet is the product
    when it is the head noun, not merely when the title avoids the word
    "rifle" — "M1 Garand Rifle Bayonet (M-1942)" says rifle and is a bayonet.
    """
    blade = _BAYONET.search(title_lower)
    if blade is not None and _is_the_head_noun(title_lower, blade):
        return True
    # The model vocabulary, not the FIREARM_WORDS list, which does not know
    # "CZ82 9x18 Makarov - 12RD Magazine". A magazine sold on its own is
    # still caught: "East German Luger Magazine" puts the part flush against
    # the name, which _accessory_leads reads as the part being the product.
    if (
        re.search(r"\bmagazine\b", title_lower)
        and not re.search(r"\bwith\s+magazine\b", title_lower)
        and not _NAMES_A_FIREARM_OR_MODEL.search(title_lower)
    ):
        return True
    # _lacks rather than a bespoke "without bolt": a rifle described by what is
    # missing is still a rifle, and the dealer writes that half a dozen ways.
    # "Romanian UMC Cugir - No Bolt" was filed under accessories because this
    # knew only "without" and "w/o".
    return (
        _BOLT.search(title_lower) is not None
        and not _lacks(title_lower, _BOLT)
        and not any(word in title_lower for word in FIREARM_WORDS)
    )


#: Designations whose type cannot be read from the words themselves, each one
#: here because somebody who knows the trade said so. This is the place for
#: facts about the market rather than facts about English, and it is expected
#: to grow.
KNOWN_DESIGNATIONS: tuple[tuple[str, bool, bool], ...] = (
    # "Govt 1911" and "Government Model" are the Colt automatic. A bare "1911"
    # is not enough on its own -- the Schmidt-Rubin Model 1911 is a rifle, and
    # the armory refuses that designation for exactly this reason -- but the
    # word in front of it settles which one a dealer means.
    (r"\bgov(?:'?t|ernment)\b[\s,-]*(?:model\s*)?1911\b", False, True),
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


def classify_firearm(  # noqa: PLR0911 - one return per rule class; a single
    #                        exit would mean a mutable answer threaded through
    #                        every veto, which is harder to read, not easier
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

    # A category names the *section*, not the item: IMA-USA file their slings,
    # bayonets and dummy cartridges under "M1 Garand & U.S. Rifles", because
    # that is what those things are for. So the confident half of the accessory
    # test goes first — a title that says outright it is a part, or that ends
    # in the part it is selling.
    #
    # Only the confident half. The rest of that test fires on "Winchester Model
    # 1873 - Octagonal Barrel" and "Swiss K31 Carbine Rifle w/ Matching
    # Bayonet", and the category is what has been quietly rescuing those.
    stated = kind_from_category(category)
    if stated is not None and _CATEGORY_IS_ONLY_A_TYPE.match(category or ""):
        # A section named for nothing but a type outranks even the confident
        # accessory test. Two listings in SARCO's "Pistols" were being read as
        # parts because of a word inside them: "Hungarian FEG Hi Power -
        # Plastic Grips" describes its grips, and "FRANZ STOCK TYPE 1" is a
        # maker whose surname is a gun part.
        return stated

    if _definitely_not_a_firearm(title_lower):
        return (False, False)

    if stated is not None:
        return stated

    haystack = f"{title or ''} {description or ''}".lower()

    if _is_not_a_firearm(title_lower) or _too_cheap_to_be_one(title_lower, price):
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
            # Still a firearm. Reaching here means the title named a rifle as
            # well, and the caliber has just said which of the two it is:
            # "Springfield Model 1855 Percussion Pistol Carbine" in .58 is a
            # carbine. Leaving it at neither filed two of them under parts.
            is_rifle = True

    if not (is_rifle or is_pistol) and _CATEGORY_FIREARM.search(category or ""):
        # Last resort, and only ever from neither-of-the-two.
        #
        # A dealer's generic firearms section -- "Shop All Firearms", "Firearms
        # & Ammunition" -- says the thing IS a gun without saying which kind.
        # Nothing else here reads that, so a title naming a maker, a
        # designation and a caliber and no gun noun at all fell through to
        # accessories: "SAVAGE 4C .22LR", "JARMANN 1883 10.15 x 61R",
        # "ANSCHUTZ MODEL 525 .22 LR". Eighteen of them in one SARCO scan.
        #
        # Placed *after* the accessory vetoes and the price floor rather than
        # beside kind_from_category, which is deliberate and is the whole of
        # its safety: it can only rescue a listing that every other rule has
        # already declined to call anything, so it cannot promote a sling out
        # of a shop's "Guns" section.
        #
        # The caliber splits it, because the category will not. A cartridge
        # only ever chambered in handguns says handgun; anything else is the
        # long gun that a surplus dealer's general section is mostly made of.
        return _kind_from_caliber(caliber)

    return (is_rifle, is_pistol)


def _kind_from_caliber(caliber: str | None) -> tuple[bool, bool]:
    """Long gun or handgun, on the cartridge alone. Used only as a last resort."""
    if caliber and any(re.search(p, caliber.lower()) for p in PISTOL_CALIBERS):
        return (False, True)
    return (True, False)


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


#: Any maker in the table above, as one alternation.
#:
#: Built from the table rather than beside it, so a maker added there is a
#: maker everywhere. Used by _without_attached_parts(), which runs long before
#: this point in the file but only ever at call time.
_NAMES_A_MAKER = re.compile(
    "|".join(f"(?:{pattern})" for pattern, _ in MANUFACTURER_PATTERNS), re.I
)


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

    # A parts kit is not a complete firearm, so it does not also count as one.
    # The same deference is_bayonet has always shown, and for the same reason:
    # the browse filter's five buckets are meant to partition the catalog, and
    # a listing in two of them is counted twice and read as whichever the
    # filter happens to ask about first. A Czech ZB37 heavy machine gun sold as
    # a kit was showing under Rifles.
    is_kit = _is_a_parts_kit(title, category)
    if is_kit:
        is_rifle = is_pistol = False
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
        "is_bayonet": not (is_rifle or is_pistol) and _is_a_bayonet(title, evidence),
        "is_parts_kit": is_kit,
    }
