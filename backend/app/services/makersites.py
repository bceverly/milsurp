"""Reading the makers' own sites: each model's variants, with MSRP and UPC.

Slice 3 of "New-gun prices, and the makers' own pages" (ROADMAP.md). For a
model in modern production, the maker's site says which versions are made --
calibers, barrels, finishes -- what each lists for and its UPC. One reader per
maker, because no two sites agree on where that lives, under every rule a scan
follows: robots.txt, the request delay, the cooldown register, through
``ScrapeContext``.

**What a reader finds arrives as pending variants**, for somebody to approve on
the model's dialog in the Armory -- never as facts. A variant already known by
its maker's part number or UPC is brought up to date instead: its MSRP and its
page, which change and are the maker's to state.

Readers so far (measured 2026-10-11):

* **Ruger** -- every product line has a ``models.html`` of model cards (model
  number, caliber, barrel, MSRP) and a spec sheet per model with the UPC and
  the finish. robots.txt allows all of it.
* **Smith & Wesson** -- two category pages carry the whole handgun catalog;
  see :class:`SmithWessonReader`.
* **Kimber** -- a sitemap of every product page, and a page per product; see
  :class:`KimberReader`.
* **Walther** -- a product grid per line; see :class:`WaltherReader`.

Kimber's and Walther's terms of use forbid automated collection; reading them
anyway, by hand and lightly, was decided on 2026-10-11 (ROADMAP.md).

Measured and not built, with the reason, in ROADMAP.md: Taurus answers its
own Store API and sitemap with 403, and Sig Sauer with a Cloudflare challenge
-- both bot controls, so neither is read; Springfield asks for 300 seconds
between requests; Glock publishes no MSRP.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ArmoryStatus,
    Caliber,
    FirearmKind,
    FirearmModel,
    Manufacturer,
    ModelVariant,
)
from ..scrapers.base import ScrapeContext, ScrapeError, text_of
from . import armory, audit, classify, frames, variants


@dataclass(frozen=True)
class Found:
    """One variant as a maker's site describes it."""

    maker_part: str
    label: str
    caliber: str | None = None
    barrel_inches: float | None = None
    finish: str | None = None
    upc: str | None = None
    msrp: float | None = None
    url: str | None = None
    #: Where the site states it outright -- Armscor's FS, MS and CS -- rather
    #: than leaving it to be read from the label.
    frame_size: str | None = None
    #: What it is, where the site says: Armscor's specification table names a
    #: gauge or a series of revolvers or rifles. For a proposed model's kind.
    kind: FirearmKind | None = None
    #: Where it was read: the maker's own site, or a retailer's catalog for a
    #: maker whose site cannot be read (:class:`BudsReader`).
    source: str = "maker-site"


def _money(text: str | None) -> float | None:
    found = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", text or "")
    try:
        return float(found.group(1).replace(",", "")) if found else None
    except ValueError:
        return None


def _digits(text: str | None) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    return digits if 8 <= len(digits) <= 14 else None


def _on_site(url: str | None, domain: str) -> bool:
    """Whether *url* is on *domain* or one of its subdomains, by its host.

    Not ``domain in url``, which "https://elsewhere.example/?ruger.com" passes
    -- the substring check CodeQL flagged (alerts #46 and #47, 2026-10-12).
    """
    host = (urlsplit(url or "").hostname or "").lower()
    return host == domain or host.endswith(f".{domain}")


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class RugerReader:
    """ruger.com: a ``models.html`` per product line, a spec sheet per model."""

    maker = "Ruger"
    home = "https://ruger.com/"

    def models_pages(self, ctx: ScrapeContext, model: FirearmModel) -> list[str]:
        """The product line's model pages: the model's own recorded page, or
        the lines in Ruger's navigation whose name is the model's."""
        if model.maker_url and _on_site(model.maker_url, "ruger.com"):
            return [model.maker_url]
        return self.navigation_pages(ctx, model)

    def navigation_pages(self, ctx: ScrapeContext, model: FirearmModel) -> list[str]:
        soup = BeautifulSoup(ctx.get_text(self.home), "html.parser")
        wanted = {
            _compact(re.sub(r"\bruger\b", "", spelling, flags=re.I)) for spelling in model.spellings
        }
        pages: list[str] = []
        # A product line is an item of the navigation, named by its first link
        # ("Ruger SP101"), with its model pages beneath it ("Standard", "Match
        # Champion").
        for line in soup.select("li"):
            first = line.find("a")
            if first is None:
                continue
            name = _compact(re.sub(r"\bruger\b", "", text_of(first), flags=re.I))
            if name not in wanted:
                continue
            for link in line.select('a[href$="/models.html"]'):
                href = urljoin(self.home, str(link.get("href")))
                if href not in pages:
                    pages.append(href)
        # A line renamed for a new generation is named in the menu by its
        # variety alone ("Standard", "Ranch"), but its address keeps the
        # model's name: americanRifleGenII, americanRifleRanchGenII (the
        # Ruger American Rifle, 2026-10-13).
        for link in soup.select('a[href$="/models.html"]'):
            href = urljoin(self.home, str(link.get("href")))
            line_name = _compact(href.rsplit("/", 2)[-2])
            if href not in pages and any(
                len(name) >= 5 and line_name.startswith(name) for name in wanted
            ):
                pages.append(href)
        return pages

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, _siblings: list[FirearmModel]
    ) -> list[Found]:
        found = self._cards(ctx, model, self.models_pages(ctx, model))
        if not found and model.maker_url and _on_site(model.maker_url, "ruger.com"):
            # A recorded page Ruger has since dropped answers 200 with "Page
            # Not Found" and no cards (EC9S, SR22, 2026-10-13): look in the
            # navigation as if no page were recorded.
            found = self._cards(ctx, model, self.navigation_pages(ctx, model))
        return found

    def _cards(self, ctx: ScrapeContext, model: FirearmModel, pages: list[str]) -> list[Found]:
        found: list[Found] = []
        for page in pages:
            soup = BeautifulSoup(ctx.get_text(page), "html.parser")
            for card in soup.select(".product-thumb"):
                facts = _pairs(card)
                number = facts.get("model")
                if not number:
                    continue
                spec = card.select_one('a[href*="specSheets"]')
                spec_url = urljoin(page, str(spec.get("href"))) if spec else None
                sheet = _spec_sheet(ctx, spec_url) if spec_url else {}
                stated = facts.get("barrel length") or sheet.get("barrel length") or ""
                barrel = variants.read_barrel(stated, long_gun=True) or variants.read_barrel(stated)
                finish = variants.normalize_finish(
                    sheet.get("slide finish") or sheet.get("finish") or sheet.get("cylinder finish")
                )
                caliber = facts.get("caliber")
                found.append(
                    Found(
                        maker_part=number,
                        label=" ".join(
                            part
                            for part in (
                                model.name,
                                caliber,
                                f'{barrel:g}"' if barrel else None,
                                finish,
                                f"(Model {number})",
                            )
                            if part
                        ),
                        caliber=caliber,
                        barrel_inches=barrel,
                        finish=finish,
                        upc=_digits(sheet.get("upc")),
                        msrp=_money(facts.get("msrp") or sheet.get("suggested retail")),
                        url=spec_url or page,
                    )
                )
        return found


def _pairs(card: Tag) -> dict[str, str]:
    """A model card's "Label: | value" cells, by lower-case label."""
    cells = [text_of(td) for td in card.select("td")]
    return {
        cells[i].rstrip(":").strip().lower(): cells[i + 1]
        for i in range(0, len(cells) - 1, 2)
        if cells[i].endswith(":")
    }


#: The labels a Ruger spec sheet states, each followed by its value.
_SHEET_LABELS = (
    "UPC",
    "Suggested Retail",
    "Slide Finish",
    "Cylinder Finish",
    "Finish",
    "Barrel Length",
)


def _spec_sheet(ctx: ScrapeContext, url: str) -> dict[str, str]:
    """A spec sheet's UPC, retail price and finishes, by lower-case label."""
    try:
        text = " ".join(
            BeautifulSoup(ctx.get_text(url), "html.parser").get_text(" ", strip=True).split()
        )
    except ScrapeError:
        return {}
    found = {}
    for label in _SHEET_LABELS:
        match = re.search(
            rf"(?<![A-Za-z]){re.escape(label)}:?\s+(.+?)(?=\s+(?:{'|'.join(_SHEET_LABELS)}|"
            r"Width|Sights|Grip|Barrel Material|Slide Material|Capacity|Weight|Height|Length)\b|$)",
            text,
        )
        if match:
            found[label.lower()] = match.group(1).strip()[:120]
    return found


def _tokens(text: str, drop: frozenset[str] = frozenset()) -> list[str]:
    """Words of a name in order, letters and digits apart: "M&P®9" is m, p, 9."""
    plain = re.sub(r"[®™]", "", text.lower())
    return [t for t in re.findall(r"[a-z]+|\d+", plain) if t not in drop]


def _carries(name: list[str], wanted: list[str]) -> bool:
    """Whether a product name carries a model's name, in order.

    Words may have others between them -- "M&P Shield" is in "M&P 9 SHIELD
    PLUS" -- but a number must follow the word before it directly: "Model 10"
    is not in "MODEL 610 10MM", whose 10 belongs to the cartridge.
    """
    at = -1
    for token in wanted:
        if token.isdigit():
            if at + 1 < len(name) and name[at + 1] == token:
                at += 1
                continue
            if at == -1 and token in name:
                at = name.index(token)
                continue
            return False
        try:
            at = name.index(token, at + 1)
        except ValueError:
            return False
    return True


class SmithWessonReader:
    """smith-wesson.com: a storefront whose category pages carry every product.

    ``/products/pistols``, ``/products/revolvers`` and ``/products/rifles`` each
    embed their whole catalog in the page's ``__NEXT_DATA__`` -- 275 pistols
    and 129 revolvers when first measured, rifles added on 2026-10-13 -- with the name, the price (S&W's MSRP), the
    UPC and the item number. Barrel and finish are in the name ("M&P9 M2.0
    METAL 4.25 INCH TUNGSTEN GRAY"). Each product goes to the flagged S&W model
    whose name it carries most specifically -- an "M&P9 Shield Plus" is a
    Shield, not an M&P9.

    **Never to a catch-all** (2026-10-14). A spelling with no number and no
    word of its own -- the M&P M2.0's "S&W M&P |", which is m and p -- names a
    family, not a gun, and it claimed the M&P 5.7 and the M&P22X, which have
    no model, so an M2.0 listing would have shown their prices as its own
    versions. A product nothing names specifically is left to :meth:`unowned`,
    which proposes a model for it.
    """

    maker = "Smith & Wesson"
    home = "https://www.smith-wesson.com/"
    # Rifles since 2026-10-13: the M&P FPC carbine is one.
    CATEGORIES = ("pistols", "revolvers", "rifles")
    _MAKER_WORDS = frozenset({"smith", "wesson", "s", "w"})

    def __init__(self) -> None:
        self._catalog: list[dict[str, Any]] | None = None

    def catalog(self, ctx: ScrapeContext) -> list[dict[str, Any]]:
        if self._catalog is None:
            found: dict[str, dict[str, Any]] = {}
            for category in self.CATEGORIES:
                text = ctx.get_text(urljoin(self.home, f"products/{category}"))
                block = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.S)
                if not block:
                    continue
                for record in _records(json.loads(block.group(1))):
                    found.setdefault(str(record.get("upc") or record.get("id")), record)
            self._catalog = list(found.values())
        return self._catalog

    def _owner(self, record: dict[str, Any], models: list[FirearmModel]) -> FirearmModel | None:
        have = _tokens(str(record.get("name") or ""))
        best: tuple[int, int, FirearmModel] | None = None
        for model in models:
            for spelling in model.spellings:
                need = _tokens(spelling, self._MAKER_WORDS)
                if need and _specific(need) and _carries(have, need):
                    score = (len(need), len(_compact(spelling)), model)
                    if best is None or score[:2] > best[:2]:
                        best = score
        return best[2] if best else None

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, siblings: list[FirearmModel]
    ) -> list[Found]:
        return [
            self._found(record)
            for record in self.catalog(ctx)
            if self._owner(record, siblings) is model
        ]

    def unowned(self, ctx: ScrapeContext, siblings: list[FirearmModel]) -> dict[str, list[Found]]:
        """The products no model names, by the product line each belongs to."""
        lines: dict[str, list[Found]] = {}
        for record in self.catalog(ctx):
            if self._owner(record, siblings) is not None:
                continue
            line = _line_name(str(record.get("name") or ""))
            if line:
                lines.setdefault(line, []).append(self._found(record))
        return lines

    def _found(self, record: dict[str, Any]) -> Found:
        name = re.sub(r"[®™]", "", str(record.get("name") or "")).strip()
        path = (
            (record.get("custom_url") or {}).get("url")
            if isinstance(record.get("custom_url"), dict)
            else None
        )
        price = record.get("price")
        return Found(
            maker_part=str(record.get("sku") or record.get("id")),
            label=name[:200],
            caliber=classify.extract_caliber(name),
            barrel_inches=variants.read_barrel(name.replace(" INCH", '"')),
            finish=variants.read_finish(name),
            upc=_digits(str(record.get("upc") or "")),
            msrp=float(price) if isinstance(price, int | float) and price > 0 else None,
            url=urljoin(self.home, f"product{path}") if path else None,
        )


def _specific(need: list[str]) -> bool:
    """Whether a model's spelling names a gun rather than a family: a number
    ("M&P9", "M2.0") or a word of three letters or more ("Shield")."""
    return any(token.isdigit() or len(token) >= 3 for token in need)


#: Where a product's name stops naming its line and starts describing the
#: version: a length, a capacity, a color, an option, a bundle.
_LINE_ENDS = re.compile(
    r"^(?:\d+(?:\.\d+)?(?:\"|IN|INCH)?|\d+RD|\d+\"|\d+MM|\.\d+|WITH|W/|NO|THUMB|SAFETY|TS|NTS|CA|"
    r"COMPLIANT|OPTICS?|OR|READY|THREADED|BARREL|PISTOL|REVOLVER|RIFLE|CARBINE|CARRY|"
    r"COMP|BUNDLE|KIT|BLACK|FDE|OD|GREEN|GRAY|GREY|SILVER|STAINLESS|BLUE|BRONZE|"
    r"MIDNIGHT|BURNT|TUNGSTEN|PINK|PURPLE|TEAL|ROSE|GOLD|MULTICAM|TWO-TONE|2-TONE|"
    r"ENGRAVED|LASER|LASERGRIPS?|INTEGRATED|ROUNDS?|SERIES|EDITION|[/-])$",
    re.I,
)


def _line_name(product: str) -> str | None:
    """A product's line: "M&P 5.7 10RD COMPLIANT" is the M&P 5.7, "M&P22X" the
    M&P22X, "PERFORMANCE CENTER MODEL 940-3" the Model 940-3. Up to three
    words, from the start of the name to the first that describes a version."""
    # A mark becomes a space: "M&P®5.7" is the M&P 5.7, not an M&P5.
    plain = " ".join(re.sub(r"\[[^\]]*\]|[®™]", " ", product).split())
    plain = re.sub(
        r"^(?:PERFORMANCE CENTER\s+|S&W\s+|SMITH\s*&\s*WESSON\s+)+", "", plain, flags=re.I
    )
    words: list[str] = []
    for word in plain.split():
        # A bare number belongs to the line while its name is one word without
        # a number of its own: "M&P 5.7", "MODEL 940" -- but "SD40 2.0" is the
        # SD40's version 2.0, and "M&P22X 10RD" a capacity.
        if re.fullmatch(r"[\d.-]+", word) and len(words) == 1 and not re.search(r"\d", words[0]):
            words.append(word)
        elif _LINE_ENDS.match(word):
            break
        else:
            words.append(word)
        if len(words) == 3:
            break
    if not words:
        return None
    return " ".join(w.capitalize() if w.isalpha() and len(w) > 3 else w for w in words)


def _records(data: Any) -> list[dict[str, Any]]:
    """Every product record in a page's data: a dict with a name, price and UPC."""
    found: list[dict[str, Any]] = []
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "upc" in node and "price" in node and "name" in node:
                found.append(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def _starts_at(have: list[str], need: list[str]) -> int | None:
    """Where a name's words appear together, in order, or None."""
    for at in range(len(have) - len(need) + 1):
        if have[at : at + len(need)] == need:
            return at
    return None


def _earliest_owner(
    words: list[str], models: list[FirearmModel], drop: frozenset[str]
) -> FirearmModel | None:
    """The model whose name appears earliest in a product's name, and the
    longer name between two that start together.

    A maker names its products line first: "micro-9-stainless-raptor" is a
    Micro 9 finished like a Raptor, and "stainless-target-ii" is a Stainless
    Target II, not a Stainless II.
    """
    best: tuple[int, int, FirearmModel] | None = None
    for model in models:
        for spelling in model.spellings:
            need = _tokens(spelling, drop)
            at = _starts_at(words, need) if need else None
            if at is None:
                continue
            if best is None or (at, -len(need)) < best[:2]:
                best = (at, -len(need), model)
    return best[2] if best else None


class KimberReader:
    """kimberamerica.com: a sitemap of product pages, and a page per product.

    The category pages are tiles linking to sub-categories and carry no
    prices, but ``sitemap.xml`` lists every product at the top level of the
    site (``/micro-9-esv-black-1``) -- one request for the catalog. A product
    page states its MSRP, calibers, specifications (barrel length, slide or
    barrel finish), product number and usually UPC. The configurable "family"
    pages (``/custom-ii-walnut``: $0.00, no specifications) carry no product
    number and are passed over. Only pages whose address names the model are
    asked for, and each goes to the model named earliest in it.
    """

    maker = "Kimber"
    home = "https://www.kimberamerica.com/"
    _MAKER_WORDS = frozenset({"kimber"})

    def __init__(self) -> None:
        self._slugs: list[str] | None = None

    def slugs(self, ctx: ScrapeContext) -> list[str]:
        if self._slugs is None:
            text = ctx.get_text(urljoin(self.home, "sitemap.xml"))
            found = []
            for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text):
                path = loc.removeprefix(self.home.rstrip("/")).strip("/")
                if path and "/" not in path and path not in found:
                    found.append(path)
            self._slugs = found
        return self._slugs

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, siblings: list[FirearmModel]
    ) -> list[Found]:
        found = []
        for slug in self.slugs(ctx):
            words = _tokens(slug.replace("-", " "))
            if _earliest_owner(words, siblings, self._MAKER_WORDS) is not model:
                continue
            url = urljoin(self.home, slug)
            try:
                product = kimber_product(ctx.get_text(url), url)
            except ScrapeError:
                continue
            if product is not None:
                found.append(product)
        return found


def _label(maker: str, name: str, caliber: str | None, number: str) -> str:
    """'Kimber Micro 9 Stainless 9 mm (3700482)': the caliber only when the
    product's name does not already say it."""
    stated = caliber if caliber and _compact(caliber) not in _compact(name) else None
    return " ".join(p for p in (f"{maker} {name}", stated, f"({number})") if p)[:200]


def _lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return [" ".join(line.split()) for line in soup.get_text("\n").splitlines() if line.strip()]


def _after(lines: list[str], label: str) -> str | None:
    """The value of the first "Label: value" line, or the line after "Label"."""
    for at, line in enumerate(lines):
        if line.lower().startswith(label.lower() + ":"):
            value = line.split(":", 1)[1].strip()
            return value or (lines[at + 1] if at + 1 < len(lines) else None)
        if line.lower() == label.lower() and at + 1 < len(lines):
            return lines[at + 1]
    return None


def _section(lines: list[str], heading: str, label: str) -> str | None:
    """A labeled value within a specification section: the barrel's length."""
    for at, line in enumerate(lines):
        if line == heading:
            return _after(lines[at + 1 : at + 6], label)
    return None


def kimber_product(html: str, url: str) -> Found | None:
    """One Kimber product page, or None when it is not a single product."""
    lines = _lines(html)
    text = "\n".join(lines)
    part = re.search(r"Product #:\s*([A-Za-z0-9-]+)", text)
    if not part:
        return None
    title = BeautifulSoup(html, "html.parser").title
    name = (title.get_text() if title else "").split("|")[0].strip()
    msrp = _money(_after(lines, "MSRP"))
    caliber = _after(lines, "Calibers")
    stated = _section(lines, "Barrel", "Length (inches)")
    barrel = None
    if stated:
        try:
            barrel = float(stated.split()[0])
        except ValueError:
            barrel = None
    finish_text = _section(lines, "Slide", "Finish") or _section(lines, "Barrel", "Finish")
    upc = re.search(r"UPC:\s*(\d{8,14})", text)
    number = part.group(1)
    return Found(
        maker_part=number,
        label=_label("Kimber", name, caliber, number),
        caliber=caliber,
        barrel_inches=barrel,
        finish=variants.normalize_finish(finish_text) or variants.read_finish(name),
        upc=upc.group(1) if upc else None,
        msrp=msrp or None,
        url=url,
    )


class WaltherReader:
    """waltherarms.com: a product grid per line, from the site's navigation.

    A line's page (``/defense/pdp``) and the pages under it that the
    navigation names (``/defense/pdp/pro``, ``/defense/pdp/two-tone`` ...) are
    grids of J2Commerce product tiles, each with the product's name (barrel
    and finish written into it: 'PDP Two-Tone Compact 4" FDE'), its MSRP, the
    item number and the caliber. The tiles alone are read -- one request a
    page; the UPC is only on the product's own page, and the item number is
    enough to find a new price by.
    """

    maker = "Walther"
    home = "https://waltherarms.com/"
    _MAKER_WORDS = frozenset({"walther"})

    def __init__(self) -> None:
        self._nav: list[str] | None = None

    def nav(self, ctx: ScrapeContext) -> list[str]:
        if self._nav is None:
            soup = BeautifulSoup(ctx.get_text(self.home), "html.parser")
            found: list[str] = []
            for link in soup.select('a[href^="/"]'):
                href = str(link.get("href")).split("#")[0].split("?")[0].rstrip("/")
                if href.count("/") >= 2 and href not in found:
                    found.append(href)
            self._nav = found
        return self._nav

    def line_pages(self, ctx: ScrapeContext, model: FirearmModel) -> list[str]:
        if model.maker_url and _on_site(model.maker_url, "waltherarms.com"):
            return [model.maker_url]
        wanted = {_compact(" ".join(_tokens(s, self._MAKER_WORDS))) for s in model.spellings}
        lines = [
            href
            for href in self.nav(ctx)
            if href.count("/") == 2 and _compact(href.rsplit("/", 1)[1]) in wanted
        ]
        return [
            urljoin(self.home, href.lstrip("/"))
            for line in lines
            for href in self.nav(ctx)
            if (href == line or href.startswith(line + "/")) and "feature" not in href
        ]

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, _siblings: list[FirearmModel]
    ) -> list[Found]:
        found: dict[str, Found] = {}
        for page in self.line_pages(ctx, model):
            try:
                text = ctx.get_text(page)
            except ScrapeError:
                # One sub-line gone from the site costs its own tiles only.
                continue
            for product in walther_tiles(text, page):
                found.setdefault(product.maker_part, product)
        return list(found.values())


def walther_tiles(html: str, page: str) -> list[Found]:
    """Every product tile on a Walther line page."""
    found = []
    for tile in BeautifulSoup(html, "html.parser").select(".j2commerce-product-item"):
        title = tile.select_one(".j2commerce-product-title a")
        if title is None:
            continue
        specs = {}
        for item in tile.select("ul.uk-specs li"):
            words = " ".join(item.get_text(" ", strip=True).split())
            for label in ("Item Number", "Caliber", "Capacity", "Barrel Length", "Finish"):
                if words.startswith(label):
                    specs[label] = words[len(label) :].strip()
        number = specs.get("Item Number")
        if not number:
            continue
        name = " ".join(title.get_text(" ", strip=True).split())
        caliber = specs.get("Caliber")
        price = tile.select_one(".j2commerce-product-price")
        found.append(
            Found(
                maker_part=number,
                label=_label("Walther", name, caliber, number),
                caliber=caliber,
                barrel_inches=variants.read_barrel(specs.get("Barrel Length") or name),
                finish=variants.normalize_finish(specs.get("Finish")) or variants.read_finish(name),
                msrp=_money(price.get_text()) if price else None,
                url=urljoin(page, str(title.get("href"))),
            )
        )
    return found


class ArmscorReader:
    """armscor.com, Rock Island Armory: a page per product, listed in its sitemap.

    Added on 2026-10-15. HubSpot pages under ``/firearms-list/`` -- 256 in
    the sitemap that day -- each with a specification table: the SKU (the
    model number listings use, "Rock Island Armory 52000 Pro Ultra Match"),
    the series, caliber, barrel, finish and the US MSRP; and a notice where
    the product is discontinued, which is passed over, as a current site is
    what says a model is still made. The catalog is read once a run.

    **A product goes to its line, and its line to a model.** Armscor's names
    do not name the model the way Kimber's do ("PRO Ultra Match 6" 45ACP 8rd"
    is a 1911), so a product's line comes from its series: every 1911 series
    -- GI, ROCK, TAC, PRO, TCM, XT, Baby Rock -- is the "1911", which the
    armory's Rock Island 1911 answers to; anything else is the model its name
    starts with ("STK200 9MM 15rd", "VR80 5rd 12GA", "RIA 5.0 SP"). A product
    named by no model -- "All Generations 12GA Pump Action", "Single Shot
    12GA" -- has no line and is not read. Nor is the Derya series: Derya's
    own guns, which Armscor distributes.

    A pistol's frame is in its name: FS is full size, MS mid size (a
    Commander's length, the armory's Compact), CS compact (an Officer's, its
    Subcompact), Baby Rock a micro 1911.
    """

    maker = "Rock Island Armory"
    home = "https://www.armscor.com/"
    _MAKER_WORDS = frozenset({"rock", "island", "armory", "armscor"})
    #: The series of 1911s, as the specification table writes them.
    ONE_NINE_ELEVEN_SERIES = frozenset({"gi", "rock", "tac", "pro", "tcm", "xt", "baby rock"})
    #: Another maker's guns, sold by Armscor.
    NOT_ARMSCOR = frozenset({"derya"})
    _FRAMES = (
        (re.compile(r"\bFS\b"), frames.FULL),
        (re.compile(r"\bMS\b"), frames.COMPACT),
        (re.compile(r"\bCS\b"), frames.SUBCOMPACT),
        (re.compile(r"\bbaby\s+rock\b|\bBBR\b", re.I), frames.MICRO),
    )

    def __init__(self) -> None:
        self._catalog: list[tuple[str, Found]] | None = None

    def catalog(self, ctx: ScrapeContext) -> list[tuple[str, Found]]:
        """Every current product with a line, as ``(line, found)``."""
        if self._catalog is None:
            sitemap = ctx.get_text(urljoin(self.home, "sitemap.xml"))
            pages = [
                loc
                for loc in dict.fromkeys(re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap))
                if "/firearms-list/" in loc and _on_site(loc, "armscor.com")
            ]
            found: dict[str, tuple[str, Found]] = {}
            for page in pages:
                try:
                    product = armscor_product(ctx.get_text(page), page)
                except ScrapeError:
                    # One page gone from the site costs that product only.
                    continue
                if product is not None:
                    found.setdefault(product[1].maker_part, product)
            self._catalog = list(found.values())
        return self._catalog

    def _owner(self, line: str, models: list[FirearmModel]) -> FirearmModel | None:
        """The model whose name is the line's, as _propose_models decides it."""
        words = _tokens(line, self._MAKER_WORDS)
        best: tuple[int, FirearmModel] | None = None
        for model in models:
            for spelling in model.spellings:
                need = _tokens(spelling, self._MAKER_WORDS)
                if (
                    need
                    and _specific(need)
                    and words[: len(need)] == need
                    and (best is None or len(need) > best[0])
                ):
                    best = (len(need), model)
        return best[1] if best else None

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, siblings: list[FirearmModel]
    ) -> list[Found]:
        return [found for line, found in self.catalog(ctx) if self._owner(line, siblings) is model]

    def unowned(self, ctx: ScrapeContext, siblings: list[FirearmModel]) -> dict[str, list[Found]]:
        lines: dict[str, list[Found]] = {}
        for line, found in self.catalog(ctx):
            if self._owner(line, siblings) is None:
                lines.setdefault(line, []).append(found)
        return lines

    @classmethod
    def frame_of(cls, name: str) -> str | None:
        return next((size for pattern, size in cls._FRAMES if pattern.search(name)), None)


def armscor_line(name: str, series: str) -> str | None:
    """The line an Armscor product belongs to, or None for one no model names."""
    family = series.strip().lower()
    if family in ArmscorReader.NOT_ARMSCOR:
        return None
    if family in ArmscorReader.ONE_NINE_ELEVEN_SERIES or re.search(
        r"\b(?:M?1911)\b|\bM1911", name, re.I
    ):
        return "1911"
    if re.match(r"(?:RIA\s*|US)5\.0", name, re.I):
        return "RIA 5.0"
    if re.match(r"MAPP\b", name, re.I):
        return "MAPP"
    first = name.split(maxsplit=1)[0] if name.split() else ""
    # A model's own name has a number in it: STK200, VR80, M206, TM22, PK-12.
    first = first.strip('",')
    return first.upper() if re.search(r"\d", first) and len(first) <= 12 else None


def _armscor_kind(series: str, caliber: str | None, action: str | None) -> FirearmKind:
    family = series.strip().lower()
    if re.search(r"\d+\s*GA\b", caliber or "", re.I):
        return FirearmKind.SHOTGUN
    if "revolver" in family:
        return FirearmKind.REVOLVER
    if family in {"rifles", "tm22", "youth"} or (action or "").lower() in {"bolt", "lever"}:
        return FirearmKind.RIFLE
    return FirearmKind.PISTOL


def armscor_product(html: str, url: str) -> tuple[str, Found] | None:
    """One Armscor product page, as ``(line, found)``; None when it is
    discontinued, has no SKU, or belongs to no line."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one(".discontinued-notice"):
        return None
    specs: dict[str, str] = {}
    for row in soup.select("table.spec-table tr"):
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.select("td")]
        if len(cells) == 2 and cells[0]:
            specs[cells[0]] = cells[1]
    heading = soup.select_one("h1")
    name = " ".join(heading.get_text(" ", strip=True).split()) if heading else ""
    number = specs.get("SKU")
    if not number or not name:
        return None
    line = armscor_line(name, specs.get("Series", ""))
    if line is None:
        return None
    caliber = specs.get("Caliber")
    kind = _armscor_kind(specs.get("Series", ""), caliber, specs.get("Action"))
    return line, Found(
        maker_part=number,
        label=_label("Rock Island Armory", name, caliber, number),
        caliber=caliber,
        barrel_inches=variants.read_barrel(specs.get("Barrel") or ""),
        finish=variants.normalize_finish(specs.get("Finish")) or variants.read_finish(name),
        msrp=_money(specs.get("MSRP (US)")) or None,
        url=url,
        frame_size=ArmscorReader.frame_of(name) if kind == FirearmKind.PISTOL else None,
        kind=kind,
    )


#: Bud's brand names where none of the armory's spellings of the maker is one.
BUDS_BRANDS = {
    "Heckler Koch": "HK",
    "Heckler & Koch": "HK",
    "Springfield": "Springfield Armory",
    "Kahr": "Kahr Arms",
    "Kel-Tec": "Kel-Tec Cnc Industries Inc.",
    "Steyr": "Steyr Arms",
    "Israel Weapon Industries": "IWI",
    "LWRC": "LWRCI",
    "SAR Arms": "SAR USA",
    "Savage": "Savage Arms",
}
#: The brands Bud's filters by, as its handgun page listed them on 2026-10-15.
BUDS_BRAND_NAMES = frozenset(
    {
        "Arex",
        "Auto Ordnance",
        "BUL Armory",
        "Beretta",
        "Bersa",
        "Bond Arms",
        "Browning",
        "CZ",
        "Canik",
        "Century Arms",
        "Charter Arms",
        "Chiappa",
        "Colt",
        "Dan Wesson",
        "Daniel Defense",
        "Diamondback Firearms",
        "European American Armory",
        "FN",
        "Girsan",
        "Glock",
        "HK",
        "Heritage Manufacturing",
        "Hi-Point",
        "Howa",
        "IWI",
        "KRISS",
        "Kahr Arms",
        "Kel-Tec Cnc Industries Inc.",
        "Kimber",
        "LWRCI",
        "Magnum Research",
        "Mossberg",
        "North American Arms",
        "Remington",
        "Rossi",
        "SAR USA",
        "SCCY",
        "Savage Arms",
        "Shadow Systems",
        "Sig Sauer",
        "Springfield Armory",
        "Staccato",
        "Steyr Arms",
        "Stoeger",
        "Taurus",
        "Tisas",
        "Uberti",
        "Wilson Combat",
    }
)


def buds_brand(firm: Manufacturer) -> str | None:
    """The brand Bud's Gun Shop files a maker's guns under, or None."""
    for spelling in firm.spellings:
        if spelling in BUDS_BRANDS:
            return BUDS_BRANDS[spelling]
        for brand in BUDS_BRAND_NAMES:
            if _compact(brand) == _compact(spelling):
                return brand
    return None


@dataclass(frozen=True)
class BudsCard:
    """One product tile on a Bud's list page."""

    url: str
    name: str
    msrp: float | None
    price: float | None
    barrel_inches: float | None


class BudsReader:
    """budsgunshop.com: a retailer's catalog, for a maker whose own site cannot
    be read or does not say.

    Suggested on 2026-10-15, when the audit of a Glock listing with no MSRP and
    no street price found that 21 Glock models, 10 Sig Sauer, 17 Springfield
    and a dozen more makers' had no versions at all: Glock's own site states
    no price and no part number, and Sig Sauer's, H&K's and Mossberg's answer
    every request with a bot challenge. Bud's robots.txt allows its public
    pages, its llms.txt invites automated readers, and its terms say nothing
    against reading.

    **What is read.** The maker's in-stock handguns, rifles and shotguns,
    from ``/categories/firearms/<category>?brand=<brand>&availability=in
    stock`` a page at a time; each tile gives the product's page, its name,
    the MSRP Bud's strikes through and its own price. A product not yet
    recorded has its page read once: its structured data says whether it is
    new (a police trade-in is not), and gives the UPC and the maker's own
    model number (Glock's "P61950203"). A product already recorded is
    refreshed from its tile alone. The UPC is what then finds the street
    price at gun.deals, as for every other version. Only the products of the
    armory's models have their pages read, and :data:`PER_UNNAMED_LINE` of
    any other line's: a list page carries 24 products, and a product page
    one.

    **A product goes to the model it names.** "Glock 19 Gen6 Optic Ready" is
    a Glock 19; "Glock 19X V-Series" is not, since the X is part of the
    number, and is left to be proposed as a model of its own.
    """

    home = "https://www.budsgunshop.com/"
    CATEGORIES = (
        ("handguns", None),
        ("rifles", FirearmKind.RIFLE),
        ("shotguns", FirearmKind.SHOTGUN),
    )
    #: The most list pages read for one category: Glock's in-stock handguns
    #: were six on 2026-10-15.
    PAGES = 20
    #: Product pages read for a line no model names: enough for a proposed
    #: model to arrive with versions, not the whole line. Browning has one
    #: model still made here and a thousand products at Bud's; reading every
    #: one made the first run some 6,000 requests (measured 2026-10-16).
    PER_UNNAMED_LINE = 3

    def __init__(self, maker: str, brand: str) -> None:
        self.maker = maker
        self.brand = brand
        self._catalog: list[tuple[str, Found]] | None = None

    def _page(self, category: str, number: int) -> str:
        query = urlencode({"brand": self.brand, "availability": "in stock", "page": number})
        return urljoin(self.home, f"categories/firearms/{category}?{query}")

    def catalog(self, ctx: ScrapeContext, siblings: list[FirearmModel]) -> list[tuple[str, Found]]:
        """Every new in-stock product of the brand, as ``(name, found)``."""
        if self._catalog is not None:
            return self._catalog
        known = {
            v.maker_url: v
            for model in siblings
            for v in model.variants
            if v.maker_url and _on_site(v.maker_url, "budsgunshop.com")
        }
        found: dict[str, tuple[str, Found]] = {}
        unnamed: dict[str, int] = {}
        for category, kind in self.CATEGORIES:
            for number in range(1, self.PAGES + 1):
                try:
                    html = ctx.get_text(self._page(category, number))
                except ScrapeError:
                    # A category the brand has nothing in costs that category.
                    break
                cards = [c for c in buds_cards(html) if self._ours(c.name)]
                for card in cards:
                    if card.url in found:
                        continue
                    if self._owner(card.name, siblings) is None and card.url not in known:
                        # A line no model names: a few of its products, to
                        # propose it with; nothing at all for a name with
                        # no designation in it.
                        line = self.line(card.name)
                        if line is None or unnamed.get(line, 0) >= self.PER_UNNAMED_LINE:
                            continue
                        unnamed[line] = unnamed.get(line, 0) + 1
                    product = self._product(ctx, card, known.get(card.url), kind)
                    if product is not None:
                        found[card.url] = (card.name, product)
                if not cards or f"page={number + 1}" not in html:
                    break
        self._catalog = list(found.values())
        return self._catalog

    def _ours(self, name: str) -> bool:
        """Whether a tile is the brand's: a list page also shows featured
        products of other makers."""
        return _compact(name).startswith(_compact(self.brand)) or _compact(name).startswith(
            _compact(self.maker)
        )

    def _product(
        self,
        ctx: ScrapeContext,
        card: BudsCard,
        known: ModelVariant | None,
        kind: FirearmKind | None,
    ) -> Found | None:
        if known is not None and known.maker_part:
            # Recorded already, as new: the tile's MSRP is all that moves.
            return Found(
                maker_part=known.maker_part,
                label=known.label,
                upc=known.upc,
                msrp=card.msrp,
                url=card.url,
                source="budsgunshop",
            )
        try:
            page = buds_product(ctx.get_text(card.url))
        except ScrapeError:
            return None
        if page is None or not page["new"] or not page["model"]:
            return None
        if _compact(page["brand"]) not in {_compact(self.brand), _compact(self.maker)}:
            return None
        name = page["name"] or card.name
        found_kind = kind or (
            FirearmKind.REVOLVER
            if "/revolvers/" in card.url or re.search(r"\brevolver\b", name, re.I)
            else FirearmKind.PISTOL
        )
        return Found(
            maker_part=page["model"],
            label=f"{name} ({page['model']})"[:200],
            caliber=classify.extract_caliber(name),
            barrel_inches=page["barrel"] or card.barrel_inches,
            finish=variants.read_finish(name),
            upc=page["upc"],
            msrp=page["msrp"] or card.msrp,
            url=card.url,
            kind=found_kind,
            source="budsgunshop",
        )

    def _owner(self, name: str, models: list[FirearmModel]) -> FirearmModel | None:
        """The model whose name the product's carries, as a whole designation:
        "Glock 19" in "Glock 19 Gen6", not in "Glock 19X"."""
        name = _unglued(name)
        best: tuple[int, FirearmModel] | None = None
        for model in models:
            for spelling in model.spellings:
                words = spelling.split()
                if not words or not _specific(_tokens(spelling)):
                    continue
                pattern = r"(?<![\w])" + r"[\s-]*".join(map(re.escape, words)) + r"(?![\w])"
                if re.search(pattern, name, re.I) and (best is None or len(spelling) > best[0]):
                    best = (len(spelling), model)
        return best[1] if best else None

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, siblings: list[FirearmModel]
    ) -> list[Found]:
        return [
            found
            for name, found in self.catalog(ctx, siblings)
            if self._owner(name, siblings) is model
        ]

    def unowned(self, ctx: ScrapeContext, siblings: list[FirearmModel]) -> dict[str, list[Found]]:
        lines: dict[str, list[Found]] = {}
        for name, found in self.catalog(ctx, siblings):
            if self._owner(name, siblings) is None and (line := self.line(name)):
                lines.setdefault(line, []).append(found)
        return lines

    def line(self, name: str) -> str | None:
        """The designation a product's name starts with after the brand:
        "Glock 19X V-Series 9mm" is the 19X, "Sig Sauer P320 Spectre" the P320.
        None where it starts with a word and no number: a name, not a model."""
        rest = _unglued(name)
        for prefix in sorted({self.brand, self.maker}, key=len, reverse=True):
            if rest.lower().startswith(prefix.lower()):
                rest = rest[len(prefix) :]
                break
        first = rest.split()[0] if rest.split() else ""
        return first if re.search(r"\d", first) and len(first) <= 12 else None


def _unglued(name: str) -> str:
    """A series letter written onto the number: Bud's "Glock 17V" and "45V"
    are the 17 and 45 of the V series, "19XV" the 19X's."""
    return re.sub(r"(?<=[0-9X])V\b", " V", name)


def buds_cards(html: str) -> list[BudsCard]:
    """The product tiles on a Bud's list page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for pricing in soup.select('[id^="card-pricing-display-"]'):
        card: Tag | None = pricing
        for _ in range(8):
            card = card.parent if card is not None else None
            if card is None or card.select_one('a[href*="/products/"]'):
                break
        if card is None:
            continue
        link = card.select_one('a[href*="/products/"]')
        text = " ".join(card.get_text(" ", strip=True).split())
        names = [a.get_text(" ", strip=True) for a in card.select('a[href*="/products/"]')]
        name = max(names, key=len) if names else ""
        struck = pricing.select_one(".line-through")
        prices = [_money(s.get_text()) for s in pricing.select("span")]
        prices = [p for p in prices if p]
        barrel = re.search(r"Barrel Length:\s*([\d.]+)\s*inch", text)
        cards.append(
            BudsCard(
                url=str(link.get("href")).split("?")[0] if link else "",
                name=" ".join(name.split()),
                msrp=_money(struck.get_text()) if struck else None,
                price=prices[-1] if prices else None,
                barrel_inches=float(barrel.group(1)) if barrel else None,
            )
        )
    return [card for card in cards if card.url and card.name]


def buds_product(html: str) -> dict[str, Any] | None:
    """A Bud's product page: its name, brand, condition, UPC, the maker's model
    number, barrel length, and the MSRP struck through beside its price."""
    soup = BeautifulSoup(html, "html.parser")
    product: dict[str, Any] | None = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        for node in data.get("@graph", [data]) if isinstance(data, dict) else []:
            if isinstance(node, dict) and node.get("@type") == "Product":
                product = node
    if product is None:
        return None
    brand = product.get("brand")
    pdp = soup.select_one('[data-lazy-suspense="product-pdp"]')
    struck = pdp.select_one(".line-through") if pdp else None
    text = " ".join(soup.get_text(" ", strip=True).split())
    barrel = re.search(r"Barrel Length:\s*([\d.]+)\s*inch", text)
    return {
        "name": " ".join(str(product.get("name") or "").split()),
        "brand": str(brand.get("name") if isinstance(brand, dict) else brand or ""),
        "new": str(product.get("itemCondition") or "").endswith("NewCondition"),
        "upc": _digits(str(product.get("gtin12") or product.get("gtin") or "")),
        "model": str(product.get("model") or product.get("mpn") or "").strip()[:64] or None,
        "msrp": _money(struck.get_text()) if struck else None,
        "barrel": float(barrel.group(1)) if barrel else None,
    }


Reader = RugerReader | SmithWessonReader | KimberReader | WaltherReader | ArmscorReader | BudsReader
READERS: dict[str, Callable[[], Reader]] = {
    "Ruger": RugerReader,
    "Smith & Wesson": SmithWessonReader,
    "Kimber": KimberReader,
    "Walther": WaltherReader,
    "Rock Island Armory": ArmscorReader,
}


def _caliber_row(session: Session, text: str | None) -> Caliber | None:
    name = armory.canonical_caliber(session, text) if text else None
    if not name:
        return None
    return session.execute(select(Caliber).where(Caliber.name == name)).scalars().first()


def _elsewhere(session: Session, model: FirearmModel, item: Found) -> ModelVariant | None:
    """The same product already recorded under another of the maker's models.

    A variant an administrator moved to the model it belongs to stays there:
    the reader's choice of owner is a best guess from the product's name, and
    the M&P40 Shield M2.0 went to the M&P M2.0 until it was moved to the
    Shield on 2026-10-14. Without this the next run proposed it again, a
    duplicate under the model it had been moved from.
    """
    if not item.maker_part:
        return None
    makers = {maker.id for maker in model.manufacturers}
    for variant in session.execute(
        select(ModelVariant).where(
            ModelVariant.maker_part == item.maker_part, ModelVariant.model_id != model.id
        )
    ).scalars():
        if makers & {maker.id for maker in variant.model.manufacturers}:
            return variant
    return None


def record(session: Session, model: FirearmModel, found: Iterable[Found]) -> dict[str, int]:
    """Write what a reader found: new variants pending, known ones refreshed."""
    counts = {"proposed": 0, "refreshed": 0}
    by_part = {v.maker_part: v for v in model.variants if v.maker_part}
    by_upc = {v.upc: v for v in model.variants if v.upc}
    for item in found:
        known = (
            by_part.get(item.maker_part)
            or (by_upc.get(item.upc) if item.upc else None)
            or _elsewhere(session, model, item)
        )
        if known is not None:
            known.msrp = item.msrp if item.msrp is not None else known.msrp
            known.maker_url = item.url or known.maker_url
            known.upc = known.upc or item.upc
            known.maker_part = known.maker_part or item.maker_part
            known.frame_size = (
                known.frame_size
                or item.frame_size
                or frames.read(item.label, None, revolver=None)[0]
            )
            counts["refreshed"] += 1
            continue
        caliber = _caliber_row(session, item.caliber)
        if caliber is None and len(model.calibers) == 1:
            # The name did not say, and the model is made in one cartridge.
            caliber = model.calibers[0]
        model.variants.append(
            ModelVariant(
                label=item.label[:200],
                caliber_id=caliber.id if caliber else None,
                barrel_inches=item.barrel_inches,
                finish=item.finish,
                # From the label, as a listing's from its title: "PDP Full
                # Size 4.5"", "M&P9 M2.0 COMPACT". 2026-10-14.
                frame_size=item.frame_size or frames.read(item.label, None, revolver=None)[0],
                upc=item.upc,
                maker_part=item.maker_part,
                msrp=item.msrp,
                maker_url=item.url,
                source=item.source,
                status=ArmoryStatus.PENDING,
            )
        )
        by_part[item.maker_part] = model.variants[-1]
        counts["proposed"] += 1
    return counts


def _readers(session: Session, maker: str | None) -> list[tuple[Manufacturer, Reader]]:
    """Each maker with models still made, and the reader for it: its own
    site's where one is built, else Bud's Gun Shop's catalog where Bud's
    carries the brand (2026-10-15)."""
    firms = [
        firm
        for firm in session.execute(
            select(Manufacturer).where(
                Manufacturer.status == ArmoryStatus.APPROVED, Manufacturer.enabled.is_(True)
            )
        ).scalars()
        if not maker or firm.name.lower() == maker.lower()
    ]
    found: list[tuple[Manufacturer, Reader]] = []
    for firm in firms:
        make = READERS.get(firm.name)
        if make is not None:
            found.append((firm, make()))
        elif brand := buds_brand(firm):
            found.append((firm, BudsReader(firm.name, brand)))
    return found


def run(
    session: Session,
    ctx: ScrapeContext,
    *,
    maker: str | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Read every modern-production model of a maker with a reader."""
    totals = {
        "models": 0,
        "proposed": 0,
        "refreshed": 0,
        "unread": 0,
        "models_proposed": 0,
        "errors": 0,
    }
    modern = list(
        session.execute(
            select(FirearmModel).where(
                FirearmModel.modern_production.is_(True), FirearmModel.enabled.is_(True)
            )
        ).scalars()
    )
    plan = [
        (firm, reader, [model for model in modern if firm in model.manufacturers])
        for firm, reader in _readers(session, maker)
    ]
    plan = [(firm, reader, siblings) for firm, reader, siblings in plan if siblings]
    errored: set[str] = set()
    for at, (firm, reader, siblings) in enumerate(plan, start=1):
        name = firm.name
        ctx.keep_at_least(reader.home, 3.0)
        where = "Bud's Gun Shop" if isinstance(reader, BudsReader) else f"{name}'s site"
        # A heading for Site settings' progress line (services/makerjobs).
        log(
            f"{where if isinstance(reader, BudsReader) else name}: "
            f"{name if isinstance(reader, BudsReader) else 'its own site'} "
            f"({at} of {len(plan)} makers)"
        )
        for model in siblings:
            totals["models"] += 1
            try:
                found = reader.read(ctx, model, siblings)
            except ScrapeError as exc:
                log(f"  {model.name}: could not read {where} ({exc}).")
                totals["unread"] += 1
                errored.add(name)
                continue
            if not found:
                log(f"  {model.name}: nothing found on {where}.")
                totals["unread"] += 1
                continue
            counts = record(session, model, found)
            session.commit()
            log(
                f"  {model.name}: {len(found)} found on {where}, {counts['proposed']} new "
                f"(pending), {counts['refreshed']} refreshed."
            )
            totals["proposed"] += counts["proposed"]
            totals["refreshed"] += counts["refreshed"]
        unowned = getattr(reader, "unowned", None)
        if callable(unowned):
            try:
                lines = unowned(ctx, siblings)
            except ScrapeError:
                lines = {}
            totals["models_proposed"] = totals.get("models_proposed", 0) + _propose_models(
                session, firm, lines, log
            )
    totals["errors"] = len(errored)
    return totals


def _still_made(
    session: Session, model: FirearmModel, found: list[Found], log: Callable[[str], None]
) -> None:
    """A model the maker's site still sells is still made (2026-10-14).

    The Model 629 and Model 29 were never flagged when the flag was introduced,
    so the reader passed them over while Smith & Wesson listed eleven 629s.
    A model in use -- approved and switched on -- whose products are on its
    maker's current site is flagged, its versions read in the same run, and
    the change written to the audit log. A model switched off, merged away or
    still awaiting approval is somebody's decision, and is only named. The
    reverse is never automatic: a model missing from the site is not
    unflagged, because a site is not a list of everything still made.
    """
    if model.status != ArmoryStatus.APPROVED or not model.enabled:
        log(f"  {model.name}: {len(found)} product(s) on the site; the model is not in use.")
        return
    model.modern_production = True
    audit.record(
        session,
        actor=None,
        action=audit.ARMORY_EDITED,
        target_type="model",
        target_id=model.id,
        target_label=model.name,
        detail="modern_production (its products are on its maker's site)",
    )
    counts = record(session, model, found)
    session.commit()
    log(
        f"  {model.name}: flagged as still made, {counts['proposed']} variant(s) proposed, "
        f"{counts['refreshed']} refreshed."
    )


#: What a product's name says it is, the first word found deciding.
_KIND_WORDS = (
    (re.compile(r"\brevolvers?\b", re.I), FirearmKind.REVOLVER),
    (re.compile(r"\bshotguns?\b", re.I), FirearmKind.SHOTGUN),
    (re.compile(r"\bcarbines?\b", re.I), FirearmKind.CARBINE),
    (re.compile(r"\brifles?\b", re.I), FirearmKind.RIFLE),
    (re.compile(r"\bpistols?\b", re.I), FirearmKind.PISTOL),
)


def _kind_of(found: list[Found]) -> FirearmKind | None:
    """The kind every product of a line that names one agrees on: "MODEL 432
    THE ULTIMATE CARRY REVOLVER" is a revolver. None where they say nothing,
    or disagree; the administrator approving it says."""
    kinds = {
        kind
        for item in found
        for kind in [
            item.kind or next((k for word, k in _KIND_WORDS if word.search(item.label)), None)
        ]
        if kind
    }
    return kinds.pop() if len(kinds) == 1 else None


def _propose_models(
    session: Session,
    firm: Manufacturer,
    lines: dict[str, list[Found]],
    log: Callable[[str], None],
) -> int:
    """A pending model for each product line no model names, its variants under it.

    Asked for on 2026-10-14, in place of filing them under the nearest family:
    an administrator approves the model and its versions together.

    **One model a family.** A line whose name begins with a shorter line's is
    a version of it: "Model 1854 Stealth" and "Model 1854 Walnut" go under the
    Model 1854, "SW22 Victory Target" under the SW22 Victory. And a line that
    begins with a model the armory already has -- the "Model 629 Deluxe" --
    is not proposed at all: it is that model's, and :func:`_still_made`
    decides what to do with it. Returns how many models were proposed.
    """
    maker_words = frozenset(_tokens(firm.name)) | {"s", "w"}
    known: list[tuple[list[str], FirearmModel]] = [
        (need, model)
        for model in session.execute(select(FirearmModel)).scalars()
        if firm in model.manufacturers
        for need in (_tokens(spelling, maker_words) for spelling in model.spellings)
        if need and _specific(need)
    ]
    families: list[tuple[list[str], str, list[Found]]] = []
    decided: dict[int, tuple[FirearmModel, list[Found]]] = {}
    for line, found in sorted(lines.items(), key=lambda kv: len(_tokens(kv[0], maker_words))):
        words = _tokens(line, maker_words)
        owner = next((model for need, model in known if words[: len(need)] == need), None)
        if owner is not None:
            decided.setdefault(owner.id, (owner, []))[1].extend(found)
            continue
        family = next((f for f in families if words[: len(f[0])] == f[0]), None)
        if family is not None:
            family[2].extend(found)
        else:
            families.append((words, line, list(found)))
    for model, owned in sorted(decided.values(), key=lambda pair: pair[0].name):
        _still_made(session, model, owned, log)
    for _words, line, found in families:
        model = FirearmModel(
            name=f"{firm.name} {line}",
            aliases=line,
            status=ArmoryStatus.PENDING,
            modern_production=True,
            # The maker's country, and a kind where its products name one: a
            # proposal states both, as every modern row does.
            kind=_kind_of(found),
            country=firm.country,
            first_seen_in=f"{firm.name}'s site: {found[0].label}"[:500],
        )
        model.manufacturers = [firm]
        session.add(model)
        session.flush()
        counts = record(session, model, found)
        session.commit()
        log(f"  {model.name}: proposed, with {counts['proposed']} variant(s) waiting under it.")
    return len(families)
