"""Vintage Doubles (vintagedoubles.com).

Kirby Hoyt's shop of British and European double guns, added on 2026-11-06
when the application widened to every used shotgun: hammer guns, sidelocks,
boxlocks and round actions from Westley Richards, Woodward, Purdey and the
Birmingham trade, with drillings and double rifles beside them. About 255
guns that day, every one priced.

**A hand-made catalog, one page per category** (``/catalog/?sort=N``),
read with :class:`~app.scrapers.catalog_pages.CatalogPagesScraper`. Each gun
is a table row ``tr#gunRow_<id>`` -- photograph, price, title, category,
gauge, the shop's GunID and the serial -- followed by rows holding the
write-up, a zoom-viewer prompt and a spec line (ejectors, barrels, chambers,
proofs, chokes, wall thickness, stock dimensions). The GunID is the key;
there is no product page, so the listing's address is its row on the
category page.

A "$0" is no price, and a "WANTED!" row is the shop asking to buy, so it is
not read. **The serial is left out**, as at Greentop and Double Shotguns. **The
photograph is the catalog thumbnail**, 100 pixels wide: every larger image
on the site is a Zoomify tile pyramid, which has no single file to link to.

Read: Hammerguns, Hammerless Sidelocks, Round Actions, Boxlocks, "Drillings,
Double Rifles, and Rifles", "Rust & Dust" (project guns) and Other Shotguns.
Not read: Left-handed Guns, which repeats guns from the others, Men's
Collectibles and Vintage Cases. robots.txt turns away only the WordPress
admin.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import ScrapedItem, normalize_whitespace, parse_price
from .catalog_pages import CatalogPagesScraper

SITE_BASE = "https://www.vintagedoubles.com/"


def _section(sort: int) -> str:
    return f"{SITE_BASE}catalog/?sort={sort}"


SOURCES = (
    {"category": "Hammerguns", "url": _section(1)},
    {"category": "Hammerless Sidelocks", "url": _section(2)},
    {"category": "Round Actions", "url": _section(3)},
    {"category": "Boxlocks", "url": _section(4)},
    {"category": "Drillings, Double Rifles, and Rifles", "url": _section(5)},
    {"category": "Rust & Dust", "url": _section(7)},
    {"category": "Other Shotguns", "url": _section(8)},
)

_GUN_ROW = re.compile(r"^gunRow_(\d+)$")

#: "Gauge: 12 gauge". A rifle's row says "Gauge: Caliber", which is no answer.
_GAUGE = re.compile(r"Gauge:\s*(\d{1,2}\s*(?:gauge|bore|ga)\b|\.?410(?:\s*bore)?)", re.I)

#: "WANTED! W.C. Scott action or gun": the shop asking to buy, in the same
#: rows as the guns it sells.
_WANTED = re.compile(r"^\W*wanted\b", re.I)

#: The viewer's own instructions, which sit in the rows like a write-up.
_VIEWER = re.compile(r"Click anywhere on the large image|Full Screen", re.I)


def _write_up(row: Tag) -> str | None:
    """The rows after a gun's own, up to the next gun or spacer."""
    parts: list[str] = []
    for sibling in row.find_next_siblings("tr"):
        ident = str(sibling.get("id") or "")
        classes: list[str] = list(sibling.get("class") or [])
        if _GUN_ROW.match(ident) or "spacerRow" in classes:
            break
        text = normalize_whitespace(sibling.get_text(" ", strip=True))
        if text and not _VIEWER.search(text):
            parts.append(text)
    return "\n\n".join(parts) or None


def parse_page(html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[ScrapedItem] = []
    for row in soup.select("tr[id^=gunRow_]"):
        found = _GUN_ROW.match(str(row.get("id") or ""))
        title_tag = row.select_one(".gunTitle")
        if found is None or title_tag is None:
            continue
        title = normalize_whitespace(title_tag.get_text(" ", strip=True))
        if not title or _WANTED.match(title):
            continue
        gun_id = found.group(1)
        price_tag = row.select_one(".gunPrice")
        price = parse_price(price_tag.get_text(" ", strip=True)) if price_tag else None
        gauge = _GAUGE.search(row.get_text(" ", strip=True))
        thumb = row.select_one("img.gunThumb")
        image = thumb.get("data-original") if thumb is not None else None
        items.append(
            ScrapedItem(
                external_key=gun_id,
                url=f"{page_url}#gunRow_{gun_id}",
                title=title,
                price=price if price else None,
                description=_write_up(row),
                category=category,
                caliber=normalize_whitespace(gauge.group(1)) if gauge else None,
                image_urls=[urljoin(page_url, image)] if isinstance(image, str) else [],
                images_are_complete=True,
            )
        )
    return items


class VintageDoublesScraper(CatalogPagesScraper):
    #: The gauge is the shop's own, from each gun's row. See SiteScraper.
    states_facts = True
    slug = "vintage-doubles"
    name = "Vintage Doubles"
    base_url = SITE_BASE
    description = (
        "British and European double guns: hammer guns, sidelocks, boxlocks, "
        "drillings and double rifles."
    )
    default_interval_minutes = 1440
    newsletter_url = f"{SITE_BASE}subscribe/"
    newsletter_note = '"Subscribe to updates" page (Mailchimp)'
    shipping_note = "FedEx or USPS on request, for an additional fee; no rate published"
    shipping_source = f"{SITE_BASE}shipping/"
    sources = SOURCES

    def parse_page(self, html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
        return parse_page(html_text, page_url, category)
