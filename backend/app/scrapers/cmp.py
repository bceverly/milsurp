"""Civilian Marksmanship Program (thecmp.org): which surplus grades are offered.

The CMP is the federally chartered seller of U.S. service firearms: M1 Garands,
M1903 and 1903A3 Springfields, M1917 Enfields, Krag-Jørgensens, M1 Carbines
and M1911A1 pistols. It is not a shop with a cart, and this does not treat it
as one. What it publishes is a page per firearm listing the **grades** it is
selling, each with CMP's item code and either a price or "SOLD OUT" and the
date. Those are what this reads. It is the reference price for these guns:
a Field Grade Garand at a dealer means something next to CMP's.

**Read, measured September 2026:**

- the M1 Garand page: one table per grade ("Expert Grade M1 Garand"), a row
  per item code (``RM1308EXPERTRC``), the price cell "$1150" or
  "SOLD OUT 12/02/25";
- the M1903/1903A3, M1917 and Krag pages: one table each, the grade in the
  description ("M1917 SERVICE GRADE"), and "Available at Stores" for grades
  sold in person only;
- the 1911 page: no table, but the grades in its text ("Service Grade $1300",
  "SOLD OUT - Range Grade - $1150", with en dashes);
- the M1 Carbine page, which lists nothing today. A page with no grades is
  ordinary for the rifles CMP sells only now and then (the Carbine, the Krag,
  the 1917); for the Garand and the 1911, which always list grades, it means
  the page changed, and the scan fails rather than de-listing them.

**Never read:** CMP's auctions (on GunBroker) and forums. Only these six pages,
once a day. Buying from CMP requires eligibility (U.S. citizenship,
membership of a CMP-affiliated club, and more), so every listing says so and
links to the requirements. A sold-out grade keeps its last price, because a
listing handed over without one keeps what is stored.

Each firearm's photograph is the one CMP's own page publishes for it (its
``og:image``): CMP photographs the type, not each grade.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .base import (
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
)
from .storefront import parse_price

SITE_BASE = "https://thecmp.org/"
ELIGIBILITY = f"{SITE_BASE}cmp_sales/eligibility-requirements/"


@dataclass(frozen=True)
class Page:
    model: str
    url: str
    kind: str  # "rifle" or "pistol"
    #: The Garand and 1911 pages always list grades; empty means a changed page.
    always_lists: bool = False
    #: A word the Garand page's per-grade headings contain, so a heading can
    #: name the listing; the other pages head their one table with prose.
    heading_names: str | None = None


PAGES = (
    Page(
        "M1 Garand",
        f"{SITE_BASE}sales-and-service/m1-garand/",
        "rifle",
        always_lists=True,
        heading_names="garand",
    ),
    Page(
        "M1903/M1903A3 Springfield",
        f"{SITE_BASE}sales-and-service/m1903-m1903a3-rifle-information/",
        "rifle",
    ),
    Page(
        "M1917 Enfield", f"{SITE_BASE}sales-and-service/m1917-enfield-rifle-information/", "rifle"
    ),
    Page("Krag-Jørgensen rifle", f"{SITE_BASE}sales-and-service/krag-jorgensen-rifles/", "rifle"),
    Page("M1 Carbine", f"{SITE_BASE}sales-and-service/m1-carbine-information/", "rifle"),
    Page(
        "M1911A1 pistol",
        f"{SITE_BASE}sales-and-service/1911-information/",
        "pistol",
        always_lists=True,
    ),
)

#: Grades as CMP's item codes spell them, most specific first.
_CODE_GRADES = (
    ("EXPERT", "Expert"),
    ("EXP", "Expert"),
    ("SERVICE", "Service"),
    ("FIELD", "Field"),
    ("RACK", "Rack"),
)
#: Codes ending in a grade letter pair: RM1917SG, RM1917FG, RM1CSB, RM1CFB.
_CODE_SUFFIX = re.compile(r"(S|F)(?:G|B)$")
#: A grade named as a grade in the description: "M1917 SERVICE GRADE". Only
#: "<word> grade", never a bare word: descriptions say "checked with a FIELD
#: gauge" and "service grade or higher criteria", and taking those as the
#: grade named a 1903A3 Expert a Field Grade.
_NAMED_GRADE = re.compile(r"\b(rack|field|service|expert|special|correct)\s+grade\b", re.I)
#: What else a code says about the rifle.
#: Written "with a …" so the classifier reads the part as fitted, not for sale:
#: a title ending "shortened barrel" was filed as a barrel.
_CODE_VARIANTS = (
    ("IHC", "with an International Harvester receiver"),
    ("WRA", "with a Winchester receiver"),
    ("CHR", "with a chrome finish"),
    ("SHORT", "with a shortened barrel"),
)
_GRADE = re.compile(r"\b(rack|field|service|expert|special|range|correct)\s+grade\b", re.I)
_SOLD_OUT = re.compile(r"sold\s+out", re.I)
_AT_STORES = re.compile(r"available\s+at\s+stores?", re.I)
_DASH = "[\u2013-]"
_PISTOL_GRADE = re.compile(
    rf"(sold\s+out\s*{_DASH}\s*)?\b(rack|field|service|range|expert|correct)\s+grade\s*"
    rf"{_DASH}?\s*\$\s?([\d,]{{3,6}})",
    re.I,
)


@dataclass(frozen=True)
class Offering:
    """One grade CMP lists: its code, words and price cell."""

    code: str
    title: str
    description: str
    price: float | None
    sold_out: bool
    stores_only: bool


def _text(tag: Tag) -> str:
    return normalize_whitespace(tag.get_text(" ", strip=True))


def _photo(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one('meta[property="og:image"]')
    content = str(tag.get("content") or "") if tag else ""
    return content or None


def grade_of(code: str, description: str) -> str | None:
    """The grade: from CMP's item code first, where it is spelled out, then
    from a "<word> grade" phrase in the description."""
    upper = code.upper()
    if "CHR" in upper:
        # Chrome rifles are ceremonial and listed by finish, not graded.
        return None
    for word, grade in _CODE_GRADES:
        if word in upper:
            return grade
    if found := _CODE_SUFFIX.search(upper):
        return "Service" if found.group(1) == "S" else "Field"
    if found := _NAMED_GRADE.search(description):
        return found.group(1).title()
    return None


def _details(code: str, description: str, page: Page) -> list[str]:
    """What the grade name leaves out: the Garand's cartridge, and the
    receiver, finish or barrel the code marks."""
    found = []
    if page.heading_names == "garand":
        found.append(
            ".308" if re.search(r"308|7\.62\s*nato", code + " " + description, re.I) else ".30-06"
        )
    upper = code.upper()
    found.extend(words for marker, words in _CODE_VARIANTS if marker in upper)
    return found


_KEEP_CAPS = {"NATO", "M1", "M1C", "SA", "HRA"}
_SMALL = {"of", "the", "and", "a", "an", "in", "for"}


def _heading(text: str) -> str:
    """A heading as a title. "7.62 NATO VERSION OF THE M1 GARAND" is shouted,
    and so is the "RACK" of "RACK Grade M1 Garand"."""
    words = []
    for position, word in enumerate(text.split()):
        if not word.isupper() or any(ch.isdigit() for ch in word) or word in _KEEP_CAPS:
            words.append(word)
        elif position and word.lower() in _SMALL:
            words.append(word.lower())
        else:
            words.append(word.capitalize())
    return " ".join(words)


def offerings_in_tables(soup: BeautifulSoup, page: Page) -> list[Offering]:
    found: list[Offering] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [_text(cell).lower() for cell in rows[0].find_all(["td", "th"])]
        if not header or header[0] != "item #":
            continue  # a table with no item codes (the Custom Shop build) is not a grade
        heading_tag = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        heading = _text(heading_tag) if heading_tag else ""
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            code = _text(cells[0]).rstrip("*").strip().upper()
            if not code:
                continue
            description = _text(cells[1])
            price_cell = _text(cells[2])
            grade = grade_of(code, description)
            if page.heading_names and page.heading_names in heading.lower():
                base = _heading(heading)
            else:
                base = f"{page.model} {grade} Grade" if grade else page.model
            details = _details(code, description, page)
            # The cartridge after a comma; a fitted part as "with a …".
            title = f"CMP {base}" + "".join(
                f" {d}" if d.startswith("with ") else f", {d}" for d in details
            )
            found.append(
                Offering(
                    code=code,
                    title=f"{title} ({code})",
                    description=description,
                    price=parse_price(price_cell) if "$" in price_cell else None,
                    sold_out=bool(_SOLD_OUT.search(price_cell)),
                    stores_only=bool(_AT_STORES.search(price_cell)),
                )
            )
    return found


def offerings_in_text(soup: BeautifulSoup, page: Page) -> list[Offering]:
    """The 1911 page: grades and prices written in its prose."""
    text = _text(soup)
    found: list[Offering] = []
    seen: set[str] = set()
    for match in _PISTOL_GRADE.finditer(text):
        grade = match.group(2).title()
        code = f"1911-{grade.upper()}"
        if code in seen:
            continue
        seen.add(code)
        found.append(
            Offering(
                code=code,
                title=f"CMP {page.model}, {grade} Grade",
                description=f"{grade} Grade M1911A1, as CMP grades its surplus U.S. Army pistols.",
                price=parse_price(match.group(3)),
                sold_out=bool(match.group(1)),
                stores_only=False,
            )
        )
    return found


class CmpScraper(SiteScraper):
    #: Hands over the condition (the grade) and the country. See SiteScraper.
    states_facts = True
    slug = "cmp"
    name = "Civilian Marksmanship Program"
    base_url = SITE_BASE
    newsletter_url = f"{SITE_BASE}emailarchives/email-signup/"
    newsletter_note = 'CMP\'s email list signup page ("Join Our Email List" in their menu)'
    description = (
        "The CMP's grades of M1 Garands, M1903/1903A3 Springfields, M1917s, Krags, "
        "M1 Carbines and 1911s, with prices and sold-out dates. Its auctions are "
        "not read. Buying from CMP requires eligibility."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def scrape(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        total = 0
        for page in PAGES:
            ctx.check_stop()
            ctx.log(f"Reading {page.model}…")
            # A page that will not load fails the scan: carrying on would
            # de-list every grade on it.
            soup = BeautifulSoup(ctx.get_text(page.url), "html.parser")
            offered = (
                offerings_in_text(soup, page)
                if page.kind == "pistol"
                else offerings_in_tables(soup, page)
            )
            if not offered and page.always_lists:
                raise ScrapeError(
                    f"{page.model}: the page lists no grades, which it always has; "
                    "its layout has probably changed."
                )
            if not offered:
                ctx.log(f"{page.model}: nothing offered right now.")
            photo = _photo(soup)
            for offering in offered:
                total += 1
                yield self._item(page, offering, photo)
        ctx.log(f"{total} grade(s) listed across {len(PAGES)} pages.")

    @staticmethod
    def _item(page: Page, offering: Offering, photo: str | None) -> ScrapedItem:
        notes = [offering.description]
        if offering.stores_only:
            notes.append("Available in CMP's stores only; not sold by mail order.")
        notes.append(
            "Buying from the CMP requires eligibility (U.S. citizenship, membership of "
            f"a CMP-affiliated club, and more): {ELIGIBILITY}"
        )
        grade = _GRADE.search(offering.title)
        return ScrapedItem(
            external_key=offering.code,
            url=f"{page.url}#{offering.code}",
            title=offering.title,
            price=offering.price,
            category="CMP Surplus Pistols" if page.kind == "pistol" else "CMP Surplus Rifles",
            condition=f"{grade.group(1).title()} Grade" if grade else None,
            country="United States",
            description="\n\n".join(notes),
            is_sold=offering.sold_out,
            image_urls=[photo] if photo else [],
        )
