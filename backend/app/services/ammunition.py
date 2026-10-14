"""What it costs to shoot a caliber, and whether it can be reloaded.

"Ammunition" in ROADMAP.md, asked for on 2026-10-11: "understanding what it
costs to shoot a gun is probably more important to the economics than the
purchase price in most cases." For each caliber in the armory:

* **Bullet diameter and bullet weights**, from the cartridge's Wikipedia
  article (``Caliber.wikipedia_url``, proposed and accepted through
  app.services.wikipedia) -- the infobox's ``bullet`` and its ``bw1`` ...
  ``bwN``. Read once, and again whenever the caliber is edited, never on a
  clock: a cartridge's diameter does not change.
* **Factory cost per round**: for each of the caliber's weights, the cheapest
  in-stock box on Ammo.com within 3% of that weight, divided by the rounds in
  it; the caliber's figure is the average of those. Box price over rounds,
  nothing else -- no shipping, hazmat or tax. Where Ammo.com lists nothing,
  **Milsurp Munitions**, which loads the obsolete military cartridges nobody
  else does: its cheapest in-stock box.
* **Lee dies**: whether Lee Precision's rifle or handgun die catalog has a
  set for it, with the link.
* **Projectile cost**: Graf & Sons' reloading bullets at the caliber's
  diameter, averaged across its weights as the factory figure is.

**AmmoSeek was the first source for both, and was dropped on 2026-10-12.** Its
terms forbid automated collection, and about an hour into the first refresh
in production its bot control refused the scanner. Ammo.com and Graf & Sons
replaced it: neither's terms of use say anything against reading the site,
and neither's robots.txt closes the pages read here. Each is read lightly
all the same -- only about calibers with a listing for sale here, on the
schedule an administrator sets (daily, weekly or every two weeks; weekly by
default), through ``ScrapeContext`` and so under robots.txt, the request
delay and the cooldown register. Only the derived figures are kept, each with
a link back to the page.

Measured 2026-10-12: Ammo.com is a Magento store whose category pages
(``/rifle``, ``/handgun``, ``/rimfire``, ``/shotgun``) link one page per
caliber (``/rifle/7.62x54r-ammo``), and a caliber page lists its in-stock
boxes 40 at a time, cheapest per round first, each naming its weight in the
title ("... 7.62x54r Ammo - 20 Rounds of 180 Grain SP Ammunition") and its
rounds and price beside it. Graf & Sons is a Shopify store whose public
``/collections/bullets/products.json`` holds its whole bullet catalog, about
2,900 products in 12 pages of 250, each title stating diameter, weight and
count ("Prvi Partizan .311 Diameter Bullets 174 grain ... Bag of 50", or
"SIERRA 6.5(.264) 153g BULLET TMK 500/bx").
"""

from __future__ import annotations

import contextlib
import html as htmlib
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any
from urllib.parse import quote, unquote, urljoin

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AmmoSetting, ArmoryStatus, Caliber, CaliberBulletWeight, Item, as_utc, utcnow
from ..scrapers.base import Disallowed, ScrapeContext, ScrapeError, text_of
from . import armory, reloading, wikipedia

AMMO_COM = "https://ammo.com/"
#: Ammo.com's category pages, each linking a page per caliber.
AMMO_COM_CATEGORIES = ("rifle", "handgun", "rimfire", "shotgun")
#: Pages of a caliber read at most: 40 boxes each, cheapest first, so three
#: hold every weight anyone loads at a price that matters.
AMMO_COM_PAGES = 3
GRAFS = "https://grafs.com/"
GRAFS_BULLETS = "collections/bullets/products.json?limit=250&page={page}"
#: A ceiling on the catalog's pages, which ends long before it on an empty one.
GRAFS_PAGES = 30
#: More than this a bullet is a count misread, not a price -- a check behind
#: the handle's count (see grafs_bullets), not a substitute for it.
MOST_PER_BULLET = 10.0
#: A title's count below this is boxes in a case, not bullets in a box.
FEWEST_BULLETS = 10
MILSURP_MUNITIONS = "https://milsurpmunitions.com/"
LEE = "https://leeprecision.com/"
LEE_DIE_CATEGORIES = ("reloading-dies-rifle-dies", "reloading-dies-hand-gun-dies")
#: Lee's shotshell reloader, whose page lists the gauges it is made for.
LEE_SHOTSHELL = "load-all-ii"

#: A shotgun's "bullet" diameter: the bore of each gauge, which is what a slug
#: is sized to. Asked for on 2026-10-12, in place of an article that has none.
GAUGE_BORES = {
    "4": 1.052,
    "8": 0.835,
    "10": 0.775,
    "12": 0.729,
    "16": 0.662,
    "20": 0.615,
    "24": 0.579,
    "28": 0.550,
    "32": 0.526,
    "410": 0.410,
}
_GAUGE = re.compile(r"^\s*\.?(\d{1,3})\s*(?:gauge|ga\.?|bore)?\s*$", re.I)

#: The three parts of a refresh, each of which can be asked for alone (2026-10-12):
#: the calibers' Wikipedia facts; reloading -- Graf & Sons' bullets and Lee's
#: dies; and factory ammunition prices from Ammo.com and Milsurp Munitions.
PARTS = ("wikipedia", "reloading", "prices")

#: The refresh frequencies an administrator chooses between, in days.
FREQUENCIES = {1: "Daily", 7: "Weekly", 14: "Every 2 weeks"}
DEFAULT_DAYS = 7

GRAINS_PER_GRAM = 15.4323584
MM_PER_INCH = 25.4
#: How close an offer's bullet must be to a weight to count as that weight:
#: a 148 gr and a 150 gr load are the same choice, 174 gr and 180 gr are not.
SAME_WEIGHT = 0.03
#: How close a bullet's diameter must be to the cartridge's: .311" for a
#: 7.62x54R stated as 7.92 mm (.3118").
SAME_DIAMETER = 0.0015


# -- Wikipedia --------------------------------------------------------------
@dataclass(frozen=True)
class ArticleFacts:
    diameter_in: float | None
    grains: list[float]
    #: The primer the infobox names ("Large rifle"), and whether a magnum.
    primer_size: str | None = None
    primer_magnum: bool | None = None


def _infobox(wikitext: str) -> str | None:
    """The body of the cartridge infobox, balanced braces and all."""
    start = re.search(r"\{\{\s*Infobox (?:firearm )?cartridge", wikitext, re.I)
    if not start:
        return None
    depth = 0
    at = start.start()
    while at < len(wikitext) - 1:
        pair = wikitext[at : at + 2]
        if pair == "{{":
            depth += 1
            at += 2
            continue
        if pair == "}}":
            depth -= 1
            at += 2
            if depth == 0:
                return wikitext[start.end() : at - 2]
            continue
        at += 1
    return None


def _params(box: str) -> dict[str, str]:
    """An infobox's ``|name=value`` parameters, split at the top level only."""
    found: dict[str, str] = {}
    depth = 0
    piece = ""
    pieces = []
    for at, char in enumerate(box):
        two = box[at : at + 2]
        if two in ("{{", "[["):
            depth += 1
        elif two in ("}}", "]]"):
            depth -= 1
        if char == "|" and depth == 0:
            pieces.append(piece)
            piece = ""
        else:
            piece += char
    pieces.append(piece)
    for part in pieces:
        name, sep, value = part.partition("=")
        if sep:
            found[name.strip().lower()] = re.sub(
                r"<!--.*?-->|<ref.*?(?:/>|</ref>)", "", value, flags=re.S
            ).strip()
    return found


def _number(text: str | None) -> float | None:
    found = re.search(r"\d+(?:\.\d+)?|\.\d+", (text or "").replace(",", ""))
    return float(found.group(0)) if found else None


#: A number and the unit written with it: "0.308 in (7.82 mm)" is inches,
#: "{{convert|5.7|mm|in}}" is millimeters, "150 gr" is grains.
_TEMPLATE = re.compile(r"\{\{\s*(?:convert|cvt)\s*\|\s*([\d.]+)\s*\|\s*([a-z\"]+)", re.I)
_WITH_UNIT = re.compile(r"(\d+(?:\.\d+)?|\.\d+)\s*(mm|in\b|inch|\"|gr\b|grains?|g\b|grams?)?", re.I)


def _measure(text: str | None) -> tuple[float | None, str | None]:
    """The first number in an infobox value and the unit written with it,
    or None for the unit when the value does not say."""
    found = _TEMPLATE.search(text or "")
    if found:
        number, unit = found.group(1), found.group(2)
    else:
        plain = _WITH_UNIT.search((text or "").replace(",", ""))
        if not plain:
            return None, None
        number, unit = plain.group(1), plain.group(2)
    try:
        value = float(number)
    except ValueError:
        return None, None
    unit = (unit or "").lower()
    named = next(
        (
            name
            for prefix, name in (
                ("mm", "mm"),
                ("in", "in"),
                ('"', "in"),
                ("gram", "g"),
                ("gr", "gr"),
                ("g", "g"),
            )
            if unit.startswith(prefix)
        ),
        None,
    )
    return value, named


def article_facts(wikitext: str) -> ArticleFacts:
    """The bullet's diameter in inches and its weights in grains, from a
    cartridge article's infobox. Each is empty when the article does not say.

    **A unit written with a number beats the page's flag.** The flags
    (``is_SI_specs``, ``is_SI_ballistics``, ``bwunit``) say how the infobox
    displays, and articles state values every way regardless: 7.62x51 NATO
    gives "0.308 in (7.82 mm)", .22 LR a ``{{convert}}`` in inches, .303
    British grains under ``is_SI_ballistics=yes``. Read by the flag alone
    those were 0.0121", 0.0088" and a 2,315 gr bullet (2026-10-11). The flag
    decides only where the value says nothing, and a bullet weight is grams
    only when labeled so or too light to be grains: no bullet weighs 40 g.
    """
    box = _infobox(wikitext)
    if box is None:
        return ArticleFacts(None, [])
    params = _params(box)
    diameter = None
    value, unit = _measure(params.get("bullet"))
    if value:
        metric = unit == "mm" or (
            unit is None and (params.get("is_si_specs", "").lower().startswith("y") or value > 1.5)
        )
        diameter = round(value / MM_PER_INCH, 4) if metric else value
    labeled = params.get("bwunit", "").lower()
    weights: list[float] = []
    for key in sorted((k for k in params if re.fullmatch(r"bw\d+", k)), key=lambda k: int(k[2:])):
        value, unit = _measure(params[key])
        if not value:
            continue
        grams = unit == "g" or (
            unit is None and ("gram" in labeled or ("grain" not in labeled and value < 40))
        )
        grains = float(round(value * GRAINS_PER_GRAM if grams else value))
        # Under ten grains is a footnote or a misread, not a bullet: the 11mm
        # French Ordnance article gave a "6" (2026-10-12).
        if grains >= 10 and grains not in weights:
            weights.append(grains)
    primer, magnum = reloading.article_primer(params)
    return ArticleFacts(diameter, sorted(weights), primer, magnum)


def read_article(fetch: wikipedia.Fetch, url: str) -> str:
    """An article's wikitext, by its address."""
    title = url.rsplit("/wiki/", 1)[-1].replace("_", " ")
    answer = fetch(
        {
            "action": "parse",
            "page": unquote(title),
            "prop": "wikitext",
            "redirects": "1",
            "formatversion": "2",
        }
    )
    return str((answer.get("parse") or {}).get("wikitext") or "")


def set_weights(caliber: Caliber, grains: Iterable[float], source: str = "wikipedia") -> None:
    """Replace the caliber's weights from one source; typed ones are kept."""
    wanted = {float(g) for g in grains}
    for weight in list(caliber.bullet_weights):
        if weight.source == source and weight.grains not in wanted:
            caliber.bullet_weights.remove(weight)
    have = {weight.grains for weight in caliber.bullet_weights}
    for grains_value in sorted(wanted - have):
        caliber.bullet_weights.append(CaliberBulletWeight(grains=grains_value, source=source))


def refresh_articles(
    session: Session,
    fetch: wikipedia.Fetch,
    *,
    limit: int | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Read the facts of every caliber whose article has not been read since
    it was linked or edited. Returns how many were read. Gauges, which have
    no article worth reading, take their bore from :data:`GAUGE_BORES`."""
    set_gauge_bores(session)
    due = list(
        session.execute(
            select(Caliber)
            .where(Caliber.wikipedia_url.is_not(None), Caliber.wikipedia_read_at.is_(None))
            .order_by(Caliber.id)
        ).scalars()
    )[:limit]
    for caliber in due:
        try:
            facts = article_facts(read_article(fetch, caliber.wikipedia_url or ""))
        except Exception as exc:  # a bad page must not stop the rest
            log(f"  {caliber.name}: Wikipedia did not answer ({exc}).")
            continue
        if facts.diameter_in:
            caliber.bullet_diameter_in = facts.diameter_in
        if facts.grains:
            set_weights(caliber, facts.grains)
        # The primer is the cartridge's, read once; one set by hand is kept.
        if facts.primer_size and caliber.primer_source != "hand":
            caliber.primer_size, caliber.primer_magnum = facts.primer_size, facts.primer_magnum
            caliber.primer_source = "wikipedia"
            reloading.price_load(session, caliber)
        caliber.wikipedia_read_at = utcnow()
        session.commit()
        log(
            f"  {caliber.name}: diameter {facts.diameter_in or 'not stated'}, "
            f"weights {', '.join(f'{g:g}' for g in facts.grains) or 'none stated'}, "
            f"primer {reloading.primer_key(facts.primer_size, bool(facts.primer_magnum)) if facts.primer_size else 'not stated'}"
        )
    return len(due)


# -- Offers, from either source ---------------------------------------------
@dataclass(frozen=True)
class Offer:
    grains: float | None
    price: float
    rounds: int
    #: The product's own page, where there is one to link to.
    url: str | None = None

    @property
    def each(self) -> float:
        return self.price / self.rounds


def _price(text: Any) -> float | None:
    found = re.search(r"[\d,]+(?:\.\d+)?", str(text or ""))
    try:
        return float(found.group(0).replace(",", "")) if found else None
    except ValueError:
        return None


def lows(offers: Iterable[Offer], weights: Iterable[float]) -> dict[float, float]:
    """Each weight's cheapest offer per round, for the weights any offer has.

    With no weights to go by, the weight offered most often stands in: one
    junk listing at a wrong weight is not the caliber's usual load.
    """
    offers = [o for o in offers if o.grains]
    weights = list(weights)
    if not weights:
        counted: dict[float, int] = {}
        for offer in offers:
            counted[offer.grains or 0] = counted.get(offer.grains or 0, 0) + 1
        if not counted:
            return {}
        weights = [max(counted, key=lambda grains: (counted[grains], -grains))]
    found = {}
    for weight in weights:
        near = [o.each for o in offers if abs((o.grains or 0) - weight) <= weight * SAME_WEIGHT]
        if near:
            found[weight] = round(min(near), 4)
    return found


def _spelled(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("×", "x"))


def match_pages(session: Session, entries: list[tuple[str, list[str]]]) -> dict[str, str]:
    """The armory caliber each of a shop's caliber pages is for, by caliber name.

    *entries* is ``(page, names)`` per page. **A page whose name is one of the
    caliber's own spellings wins**, and the armory's looser reading of a name
    only fills in after: read loosely and first come first served, ".308
    Marlin Express" claimed 7.62x51 NATO, "9mm Browning Long" 9mm Luger and
    "22 S, L, LR" .22 LR on AmmoSeek (2026-10-11).

    Among the pages a caliber's spellings name, **the one named by its
    earliest spelling** -- its own name first, then its aliases in order:
    5.56x45mm NATO is Ammo.com's "5.56x45" page rather than its "223", which
    is also one of its spellings. A caliber with a vague name is never
    matched (see :func:`armory.is_vague_caliber`).
    """
    ranked: dict[str, tuple[str, int]] = {}
    for row in session.execute(
        select(Caliber).where(Caliber.status == ArmoryStatus.APPROVED, Caliber.enabled.is_(True))
    ).scalars():
        if armory.is_vague_caliber(row.name):
            continue
        for rank, spelling in enumerate(row.spellings):
            ranked.setdefault(_spelled(spelling), (row.name, rank))
    found: dict[str, str] = {}
    best: dict[str, int] = {}
    for path, names in entries:
        for name in names:
            mine = ranked.get(_spelled(name))
            if mine and path not in found.values() and mine[1] < best.get(mine[0], 1 << 30):
                found[mine[0]], best[mine[0]] = path, mine[1]
    for path, names in entries:
        for name in names:
            loose = armory.canonical_caliber(session, name)
            if (
                loose
                and not armory.is_vague_caliber(loose)
                and loose not in found
                and path not in found.values()
            ):
                found[loose] = path
                break
    return found


# -- Ammo.com ------------------------------------------------------------------
_AMMO_COM_PAGE = re.compile(
    r"^https://ammo\.com/(?:" + "|".join(AMMO_COM_CATEGORIES) + r")/[a-z0-9._-]+/?$"
)


#: Pages whose own name says less than the cartridge: Ammo.com's "8mm" is
#: the 8mm Mauser (2026-10-12, found priced against the rimmed 8x57 JR).
AMMO_COM_HINTS = {"8mm-ammo": ["8mm Mauser"]}
_ABBREVIATED = (("Win", "Winchester"), ("Rem", "Remington"), ("Mag", "Magnum"))


def _ammo_com_names(label: str, page: str = "") -> list[str]:
    """The names one caliber link stands for.

    "40 Cal (S&W) Ammo" is "40 Cal (S&W)", "40 Cal" and "40 S&W"; "22 Long
    Rifle (LR) Ammo" is also "22 LR". A link to a caliber with nothing in
    stock says so first ("Out of stock 32 S&W Ammo").

    And the way the armory writes them: an inch caliber with its point
    (".22-250", ".300 Blackout", ".50 BMG") and the abbreviations spelled out
    ("300 Win Magnum" is ".300 Winchester Magnum") -- without which 52 of the
    122 pages matched nothing on the first production run (2026-10-12).
    """
    label = re.sub(r"^\s*out of stock\s*", "", label, flags=re.I)
    label = re.sub(r"\s+(?:ammo(?:\s+for\s+sale)?|shotgun\s+shells)\s*$", "", label, flags=re.I)
    label = label.strip()
    names = [*AMMO_COM_HINTS.get(page.rstrip("/").rsplit("/", 1)[-1], []), label]
    bracketed = re.match(r"^(\S+)\s.*?\(([^)]+)\)", label)
    if bracketed:
        names.append(re.sub(r"\s*\([^)]*\)", "", label).strip())
        names.append(f"{bracketed.group(1)} {bracketed.group(2)}")
    for name in list(names):
        spelled = name
        for short, long in _ABBREVIATED:
            spelled = re.sub(rf"\b{short}\b", long, spelled)
        # Two or three digits not followed by a metric size or a gauge: inches.
        inches = re.match(r"^\d{2,3}(?![\d.]*\s*(?:mm|x\d|gauge|ga\b|buck))", name, re.I)
        for variant in (spelled, f".{name}" if inches else "", f".{spelled}" if inches else ""):
            if variant and variant not in names:
                names.append(variant)
    return [n for n in names if n]


def ammo_com_calibers(html: str) -> list[tuple[str, list[str]]]:
    """The caliber pages one Ammo.com category page links: ``(page, names)``."""
    found: dict[str, list[str]] = {}
    for link in BeautifulSoup(html, "html.parser").select("a[href]"):
        href = str(link.get("href")).rstrip("/")
        label = text_of(link)
        if _AMMO_COM_PAGE.match(href) and label and href not in found:
            found[href] = _ammo_com_names(label, href)
    return list(found.items())


def ammo_com_offers(html: str) -> list[Offer]:
    """The in-stock boxes on one page of an Ammo.com caliber.

    The weight from the title ("... 20 Rounds of 180 Grain SP Ammunition"),
    the rounds from the line beside it ("20 Rounds") and the price actually
    asked -- the sale price where there is one. A box stating no rounds is
    passed over rather than guessed.
    """
    found = []
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select(".b-category-product-list__item"):
        if item.select_one(".b-availability__in-stock") is None:
            continue
        name_tag = item.select_one(".b-product-list-item__product-name")
        facts_tag = item.select_one(".b-product-list-item__attributes-short")
        title = text_of(name_tag) if name_tag else ""
        facts = text_of(facts_tag) if facts_tag else ""
        price_tag = item.select_one('.price[id^="product-price-"]') or item.select_one(".price")
        price = _price(text_of(price_tag)) if price_tag else None
        rounds = re.search(r"([\d,]+)\s*rounds?\b", facts, re.I)
        grains = re.search(r"(\d+(?:\.\d+)?)\s*(?:grains?|gr)\b", title, re.I)
        count = int(rounds.group(1).replace(",", "")) if rounds else 0
        if price and count > 0:
            found.append(Offer(float(grains.group(1)) if grains else None, price, count))
    return found


def ammo_com_more(html: str, page: int) -> bool:
    """Whether a caliber's page *page* links the page after it."""
    return f"?p={page + 1}" in html


# -- Graf & Sons ---------------------------------------------------------------
#: A diameter written as three or four decimals: ".311", "(.264)", '.452"'.
_DIAMETER = re.compile(r"(?<![\d.])(\.\d{3,4})(?!\d)")
#: Grains, written out or run into the shape after it ("105gTCFP"): a "g"
#: before a capital or a mark is grains, before "a" or "auge" it is not.
_BULLET_GRAINS = re.compile(r"(\d{2,3}(?:\.\d)?)\s*(?:grains?|gr|g)(?-i:(?![a-z]))", re.I)
_BULLET_COUNT = re.compile(
    r"(?:\b(?:box|bag|tin|pack|bucket|case|each)\s+of|\bper|\bp/)\s*([\d,]+)"
    r"|([\d,]+)\s*(?:/?\s*(?:bx|box|b|bag|bg|pk)\b|ct\b|count\b|pcs?\b|each\b|ea\b|bullets\b"
    r"|per\s+(?:box|bag)\b)",
    re.I,
)


def _count(text: str) -> int:
    counted = _BULLET_COUNT.search(text)
    return int((counted.group(1) or counted.group(2)).replace(",", "")) if counted else 0


def grafs_bullets(products: list[dict[str, Any]]) -> list[tuple[float, Offer]]:
    """Graf & Sons' in-stock bullets: ``(diameter in inches, offer)``.

    Every fact is in the title, which is written several ways: "Prvi Partizan
    .311 Diameter Bullets 174 grain Full Metal Jacket ... Bag of 50", "SIERRA
    6.5(.264) 153g BULLET TMK 500/bx", "PULL DOWN 30c (.308) 160g BULLET (30-30)
    P/100". A variant naming its own count ("100 ct") overrides the product's.
    A product missing any of the three is passed over rather than guessed.

    **A count under ten is a case of boxes**: Graf & Sons sells Winchester's
    147 gr .308 as "Box of 4" at $165.99 and Federal's Fusion as "Box of 4" at
    $32.99, which their handles say are four boxes of 500 and a box of 50. The
    handle's count is taken there, and a product whose handle says none is
    passed over.
    """
    found = []
    for product in products:
        title = htmlib.unescape(str(product.get("title") or ""))
        diameter = _DIAMETER.search(title)
        grains = _BULLET_GRAINS.search(title)
        if not diameter or not grains:
            continue
        inches = float(diameter.group(1))
        if not 0.1 < inches < 1.1:
            continue
        url = urljoin(GRAFS, f"products/{product.get('handle')}") if product.get("handle") else None
        for variant in product.get("variants") or []:
            if not variant.get("available"):
                continue
            named = str(variant.get("title") or "")
            count = _count(named if named != "Default Title" else "") or _count(title)
            if 0 < count < FEWEST_BULLETS:
                count = _count(str(product.get("handle") or "").replace("-", " "))
                count = count if count >= FEWEST_BULLETS else 0
            price = _price(variant.get("price"))
            if price and count > 0 and price / count <= MOST_PER_BULLET:
                found.append((inches, Offer(float(grains.group(1)), price, count, url)))
    return found


def at_diameter(bullets: list[tuple[float, Offer]], diameter: float) -> list[Offer]:
    """The bullets made for a cartridge of *diameter*."""
    return [offer for inches, offer in bullets if abs(inches - diameter) <= SAME_DIAMETER]


# -- Milsurp Munitions -------------------------------------------------------
def milsurp_offers(products: list[dict[str, Any]]) -> list[tuple[str, Offer]]:
    """In-stock loads from Milsurp Munitions' Store API: ``(name, offer)``.

    The bullet weight is in the name ("8x50R Mannlicher (205gr SP)") and the
    rounds in a box in the description ("20 rounds"); a product stating
    neither count is passed over rather than guessed.
    """
    found = []
    for product in products:
        if not product.get("is_in_stock"):
            continue
        name = htmlib.unescape(str(product.get("name") or ""))
        words = htmlib.unescape(
            re.sub(
                r"<[^>]+>",
                " ",
                f"{product.get('short_description') or ''} {product.get('description') or ''}",
            )
        )
        rounds = re.search(r"(\d+)\s*(?:rounds?|rds?\b|ct\b|count\b|per box)", words, re.I)
        prices = product.get("prices") or {}
        try:
            price = int(prices.get("price") or 0) / 10 ** int(
                prices.get("currency_minor_unit") or 2
            )
        except (TypeError, ValueError):
            continue
        grains = re.search(r"(\d+)\s*gr", name, re.I)
        if rounds and int(rounds.group(1)) > 0 and price > 0:
            found.append(
                (
                    name,
                    Offer(float(grains.group(1)) if grains else None, price, int(rounds.group(1))),
                )
            )
    return found


# -- Lee Precision -----------------------------------------------------------
def lee_dies(html: str) -> list[tuple[str, str]]:
    """The die sets on one page of Lee's catalog: ``(cartridge, page)``."""
    found = []
    for link in BeautifulSoup(html, "html.parser").select(".product-title a"):
        name = re.sub(r"\s+dies?\s*$", "", text_of(link), flags=re.I).strip()
        if name:
            found.append((name, urljoin(LEE, str(link.get("href")))))
    return found


def lee_names(name: str) -> list[str]:
    """The cartridges one Lee die set is for.

    One set often loads two: "38 Special / 357 Magnum", "40 S&W / 10MM Auto",
    and written shorter, "44 Special/Magnum" and "38 ACP/Super", where the
    second takes the first's number. Read whole, only the first was credited,
    and .357 Magnum came out with no Lee dies (2026-10-12). "32/20 Winchester"
    is one cartridge, the .32-20, and is left alone.
    """
    parts = [p.strip() for p in re.split(r"(?<!\d)\s*/\s*|\s*/\s*(?!\d)", name) if p.strip()]
    if len(parts) < 2:
        return [name]
    number = re.match(r"^\.?\d[\d.x]*", parts[0])
    found = [name]
    for part in parts:
        bare = not re.search(r"\d", part) and number
        found.append(f"{number.group(0)} {part}" if bare and number else part)
    return found


def gauge_bore(name: str) -> float | None:
    """The bore diameter of a gauge named like "12 Gauge", "20 ga" or ".410"."""
    found = _GAUGE.match(name or "")
    if not found or (
        "gauge" not in name.lower() and "ga" not in name.lower() and "410" not in name
    ):
        return None
    return GAUGE_BORES.get(found.group(1))


def set_gauge_bores(session: Session) -> int:
    """Give every gauge in the armory its bore as its diameter, where it has none."""
    changed = 0
    for caliber in session.execute(select(Caliber)).scalars():
        bore = gauge_bore(caliber.name)
        if bore and caliber.bullet_diameter_in is None:
            caliber.bullet_diameter_in = bore
            changed += 1
    session.commit()
    return changed


def lee_shotshells(html: str) -> list[str]:
    """The gauges Lee's Load-All II page offers: "12 Gauge", ".410".

    From the page's own choice of gauge -- the dropdown whose every option is
    a gauge -- not the site-wide cartridge finder sharing the page, which
    lists hundreds of cartridges and the gauges among them. Each option's own
    words only: the page leaves ``<option>`` unclosed, so an option's text
    runs on into every one after it.
    """
    for select_ in BeautifulSoup(html, "html.parser").select("select"):
        names = [next(option.stripped_strings, "") for option in select_.select("option")]
        offered = [n for n in names if n and not n.lower().startswith("select")]
        if offered and all(re.search(r"gauge|\b410\b", n, re.I) for n in offered):
            return [".410" if "410" in n else n for n in offered]
    return []


def lee_catalog(ctx: ScrapeContext) -> list[tuple[str, str]]:
    """Every die set Lee lists, from its rifle and handgun die categories."""
    found: list[tuple[str, str]] = []
    for category in LEE_DIE_CATEGORIES:
        for page in range(1, 20):
            sets = lee_dies(ctx.get_text(urljoin(LEE, f"{category}?pagesize=48&pagenumber={page}")))
            fresh = [entry for entry in sets if entry not in found]
            if not fresh:
                break
            found.extend(fresh)
    # Shotshells too, which are reloaded on a Load-All rather than with dies
    # (asked for on 2026-10-12). One page; a failure costs only these.
    load_all = urljoin(LEE, LEE_SHOTSHELL)
    with contextlib.suppress(ScrapeError):
        found.extend((gauge, load_all) for gauge in lee_shotshells(ctx.get_text(load_all)))
    return found


# -- The refresh ---------------------------------------------------------------
def settings(session: Session) -> AmmoSetting:
    row = session.get(AmmoSetting, 1)
    if row is None:
        row = AmmoSetting(id=1, refresh_days=DEFAULT_DAYS)
        session.add(row)
        session.commit()
    return row


def is_due(session: Session, now: datetime | None = None) -> bool:
    return bool(due_parts(session, now))


def due_parts(session: Session, now: datetime | None = None) -> tuple[str, ...]:
    """The parts of a refresh to run now: those asked for, or all of them when
    the schedule says so, or none.

    The schedule runs from the last *full* refresh, so updating one part by
    hand does not put the others off for another week.
    """
    row = settings(session)
    if row.requested_at is not None:
        asked = tuple(p for p in PARTS if p in (row.requested_parts or "").split(","))
        return asked or PARTS
    last = as_utc(row.last_full_at)
    if last is None or (now or utcnow()) - last >= timedelta(days=row.refresh_days or 7):
        return PARTS
    return ()


def ask_for(session: Session, parts: Iterable[str]) -> None:
    """Ask the scheduler for a refresh of *parts*, on its next tick."""
    wanted = [p for p in PARTS if p in set(parts)]
    if not wanted:
        raise ValueError(f"Nothing to refresh: the parts are {', '.join(PARTS)}.")
    row = settings(session)
    row.requested_at = utcnow()
    row.requested_parts = ",".join(wanted)
    session.commit()


def for_sale(session: Session) -> list[Caliber]:
    """Approved calibers with a listing for sale here, which is what is asked about."""
    names = set(
        session.execute(
            select(Item.caliber).where(
                Item.is_active.is_(True), Item.is_sold.is_(False), Item.caliber.is_not(None)
            )
        ).scalars()
    )
    return [
        caliber
        for caliber in session.execute(
            select(Caliber)
            .where(Caliber.status == ArmoryStatus.APPROVED, Caliber.enabled.is_(True))
            .order_by(Caliber.name)
        ).scalars()
        if caliber.name in names
    ]


def _record(caliber: Caliber, found: dict[float, float], field: str) -> None:
    by_weight = {weight.grains: weight for weight in caliber.bullet_weights}
    for weight in caliber.bullet_weights:
        setattr(weight, field, None)
    for grains, each in found.items():
        if grains in by_weight:
            setattr(by_weight[grains], field, each)


def _from_ammo_com(
    ctx: ScrapeContext, page: str | None, weights: list[float], *, any_load: bool = False
) -> dict[float, float]:
    """Each weight's cheapest round on Ammo.com's page for a caliber.

    Pages are read until every weight has a price or the cheapest few pages
    are done: the list is cheapest first, so a weight not on them is not
    sold at a price that would change the figure. A gauge has no weights in
    grains, and its boxes name none ("1 oz", "00 Buck"), so its cheapest
    round of any load stands in (*any_load*) -- not the weight offered most
    often, which on a shotshell page is a slug's: 20 gauge came out at $4 a
    round on the first production run (2026-10-12).
    """
    if not page:
        return {}
    if any_load:
        offers_ = ammo_com_offers(ctx.get_text(page))
        return {0.0: round(min(o.each for o in offers_), 4)} if offers_ else {}
    offers: list[Offer] = []
    found: dict[float, float] = {}
    for number in range(1, AMMO_COM_PAGES + 1):
        html = ctx.get_text(page if number == 1 else f"{page}?p={number}")
        offers.extend(ammo_com_offers(html))
        found = lows(offers, weights)
        if (weights and len(found) == len(weights)) or not ammo_com_more(html, number):
            break
    if not found and not weights and offers:
        found = {0.0: round(min(offer.each for offer in offers), 4)}
    return found


def _factory(
    session: Session,
    ctx: ScrapeContext,
    caliber: Caliber,
    pages: dict[str, str],
    milsurp: list[tuple[str, Offer]],
    now: datetime,
) -> str | None:
    """Price one caliber's factory ammunition. Returns where it came from.

    A page Ammo.com could not serve this time keeps the figure it gave before,
    unless Milsurp Munitions has one now: "not read" is not "none for sale".
    """
    weights = [weight.grains for weight in caliber.bullet_weights]
    page = pages.get(caliber.name)
    found: dict[float, float] = {}
    unread = False
    try:
        found = _from_ammo_com(ctx, page, weights, any_load=gauge_bore(caliber.name) is not None)
    except Disallowed:
        raise
    except ScrapeError:
        # One caliber Ammo.com could not answer for still gets the fallback.
        unread = True
    if found:
        caliber.factory_source, caliber.factory_url = "ammo-com", page
    else:
        mine = [
            offer
            for name, offer in milsurp
            if armory.canonical_caliber(session, name) == caliber.name
        ]
        if mine:
            cheapest = min(mine, key=lambda offer: offer.each)
            found = {cheapest.grains or 0.0: round(cheapest.each, 4)}
            caliber.factory_source = "milsurp-munitions"
            caliber.factory_url = urljoin(MILSURP_MUNITIONS, "?s=" + quote(caliber.name))
    if not found and unread and caliber.factory_source == "ammo-com":
        return caliber.factory_source
    caliber.factory_checked_at = now
    if not found:
        caliber.factory_cpr = None
        caliber.factory_source = caliber.factory_url = None
        _record(caliber, {}, "factory_cpr")
        return None
    caliber.factory_cpr = round(mean(found.values()), 4)
    _record(caliber, found, "factory_cpr")
    return caliber.factory_source


#: Rimfire cartridges, which cannot be reloaded: .22 LR was priced against
#: .224" centerfire bullets on the first production run (2026-10-12).
RIMFIRE = re.compile(
    r"^\s*(?:\.?22\s*(?:lr|long(?:\s*rifle)?|short|wmr|wrf|win(?:chester)?\s*(?:mag|auto)|magnum|cb|bb)"
    r"|\.?17\s*(?:hmr|wsm|hm2|mach\s*2)|5\s*mm\s*rem(?:ington)?\s*mag|\.?25\s*stevens)\b",
    re.I,
)


def is_rimfire(name: str) -> bool:
    return bool(RIMFIRE.match(name or ""))


def _projectiles(caliber: Caliber, bullets: list[tuple[float, Offer]], now: datetime) -> bool:
    """Price one caliber's projectiles by its diameter. Whether any were found.

    Linked to the cheapest of the bullets priced, on Graf & Sons' own page.
    None for a rimfire cartridge, which is not reloaded.
    """
    caliber.projectile_checked_at = now
    weights = [w.grains for w in caliber.bullet_weights]
    offers = (
        at_diameter(bullets, caliber.bullet_diameter_in)
        if caliber.bullet_diameter_in and not is_rimfire(caliber.name)
        else []
    )
    found = lows(offers, weights)
    caliber.projectile_cost = round(mean(found.values()), 4) if found else None
    priced = [
        offer
        for offer in offers
        if any(abs((offer.grains or 0) - w) <= w * SAME_WEIGHT for w in found)
    ]
    cheapest = min(priced, key=lambda offer: offer.each, default=None)
    caliber.projectile_url = (cheapest.url or GRAFS) if found and cheapest else None
    _record(caliber, found, "projectile_cost")
    return bool(found)


def _refresh_lee(session: Session, ctx: ScrapeContext, now: datetime) -> str:
    """Mark every caliber with whether Lee lists dies for it. Returns a note."""
    try:
        catalog = lee_catalog(ctx)
    except (Disallowed, ScrapeError) as exc:
        return f"Lee not read ({exc})"
    dies: dict[str, str] = {}
    for name, url in catalog:
        for part in lee_names(name):
            mine = armory.canonical_caliber(session, part)
            if mine:
                dies.setdefault(mine, url)
    for caliber in session.execute(select(Caliber)).scalars():
        caliber.lee_dies = caliber.name in dies
        caliber.lee_url = dies.get(caliber.name)
        caliber.lee_checked_at = now
    session.commit()
    return f"Lee: {len(dies)} calibers with dies"


@dataclass
class Sources:
    """What one refresh read once and uses for every caliber."""

    #: Ammo.com's page for each armory caliber, by caliber name.
    pages: dict[str, str]
    #: Graf & Sons' bullets, ``(diameter, offer)``.
    bullets: list[tuple[float, Offer]]
    milsurp: list[tuple[str, Offer]]
    notes: list[str]
    #: Graf & Sons' brass, primers and powders, for reloading.
    supplies: reloading.Supplies | None = None


def grafs_catalog(ctx: ScrapeContext) -> list[tuple[float, Offer]]:
    """Graf & Sons' whole bullet catalog, a page of 250 at a time."""
    found: list[tuple[float, Offer]] = []
    for number in range(1, GRAFS_PAGES + 1):
        text = ctx.get_text(urljoin(GRAFS, GRAFS_BULLETS.format(page=number)))
        try:
            products = list(json.loads(text).get("products") or [])
        except (ValueError, AttributeError) as exc:
            raise ScrapeError(
                f"Graf & Sons answered with something other than JSON ({exc})"
            ) from exc
        if not products:
            break
        found.extend(grafs_bullets(products))
    return found


def _sources(session: Session, ctx: ScrapeContext, parts: Iterable[str] = PARTS) -> Sources:
    """Read once what the parts asked for need: Ammo.com's caliber pages and
    Milsurp Munitions for prices, Graf & Sons' catalog for reloading."""
    parts = set(parts)
    found = Sources({}, [], [], [])
    if "prices" in parts:
        try:
            entries: list[tuple[str, list[str]]] = []
            for category in AMMO_COM_CATEGORIES:
                entries.extend(ammo_com_calibers(ctx.get_text(urljoin(AMMO_COM, category))))
            found.pages = match_pages(session, entries)
        except (Disallowed, ScrapeError) as exc:
            found.notes.append(f"Ammo.com not read ({exc})")
        try:
            text = ctx.get_text(
                urljoin(MILSURP_MUNITIONS, "wp-json/wc/store/v1/products?per_page=100")
            )
            found.milsurp = milsurp_offers(json.loads(text))
        except (Disallowed, ScrapeError, ValueError) as exc:
            found.notes.append(f"Milsurp Munitions not read ({exc})")
    if "reloading" in parts:
        try:
            found.bullets = grafs_catalog(ctx)
        except (Disallowed, ScrapeError) as exc:
            found.notes.append(f"Graf & Sons not read ({exc})")
        try:
            found.supplies = reloading.read_supplies(ctx)
        except (Disallowed, ScrapeError) as exc:
            found.notes.append(f"Graf & Sons' brass, primers and powder not read ({exc})")
    return found


def _price_calibers(
    session: Session,
    ctx: ScrapeContext,
    sources: Sources,
    now: datetime,
    log: Callable[[str], None],
    parts: Iterable[str] = PARTS,
) -> str:
    """Price every caliber for sale, for the parts asked for. Returns a summary."""
    parts = set(parts)
    priced = projectiles = brassed = whole = 0
    asked = for_sale(session)
    supplies = sources.supplies if "reloading" in parts else None
    brass: dict[str, list[reloading.Brass]] = {}
    if supplies is not None:
        reloading.store_supplies(session, supplies, now)
        brass = reloading.brass_by_caliber(session, supplies.brass)
        # Every caliber with a load entered, for sale here or not.
        for caliber in session.execute(select(Caliber)).scalars():
            reloading.price_load(session, caliber)
        session.commit()
    for caliber in asked:
        if "prices" in parts:
            try:
                priced += int(
                    bool(_factory(session, ctx, caliber, sources.pages, sources.milsurp, now))
                )
            except Disallowed as exc:
                # A robots.txt that changed its mind is an answer, not an error.
                sources.notes.append(f"stopped: {exc}")
                session.commit()
                break
        if "reloading" in parts and sources.bullets:
            projectiles += int(_projectiles(caliber, sources.bullets, now))
        if supplies is not None:
            brassed += int(reloading.price_brass(caliber, brass.get(caliber.name), now))
            whole += int(reloading.reload_cost(caliber) is not None)
        session.commit()
        log(
            f"  {caliber.name}: factory {caliber.factory_cpr or '-'} "
            f"({caliber.factory_source or 'none'}), projectile {caliber.projectile_cost or '-'}, "
            f"brass {caliber.brass_cost or '-'}, reloaded {reloading.reload_cost(caliber) or '-'}"
        )
    counts = []
    if "prices" in parts:
        counts.append(f"{priced} with factory prices")
    if "reloading" in parts:
        counts.append(f"{projectiles} with projectile prices")
    if supplies is not None:
        counts.append(
            f"{brassed} with new brass, {whole} with a whole reloaded round "
            f"({len(supplies.powders)} powders, {len(supplies.primers)} primers in stock)"
        )
    head = f"{len(asked)} calibers for sale: {', '.join(counts)}"
    return "; ".join([head, *sources.notes])


def refresh(
    session: Session,
    ctx: ScrapeContext,
    *,
    fetch: wikipedia.Fetch | None = None,
    log: Callable[[str], None] = print,
    parts: Iterable[str] = PARTS,
    reread: bool = False,
) -> str:
    """One refresh of *parts* (all of them by default). Returns its summary,
    also kept on the settings row.

    Wikipedia first (proposals for calibers without an article, and the facts
    of any not yet read -- or of every one, with *reread*), so the weights the
    prices are measured against are current; then Lee's catalog; then, per
    caliber for sale, the factory ammunition and the projectiles.
    """
    started = time.monotonic()
    parts = tuple(p for p in PARTS if p in set(parts))
    row = settings(session)
    row.requested_at = None
    row.requested_parts = None
    session.commit()
    now = utcnow()
    try:
        notes = []
        if "wikipedia" in parts and fetch is not None:
            wikipedia.run(session, fetch, kinds=("caliber",), log=log)
            if reread:
                for caliber in session.execute(
                    select(Caliber).where(Caliber.wikipedia_url.is_not(None))
                ).scalars():
                    caliber.wikipedia_read_at = None
                session.commit()
            notes.append(f"Wikipedia: {refresh_articles(session, fetch, log=log)} articles read")
        if "reloading" in parts:
            notes.append(_refresh_lee(session, ctx, now))
        if "prices" in parts or "reloading" in parts:
            ctx.keep_at_least(AMMO_COM, 5.0)
            ctx.keep_at_least(GRAFS, 5.0)
            sources = _sources(session, ctx, parts)
            sources.notes[:0] = notes
            summary = _price_calibers(session, ctx, sources, now, log, parts)
        else:
            summary = "; ".join(notes) or "Nothing to do"
        status, error = "ok", None
    except Exception as exc:  # recorded where the Caliber data page shows it
        session.rollback()
        summary, status, error = f"Failed: {exc}", "failed", str(exc)[:500]
        log(summary)
    row = settings(session)
    row.last_status, row.last_error = status, error
    row.last_run_at = now
    row.last_parts = ",".join(parts)
    if parts == PARTS:
        row.last_full_at = now
    row.last_summary = summary[:500]
    row.last_seconds = round(time.monotonic() - started, 1)
    session.commit()
    return summary


def facts(session: Session, name: str) -> Caliber | None:
    """The armory caliber a name means, for the Ammunition information panel."""
    canonical = armory.canonical_caliber(session, name) or name
    return session.execute(select(Caliber).where(Caliber.name == canonical)).scalars().first()
