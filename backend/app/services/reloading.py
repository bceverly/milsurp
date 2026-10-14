"""What it costs to reload one round: bullet, new brass, powder and primer.

Asked for on 2026-10-14, alongside the bullet prices the caliber data already
had ("something along the lines of our reloading bullets"). Four parts, two
kinds of fact:

* **Prices, read on the caliber data's schedule** from Graf & Sons, the shop
  the bullets already come from -- the same public product feeds, the same
  pace. New brass per case (``collections/rifle-brass`` and
  ``handgun-brass``), primers per primer (``primers``), powder per pound
  (``smokeless-powder`` and ``black-powder``).
* **Facts of the cartridge, kept once**: the primer it takes, read from its
  Wikipedia article's infobox (``primer=Large rifle``) and correctable by
  hand; and the load -- which powder and how many grains, for which bullet
  weight -- entered by hand. Load data was to come from loaddata.com, whose
  disclaimer allows its documents "for informational and non-commercial or
  personal use only" and says they "will not be copied or posted on any
  network computer"; a site with other readers is that, so the load is
  whatever its administrator looks up and enters.

**New brass only.** Graf sells fired, reconditioned and pulled-down cases
too, and primed ones; a reloading cost counts a new, empty case, so those are
left out -- a primed case would count its primer twice.
"""

from __future__ import annotations

import html as htmlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ArmoryStatus, Caliber, ReloadingSupply
from ..scrapers.base import ScrapeContext, ScrapeError
from . import armory

GRAFS = "https://grafs.com/"
BRASS_COLLECTIONS = ("rifle-brass", "handgun-brass")
PRIMER_COLLECTIONS = ("primers",)
POWDER_COLLECTIONS = ("smokeless-powder", "black-powder")
#: Pages of 250 read at most from one collection: rifle brass was 965.
PAGES = 12
GRAINS_PER_POUND = 7000.0

#: The primer sizes, as the infobox and the shops write them.
SMALL_PISTOL = "Small pistol"
LARGE_PISTOL = "Large pistol"
SMALL_RIFLE = "Small rifle"
LARGE_RIFLE = "Large rifle"
BMG = ".50 BMG"
SHOTSHELL = "209 shotshell"
BERDAN = "Berdan"
PRIMER_SIZES = (SMALL_PISTOL, LARGE_PISTOL, SMALL_RIFLE, LARGE_RIFLE, BMG, SHOTSHELL, BERDAN)

# -- Reading a Graf & Sons title ------------------------------------------------
_COUNT = re.compile(
    r"\b(?:bag|box|jug|case|pack|tray|bucket)\s+of\s+([\d,]+)\b"
    r"|\b([\d,]+)\s*/\s*(?:bx|box|bag|bg|ct|pk|cs|case)\b"
    r"|\bper\s+([\d,]+)\b"
    r"|\b([\d,]+)\s*(?:ct|count|pcs)\b",
    re.I,
)
#: Not a new, empty case: fired or cleaned up, a blank or a dummy, primed, or
#: "Basic" -- a parent case to be formed into the one it names.
_NOT_NEW_BRASS = re.compile(
    r"\b(?:once[\s-]*fired|fired|reconditioned|processed|range|blank|dummy|snap|"
    r"pull[\s-]*down|(?<!un)primed|basic)\b",
    re.I,
)
#: Makers whose brass is fired brass cleaned up for sale.
_RECONDITIONED_VENDORS = ("lightning",)
_BRAND_WORDS = re.compile(
    r"^(?:peterson(?:\s+cartridge)?|prvi(?:\s+partizan)?|ppu|starline|hornady|nosler|"
    r"winchester|lapua|norma|weatherby|quality\s+cartridge|graf\s*&\s*sons|graf|"
    r"alpha(?:\s+munitions)?|remington|federal(?:\s+premium)?|bertram|sig\s+sauer|"
    r"top\s+brass|jagemann|fiocchi|sellier\s*&\s*bellot|igman|atlas|gunwerks|"
    r"lightning|adg|hsm|pmc|frontier|cbc|magtech|aguila)\s+",
    re.I,
)


def _count(title: str) -> int:
    found = _COUNT.search(title)
    if not found:
        return 0
    digits = next(group for group in found.groups() if group)
    return int(digits.replace(",", ""))


def _price(text: Any) -> float | None:
    found = re.search(r"[\d,]+(?:\.\d+)?", str(text or ""))
    return float(found.group(0).replace(",", "")) if found else None


def _cheapest(product: dict[str, Any]) -> float | None:
    prices = [
        p
        for variant in product.get("variants") or []
        if variant.get("available")
        for p in [_price(variant.get("price"))]
        if p
    ]
    return min(prices) if prices else None


def _url(product: dict[str, Any]) -> str | None:
    handle = product.get("handle")
    return urljoin(GRAFS, f"products/{handle}") if handle else None


def brass_caliber_text(title: str) -> str:
    """The caliber a brass title names: "Starline 45-70 Gov't Brass Bag of 100"
    is "45-70 Gov't", "LAPUA BRASS 220 RUSSIAN UNPRIMED 100/box" "220 RUSSIAN"."""
    text = htmlib.unescape(title).strip()
    text = re.sub(r"\bnew\b", " ", text, flags=re.I)
    while True:
        stripped = _BRAND_WORDS.sub("", text, count=1)
        stripped = re.sub(r"^brass\s+", "", stripped, flags=re.I)
        if stripped == text:
            break
        text = stripped
    text = re.split(
        r"\s+(?:nickel[\s-]*plated\s+)?(?:brass|cases?|unprimed|nickel)\b"
        r"|\s+(?:bag|box|jug|case|per)\b|\s+\d+\s*/",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    return " ".join(text.split()).strip(" -,")


@dataclass(frozen=True)
class Brass:
    caliber_text: str
    price: float
    count: int
    url: str | None

    @property
    def each(self) -> float:
        return self.price / self.count


def grafs_brass(products: Iterable[dict[str, Any]]) -> list[Brass]:
    """New, empty, in-stock cases: one :class:`Brass` per product."""
    found = []
    for product in products:
        title = htmlib.unescape(str(product.get("title") or ""))
        vendor = str(product.get("vendor") or "").lower()
        if _NOT_NEW_BRASS.search(title) or vendor.startswith(_RECONDITIONED_VENDORS):
            continue
        count, price = _count(title), _cheapest(product)
        name = brass_caliber_text(title)
        if count >= 10 and price and name:
            found.append(Brass(name, price, count, _url(product)))
    return found


@dataclass(frozen=True)
class Primer:
    size: str
    magnum: bool
    price: float
    count: int
    url: str | None

    @property
    def each(self) -> float:
        return self.price / self.count


def primer_kind(text: str) -> tuple[str | None, bool]:
    """A primer's size and whether it is a magnum, from a shop's title or an
    infobox: "CCI #450 Small Rifle Magnum Primers", "Large pistol LP (some
    makers are now using small pistol SP)", "Berdan or boxer large rifle"."""
    lowered = text.lower()
    magnum = bool(re.search(r"\bmagnum\b|\bmag\b", lowered))
    if re.search(r"\b209\b|shotshell|shotgun", lowered):
        return SHOTSHELL, magnum
    if re.search(r"\.?50\s*bmg|\b#?35\b", lowered):
        return BMG, magnum
    # The first size named: "Large pistol LP (some makers ... small pistol SP)"
    # is a large pistol. "5.56mm NATO-Spec Small Rifle" is a small rifle.
    sized = re.search(r"\b(small|large)\s+(pistol|rifle)\b", lowered)
    if sized:
        return f"{sized.group(1).capitalize()} {sized.group(2)}", magnum
    if re.search(r"\bberdan\b", lowered):
        return BERDAN, magnum
    return None, magnum


def grafs_primers(products: Iterable[dict[str, Any]]) -> list[Primer]:
    found = []
    for product in products:
        title = htmlib.unescape(str(product.get("title") or ""))
        if re.search(r"\bmuzzleloader\b|\bcaps?\b|\btray\b", title, re.I):
            continue
        size, magnum = primer_kind(title)
        count, price = _count(title), _cheapest(product)
        if size and size != BERDAN and count >= 100 and price:
            found.append(Primer(size, magnum, price, count, _url(product)))
    return found


@dataclass(frozen=True)
class Powder:
    name: str
    pounds: float
    price: float
    url: str | None
    #: False for a title in capitals, whose name was re-cased.
    as_written: bool = True

    @property
    def per_pound(self) -> float:
        return self.price / self.pounds


_POWDER_WEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*(lb|lbs|pound|pounds|oz|ounces?|kg)\b", re.I)


def _shouting(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and all(ch.isupper() for ch in letters)


def powder_name(title: str) -> str:
    """The powder a title sells, without its packaging: "Hodgdon H322 Smokeless
    Powder 1lb" and "HODGDON H322 8LB" are both "Hodgdon H322".

    As Graf writes it -- "Hodgdon CFE 223", "Alliant BE-86", "Winchester
    StaBall HD" -- unless the whole title is in capitals, where only a plain
    word longer than an acronym is put in lower case: "ACCURATE HIGH COUNTRY"
    is "Accurate High Country", its "IMR" and "HS6" stay as they are.
    """
    text = htmlib.unescape(title)
    text = _POWDER_WEIGHT.sub(" ", text)
    text = re.sub(r"\b(?:smokeless|powder|canister|keg|jug)\b", " ", text, flags=re.I)
    words = text.split()
    if _shouting(title):
        words = [w.capitalize() if w.isalpha() and len(w) > 3 else w for w in words]
    return " ".join(words).strip(" -,")


def supply_key(name: str | None) -> str:
    """A powder's or primer's name for comparing: "H4831-SC" is "h4831sc"."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def grafs_powders(products: Iterable[dict[str, Any]]) -> list[Powder]:
    found = []
    for product in products:
        title = htmlib.unescape(str(product.get("title") or ""))
        weight = _POWDER_WEIGHT.search(title)
        price = _cheapest(product)
        if not weight or not price or re.search(r"\bfuse\b|\bsample\b", title, re.I):
            continue
        amount, unit = float(weight.group(1)), weight.group(2).lower()
        pounds = (
            amount / 16 if unit.startswith("oz") else amount * 2.20462 if unit == "kg" else amount
        )
        name = powder_name(title)
        if pounds > 0 and name:
            found.append(Powder(name, pounds, price, _url(product), not _shouting(title)))
    return found


# -- Reading Graf & Sons ------------------------------------------------------
def read_collection(ctx: ScrapeContext, handle: str) -> list[dict[str, Any]]:
    """Every product of one Graf & Sons collection, 250 at a time."""
    found: list[dict[str, Any]] = []
    for page in range(1, PAGES + 1):
        text = ctx.get_text(
            urljoin(GRAFS, f"collections/{handle}/products.json?limit=250&page={page}")
        )
        try:
            products = list(json.loads(text).get("products") or [])
        except (ValueError, AttributeError) as exc:
            raise ScrapeError(
                f"Graf & Sons answered with something other than JSON ({exc})"
            ) from exc
        found.extend(products)
        if len(products) < 250:
            break
    return found


@dataclass
class Supplies:
    brass: list[Brass]
    primers: list[Primer]
    powders: list[Powder]


def read_supplies(ctx: ScrapeContext) -> Supplies:
    def collections(handles: Iterable[str]) -> list[dict[str, Any]]:
        return [p for handle in handles for p in read_collection(ctx, handle)]

    return Supplies(
        brass=grafs_brass(collections(BRASS_COLLECTIONS)),
        primers=grafs_primers(collections(PRIMER_COLLECTIONS)),
        powders=grafs_powders(collections(POWDER_COLLECTIONS)),
    )


# -- Matching brass to the armory's calibers -----------------------------------
#: Graf & Sons' shorthand, read the same way on both sides of a comparison.
_SYNONYMS = {
    "wcf": "winchester",
    "win": "winchester",
    "gov't": "government",
    "govt": "government",
    "gov": "government",
    "rem": "remington",
    "mag": "magnum",
    "spl": "special",
    "spc": "spc",
    "auto": "acp",
}
#: Words of a title that are not the cartridge: "Factory Seconds" is a grade,
#: "+P" a pressure the same case takes.
_NOT_CARTRIDGE = re.compile(r"^(?:factory\s+seconds|troy|wadcutter)\s+|\+p\b", re.I)


#: A case's full designation: "7.62x54r", "30-06", not a bore alone.
_DESIGNATION = re.compile(r"\dx\d|\d-\d")


def _designation(text: str) -> tuple[str, frozenset[str]]:
    """A caliber name as its number and its words: ".30-40 Krag" is
    ("30-40", {"krag"}), "7.62x54mmR" ("7.62x54r", {}), "45-70 Gov't"
    ("45-70", {"government"})."""
    words = re.findall(r"[a-z0-9.&'/-]+", text.lower().replace("×", "x"))
    number, rest = "", []
    for word in words:
        if not number and re.search(r"\d", word):
            number = re.sub(r"mm", "", word.strip(".-"))
        elif (bare := word.strip(".-")) and bare != "mm":
            rest.append(_SYNONYMS.get(bare, bare))
    return number, frozenset(rest)


def _readings(text: str) -> list[str]:
    """The ways a brass title's caliber is written: as it stands, without its
    parentheses, and each name inside them -- "30-40 Krag (30 Army)" is also
    "30-40 Krag" and "30 Army"; "11mm Mauser (11x60R Mauser, 43 Mauser)" also
    each of those."""
    text = _NOT_CARTRIDGE.sub(" ", text).strip()
    names = [text, re.sub(r"\([^)]*\)", " ", text)]
    for inside in re.findall(r"\(([^)]*)\)", text):
        names.extend(part.strip() for part in inside.split(","))
    return [" ".join(name.split()) for name in dict.fromkeys(names) if name.strip()]


def brass_by_caliber(session: Session, brass: Iterable[Brass]) -> dict[str, list[Brass]]:
    """Each approved caliber's new brass, by the same number and the same words
    as one of its spellings.

    Not the armory's looser reading, which suits a listing's title but not a
    shop's catalog of 600 cartridges: it took "25 Creedmoor" for .25 ACP, "303
    Savage" for .303 British and "222 Remington Magnum" for .222 Remington.
    Two loosenesses are kept, both for a cartridge's full designation, which
    names one case whatever words come with it: Graf's bare "6.5x55mm" is the
    armory's one 6.5x55mm, whatever the armory calls it, and the armory's bare
    "8x52mmR" or "30-03" is Graf's "8x52mmR T-66 Siamese" or "30-03 Gov't". A
    bore alone (".38") is no designation, and a vague caliber ("45 Caliber")
    is never matched.
    """
    named: dict[tuple[str, frozenset[str]], str] = {}
    numbered: dict[str, set[str]] = {}
    bare: dict[str, str] = {}
    for row in session.execute(
        select(Caliber).where(Caliber.status == ArmoryStatus.APPROVED, Caliber.enabled.is_(True))
    ).scalars():
        if armory.is_vague_caliber(row.name):
            continue
        for spelling in row.spellings:
            number, words = _designation(spelling)
            if number:
                named.setdefault((number, words), row.name)
                numbered.setdefault(number, set()).add(row.name)
                if not words and _DESIGNATION.search(number):
                    bare.setdefault(number, row.name)
    brass = list(brass)
    # What else Graf sells under each designation: the armory's bare "30-03"
    # is Graf's "30-03 Gov't" only when nothing else is a 30-03 there. Graf's
    # 22-250 is also an Ackley Improved, its 9x23mm a Largo and a Winchester.
    sold: dict[str, set[frozenset[str]]] = {}
    for item in brass:
        for reading in _readings(item.caliber_text):
            number, words = _designation(reading)
            sold.setdefault(number, set()).add(words)

    def exactly(readings: list[tuple[str, frozenset[str]]]) -> str | None:
        return next((named[r] for r in readings if r in named), None)

    def loosely(readings: list[tuple[str, frozenset[str]]]) -> str | None:
        for number, words in readings:
            if not _DESIGNATION.search(number):
                continue
            if not words and len(numbered.get(number, ())) == 1:
                return next(iter(numbered[number]))
            if words and number in bare and sold.get(number) == {words}:
                return bare[number]
        return None

    found: dict[str, list[Brass]] = {}
    for item in brass:
        readings = [_designation(reading) for reading in _readings(item.caliber_text)]
        caliber = exactly(readings) or loosely(readings)
        if caliber:
            found.setdefault(caliber, []).append(item)
    return found


# -- Keeping and using the prices ----------------------------------------------
POWDER = "powder"
PRIMER = "primer"


def primer_key(size: str, magnum: bool) -> str:
    """A kind of primer by name: "Large rifle", "Small pistol magnum"."""
    return f"{size} magnum" if magnum else size


def store_supplies(session: Session, supplies: Supplies, now: datetime) -> None:
    """Keep the cheapest in-stock price of each powder and each kind of primer.

    A powder no longer in stock keeps its row, marked so: a load already
    entered still names it, and the dropdown still offers it.
    """
    rows = {
        (row.kind, supply_key(row.name)): row
        for row in session.execute(select(ReloadingSupply)).scalars()
    }
    for row in rows.values():
        row.in_stock = False
    best: dict[tuple[str, str], tuple[float, str, str | None]] = {}
    names: dict[str, str] = {}
    for powder in supplies.powders:
        key = (POWDER, supply_key(powder.name))
        # A name from a title in capitals only until a written one turns up.
        if powder.as_written or key[1] not in names:
            names[key[1]] = powder.name
        if key not in best or powder.per_pound < best[key][0]:
            best[key] = (powder.per_pound, powder.name, powder.url)
    for primer in supplies.primers:
        name = primer_key(primer.size, primer.magnum)
        key = (PRIMER, supply_key(name))
        if key not in best or primer.each < best[key][0]:
            best[key] = (primer.each, name, primer.url)
    for (kind, compared), (price, name, url) in best.items():
        stored = rows.get((kind, compared))
        if stored is None:
            stored = ReloadingSupply(kind=kind, name=name)
            session.add(stored)
        if kind == POWDER:
            stored.name = names.get(compared, name)
        stored.unit_price = round(price, 5)
        stored.url, stored.in_stock, stored.checked_at = url, True, now
    session.flush()


def supply(session: Session, kind: str, name: str | None) -> ReloadingSupply | None:
    """The stored powder or primer a name means, however it is punctuated."""
    wanted = supply_key(name)
    if not wanted:
        return None
    return next(
        (
            row
            for row in session.execute(
                select(ReloadingSupply).where(ReloadingSupply.kind == kind)
            ).scalars()
            if supply_key(row.name) == wanted
        ),
        None,
    )


def powders(session: Session) -> list[ReloadingSupply]:
    """Every powder Graf & Sons has sold since the first read, by name."""
    return list(
        session.execute(
            select(ReloadingSupply)
            .where(ReloadingSupply.kind == POWDER)
            .order_by(ReloadingSupply.name)
        ).scalars()
    )


def price_load(session: Session, caliber: Caliber) -> None:
    """The caliber's primer and powder, from the stored prices. Run after each
    read and whenever the caliber's primer or load is edited.

    A magnum primer is priced only as one: a load that takes it is not
    costed with a standard primer. A Berdan primer is not priced -- Graf
    sells none -- and neither is a powder out of stock.
    """
    primer = None
    if caliber.primer_size and caliber.primer_size != BERDAN:
        primer = supply(
            session, PRIMER, primer_key(caliber.primer_size, bool(caliber.primer_magnum))
        )
    caliber.primer_cost = primer.unit_price if primer and primer.in_stock else None
    caliber.primer_url = primer.url if primer else None
    powder = supply(session, POWDER, caliber.powder_name)
    caliber.powder_url = powder.url if powder else None
    if powder and powder.in_stock and powder.unit_price and caliber.powder_charge_gr:
        caliber.powder_cost = round(
            powder.unit_price / GRAINS_PER_POUND * caliber.powder_charge_gr, 5
        )
    else:
        caliber.powder_cost = None


def price_brass(caliber: Caliber, offers: list[Brass] | None, now: datetime) -> bool:
    """The cheapest new case of the caliber, or nothing. Whether one was found."""
    caliber.brass_checked_at = now
    if not offers:
        caliber.brass_cost = caliber.brass_url = None
        return False
    cheapest = min(offers, key=lambda offer: offer.each)
    caliber.brass_cost, caliber.brass_url = round(cheapest.each, 4), cheapest.url
    return True


def bullet_cost(caliber: Caliber) -> float | None:
    """The bullet the load is for, at its weight where both are known, or the
    caliber's average bullet price."""
    if caliber.powder_bullet_gr:
        for weight in caliber.bullet_weights:
            if abs(weight.grains - caliber.powder_bullet_gr) < 0.5 and weight.projectile_cost:
                return weight.projectile_cost
    return caliber.projectile_cost


def reload_cost(caliber: Caliber) -> float | None:
    """One round, reloaded: bullet, new case, powder and primer -- or None
    until all four are known. No shipping, hazmat or tax, as for the rest."""
    parts = (bullet_cost(caliber), caliber.brass_cost, caliber.powder_cost, caliber.primer_cost)
    if any(part is None for part in parts):
        return None
    return round(sum(part or 0.0 for part in parts), 4)


# -- The primer a cartridge takes ----------------------------------------------
def article_primer(params: dict[str, str]) -> tuple[str | None, bool | None]:
    """The primer an infobox names: ``primer=Large rifle``, ``Berdan or boxer
    large rifle`` (a Boxer size wins: new brass takes one), ``Large pistol LP
    (some makers are now using small pistol SP)``. None where it says nothing."""
    text = re.sub(
        r"<[^>]+>|\{\{[^}]*\}\}|\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", params.get("primer", "")
    )
    if not text.strip():
        return None, None
    size, magnum = primer_kind(text)
    return size, magnum if size else None
