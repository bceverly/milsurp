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
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ArmoryStatus, Caliber, FirearmModel, Manufacturer, ModelVariant
from ..scrapers.base import ScrapeContext, ScrapeError, text_of
from . import armory, classify, variants


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


def _money(text: str | None) -> float | None:
    found = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", text or "")
    try:
        return float(found.group(1).replace(",", "")) if found else None
    except ValueError:
        return None


def _digits(text: str | None) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    return digits if 8 <= len(digits) <= 14 else None


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class RugerReader:
    """ruger.com: a ``models.html`` per product line, a spec sheet per model."""

    maker = "Ruger"
    home = "https://ruger.com/"

    def models_pages(self, ctx: ScrapeContext, model: FirearmModel) -> list[str]:
        """The product line's model pages: the model's own recorded page, or
        the lines in Ruger's navigation whose name is the model's."""
        if model.maker_url and "ruger.com" in model.maker_url:
            return [model.maker_url]
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
        return pages

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, _siblings: list[FirearmModel]
    ) -> list[Found]:
        found: list[Found] = []
        for page in self.models_pages(ctx, model):
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

    ``/products/pistols`` and ``/products/revolvers`` each embed their whole
    catalog in the page's ``__NEXT_DATA__`` -- 275 pistols and 129 revolvers
    when measured, two requests -- with the name, the price (S&W's MSRP), the
    UPC and the item number. Barrel and finish are in the name ("M&P9 M2.0
    METAL 4.25 INCH TUNGSTEN GRAY"). Each product goes to the flagged S&W model
    whose name it carries most specifically -- an "M&P9 Shield Plus" is a
    Shield, not an M&P9.
    """

    maker = "Smith & Wesson"
    home = "https://www.smith-wesson.com/"
    CATEGORIES = ("pistols", "revolvers")
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
                if need and _carries(have, need):
                    score = (len(need), len(_compact(spelling)), model)
                    if best is None or score[:2] > best[:2]:
                        best = score
        return best[2] if best else None

    def read(
        self, ctx: ScrapeContext, model: FirearmModel, siblings: list[FirearmModel]
    ) -> list[Found]:
        found = []
        for record in self.catalog(ctx):
            if self._owner(record, siblings) is not model:
                continue
            name = re.sub(r"[®™]", "", str(record.get("name") or "")).strip()
            path = (
                (record.get("custom_url") or {}).get("url")
                if isinstance(record.get("custom_url"), dict)
                else None
            )
            price = record.get("price")
            found.append(
                Found(
                    maker_part=str(record.get("sku") or record.get("id")),
                    label=name[:200],
                    caliber=classify.extract_caliber(name),
                    barrel_inches=variants.read_barrel(name.replace(" INCH", '"')),
                    finish=variants.read_finish(name),
                    upc=_digits(str(record.get("upc") or "")),
                    msrp=float(price) if isinstance(price, int | float) and price > 0 else None,
                    url=urljoin(self.home, f"product{path}") if path else None,
                )
            )
        return found


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
        if model.maker_url and "waltherarms.com" in model.maker_url:
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


Reader = RugerReader | SmithWessonReader | KimberReader | WaltherReader
READERS: dict[str, Callable[[], Reader]] = {
    "Ruger": RugerReader,
    "Smith & Wesson": SmithWessonReader,
    "Kimber": KimberReader,
    "Walther": WaltherReader,
}


def _caliber_row(session: Session, text: str | None) -> Caliber | None:
    name = armory.canonical_caliber(session, text) if text else None
    if not name:
        return None
    return session.execute(select(Caliber).where(Caliber.name == name)).scalars().first()


def record(session: Session, model: FirearmModel, found: Iterable[Found]) -> dict[str, int]:
    """Write what a reader found: new variants pending, known ones refreshed."""
    counts = {"proposed": 0, "refreshed": 0}
    by_part = {v.maker_part: v for v in model.variants if v.maker_part}
    by_upc = {v.upc: v for v in model.variants if v.upc}
    for item in found:
        known = by_part.get(item.maker_part) or (by_upc.get(item.upc) if item.upc else None)
        if known is not None:
            known.msrp = item.msrp if item.msrp is not None else known.msrp
            known.maker_url = item.url or known.maker_url
            known.upc = known.upc or item.upc
            known.maker_part = known.maker_part or item.maker_part
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
                upc=item.upc,
                maker_part=item.maker_part,
                msrp=item.msrp,
                maker_url=item.url,
                source="maker-site",
                status=ArmoryStatus.PENDING,
            )
        )
        by_part[item.maker_part] = model.variants[-1]
        counts["proposed"] += 1
    return counts


def run(
    session: Session,
    ctx: ScrapeContext,
    *,
    maker: str | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Read every modern-production model of a maker with a reader."""
    totals = {"models": 0, "proposed": 0, "refreshed": 0, "unread": 0}
    for name, make in READERS.items():
        if maker and name.lower() != maker.lower():
            continue
        reader = make()
        firm = (
            session.execute(select(Manufacturer).where(Manufacturer.name == name)).scalars().first()
        )
        if firm is None:
            continue
        ctx.keep_at_least(reader.home, 3.0)
        siblings = [
            model
            for model in session.execute(
                select(FirearmModel).where(
                    FirearmModel.modern_production.is_(True), FirearmModel.enabled.is_(True)
                )
            ).scalars()
            if firm in model.manufacturers
        ]
        for model in siblings:
            totals["models"] += 1
            try:
                found = reader.read(ctx, model, siblings)
            except ScrapeError as exc:
                log(f"  {model.name}: could not read {name}'s site ({exc}).")
                totals["unread"] += 1
                continue
            if not found:
                log(f"  {model.name}: no page found on {name}'s site; set its maker's page.")
                totals["unread"] += 1
                continue
            counts = record(session, model, found)
            session.commit()
            log(
                f"  {model.name}: {len(found)} found, {counts['proposed']} new (pending), "
                f"{counts['refreshed']} refreshed."
            )
            totals["proposed"] += counts["proposed"]
            totals["refreshed"] += counts["refreshed"]
    return totals
