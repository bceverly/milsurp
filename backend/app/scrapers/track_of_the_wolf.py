"""Track of the Wolf (trackofthewolf.com).

A Minnesota muzzleloading supplier best known for parts, with a shelf of
complete guns: antiques ("Antique Model 1789 Saxony Dragoon Pistol"), used
contemporary customs ("York County Longrifle ... by M. Compton") and used
Pedersolis. About fifty on 2026-10-08, across six sections -- flintlock
pistols, rifles and smoothbores, percussion pistols, rifles and shotguns. Their
"Antique & Collectible" section repeats the others and is not read.

The site is its own (ASP.NET). A section is paged by path --
``/parts/list/2584/2`` -- and an empty page is the end. A gun is a ``div.card``
whose part number (``AAX-135``) is the key; the title is the card's text after
it; the price is the bold figure in the footer; and availability is the
``title`` of the status icon: "In Stock", or "Out of Stock", or "shipped out
for inspection", which is not for sale either. robots.txt allows everything.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ScrapeContext, ScrapedItem, normalize_whitespace
from .catalog_pages import CatalogPagesScraper
from .storefront import parse_price

SITE_BASE = "https://www.trackofthewolf.com/"

SECTIONS = (
    ("Flintlock Pistols", 2585),
    ("Flintlock Rifles", 2584),
    ("Flintlock Smoothbores", 2586),
    ("Percussion Pistols", 2588),
    ("Percussion Rifles", 2587),
    ("Percussion Shotguns", 2589),
)

#: Pages walked per section before giving up; the largest had two.
MAX_PAGES = 10

_PART = re.compile(r"/parts/detail/\d+/\d+/([^/?#]+)")


def parse_page(html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
    """The guns on one section page."""
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[ScrapedItem] = []
    for card in soup.select("div.card"):
        link = card.select_one(".card-title a[href*='/parts/detail/']")
        if link is None:
            continue
        found = _PART.search(str(link["href"]))
        if found is None:
            continue
        heading = card.select_one(".card-title")
        if heading is None:  # pragma: no cover - the link was found inside it
            continue
        title = normalize_whitespace(
            heading.get_text(" ", strip=True).replace(link.get_text(strip=True), "", 1)
        ).strip(" ,")
        if not title:
            continue
        price = card.select_one(".card-footer .fw-bold")
        status = card.select_one(".inventory-status[title]")
        image = card.select_one(".card-img-top img[src]")
        items.append(
            ScrapedItem(
                external_key=found.group(1).upper(),
                url=urljoin(page_url, str(link["href"])),
                title=title,
                price=parse_price(price.get_text(" ", strip=True)) if price else None,
                category=category,
                is_sold=not (
                    status is not None and str(status["title"]).strip().lower() == "in stock"
                ),
                image_urls=[str(image["src"])] if image is not None else [],
                images_are_complete=False,
            )
        )
    return items


class TrackOfTheWolfScraper(CatalogPagesScraper):
    slug = "track-of-the-wolf"
    name = "Track of the Wolf"
    base_url = SITE_BASE
    description = "Muzzleloading supplier's complete guns: antiques, customs and used Pedersolis."
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-08"
    shipping_note = "No firearm shipping rate published; checked 2026-10-08"

    sources = tuple(
        {"category": label, "url": f"{SITE_BASE}parts/list/{number}/1"}
        for label, number in SECTIONS
    )

    def parse_page(self, html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
        return parse_page(html_text, page_url, category)

    def _walk(self, ctx: ScrapeContext, source: dict[str, str]) -> Iterator[ScrapedItem]:
        """Page by path until a page comes back empty."""
        first = source["url"]
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            url = first[: first.rstrip("/").rfind("/") + 1] + str(page)
            found = parse_page(ctx.get_text(url), url, source["category"])
            if not found:
                return
            yield from found
