"""Comer's Gunworks (comersgunworks.com).

A reenactors' gunsmith and dealer: new Pedersoli, Uberti, Pietta, Chiappa and
Armi Sport reproductions -- 1842 Springfields, 1861 and 1863 rifle-muskets,
Enfields, Colt and Remington revolvers -- with a few used and original guns
("1842 Springfield (original)"). About 65 guns on 2026-10-08 in their Black
Powder Weapons and Defarbing section, read four pages deep with ``?page=``.

Their own storefront. A gun is a ``div.item`` tile linking to
``/products/<slug>``, which is the key; the title is the tile's name with the
maker before it ("Armisport 42 Springfield - Used, like new"), because the
maker is set apart in the tile and the gun cannot be recognized without it. An
"Out of Stock" badge means not for sale. The defarbing services the section
also sells -- work on a gun, not a gun -- are left out. robots.txt asks for
five seconds between requests, which the scanner honors.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ScrapeContext, ScrapedItem, normalize_whitespace
from .catalog_pages import CatalogPagesScraper
from .storefront import parse_price

SITE_BASE = "https://www.comersgunworks.com/"
SECTION = f"{SITE_BASE}catalog/black-powder-weapons-and-defarbing"

#: Pages read; the section was four.
MAX_PAGES = 10

_PRODUCT = re.compile(r"^/products/([^/?#]+)")
#: A service or a part rather than a gun.
_NOT_A_GUN = re.compile(r"\bdefarb|\bspare\s+cylinder\b|\bservice\b", re.I)


def parse_page(html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
    """The guns on one page of the section."""
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[ScrapedItem] = []
    for tile in soup.select("div.item"):
        link = tile.select_one("a[href^='/products/']")
        if link is None:
            continue
        found = _PRODUCT.search(str(link["href"]))
        name = tile.select_one(".description strong")
        if found is None or name is None:
            continue
        maker = tile.select_one(".grid-description .small:not(.text-muted)")
        title = normalize_whitespace(
            " ".join(
                part
                for part in (
                    maker.get_text(" ", strip=True) if maker else "",
                    name.get_text(" ", strip=True),
                )
                if part
            )
        )
        if not title or _NOT_A_GUN.search(title):
            continue
        price = tile.select_one(".price")
        image = tile.select_one(".image img[src]")
        items.append(
            ScrapedItem(
                external_key=found.group(1),
                url=urljoin(page_url, str(link["href"])),
                title=title,
                price=parse_price(price.get_text(" ", strip=True)) if price else None,
                category=category,
                is_sold=tile.select_one(".out-of-stock-badge") is not None,
                image_urls=[str(image["src"])] if image is not None else [],
                images_are_complete=False,
            )
        )
    return items


class ComersGunworksScraper(CatalogPagesScraper):
    slug = "comers-gunworks"
    name = "Comer's Gunworks"
    base_url = SITE_BASE
    description = "Reenactors' dealer: reproduction muskets, rifles and revolvers."
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-08"
    shipping_note = "No black powder shipping rate published; checked 2026-10-08"
    shipping_source = "https://www.comersgunworks.com/store-policies"

    sources = ({"category": "Black Powder Weapons", "url": f"{SECTION}?page=1"},)

    def parse_page(self, html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
        return parse_page(html_text, page_url, category)

    def _walk(self, ctx: ScrapeContext, source: dict[str, str]) -> Iterator[ScrapedItem]:
        """Page until a page adds nothing new."""
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            url = f"{SECTION}?page={page}"
            found = [
                i
                for i in parse_page(ctx.get_text(url), url, source["category"])
                if i.external_key not in seen
            ]
            if not found:
                return
            seen.update(i.external_key for i in found)
            yield from found
