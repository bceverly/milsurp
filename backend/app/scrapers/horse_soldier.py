"""Horse Soldier (horsesoldier.com).

A Gettysburg dealer in Civil War arms and militaria. Three firearm sections
are read -- longarms, handguns and carbines, measured 2026-10-06 at 69, 75 and
18 -- each in one page with ``?show=all``. Cartridges, gun tools and holsters
are not.

The site is its own. A listing is a ``div.product`` card -- a thumbnail, the
name and the start of the write-up -- followed by a ``div.details`` block with
the price, and a badge when it is not for sale: ``SOLD``, or ``ON HOLD``, both
in a ``span.sold`` and both read as not for sale. A reduced item shows its old
price beside the new one ("Originally $2,950.00"), and the new one is read.

**The key is the shop's product number**, which ends every product address
(``/products/firearms/longarms/55145``). The product page is read once per
listing, for the whole write-up and the full-size gallery, whose photographs
each carry their full-size address in ``data-full-image``. robots.txt is
empty; there is no mailing list, and ordering is by telephone or email.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import ScrapedItem, normalize_whitespace
from .catalog_pages import CatalogPagesScraper
from .storefront import parse_price

SITE_BASE = "https://www.horsesoldier.com/"
FIREARMS = f"{SITE_BASE}products/firearms/"

SOURCES = (
    {"category": "Longarms", "url": f"{FIREARMS}longarms/?show=all"},
    {"category": "Handguns", "url": f"{FIREARMS}handguns/?show=all"},
    {"category": "Carbines", "url": f"{FIREARMS}carbines/?show=all"},
)

_PRODUCT_NUMBER = re.compile(r"/(\d{3,7})/?$")
_THUMBNAIL = re.compile(r"_tn(\.\w+)$")
#: The shop's own filing codes at the end of a write-up: "[sr][ph:L]".
_FILING_CODES = re.compile(r"(?:\s*\[[a-z]{1,4}(?::[^\]]{0,12})?\])+\s*$", re.I)


def _details_after(card: Tag) -> Tag | None:
    """The ``div.details`` that follows a card, before the next card."""
    for sibling in card.find_next_siblings("div"):
        classes: list[str] = list(sibling.get("class") or [])
        if "details" in classes:
            return sibling
        if "product" in classes:
            return None
    return None


def parse_page(html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[ScrapedItem] = []
    for card in soup.select("div.product"):
        link = card.select_one("h4 a[href]")
        if link is None:
            continue
        href = str(link["href"])
        number = _PRODUCT_NUMBER.search(href)
        title = normalize_whitespace(link.get_text(" ", strip=True))
        if number is None or not title:
            continue
        details = _details_after(card)
        price = None
        unavailable = False
        if details is not None:
            price_link = details.select_one("a")
            price = parse_price(price_link.get_text(" ", strip=True)) if price_link else None
            unavailable = details.select_one("span.sold") is not None
        summary = card.find("p")
        image = card.select_one(".feature-img img[src]")
        items.append(
            ScrapedItem(
                external_key=number.group(1),
                url=urljoin(page_url, href),
                title=title,
                price=price,
                description=(
                    normalize_whitespace(summary.get_text(" ", strip=True)) if summary else None
                ),
                category=category,
                is_sold=unavailable,
                image_urls=(
                    [_THUMBNAIL.sub(r"\1", urljoin(page_url, str(image["src"])))]
                    if image is not None
                    else []
                ),
                images_are_complete=False,
            )
        )
    return items


def read_detail(item: ScrapedItem, html_text: str) -> None:
    soup = BeautifulSoup(html_text, "html.parser")
    details = soup.select_one("div.details.alignleft")
    if details is not None:
        # The write-up is the plain paragraphs after the price-and-ordering
        # block, up to their standing disclaimer; the centered ones after it
        # are the layaway notice every item carries.
        paragraphs: list[str] = []
        for paragraph in details.find_next_siblings("p"):
            if "aligncenter" in (paragraph.get("class") or []):
                continue
            text = normalize_whitespace(paragraph.get_text(" ", strip=True))
            if text.upper().startswith("DISCLAIMER"):
                break
            text = _FILING_CODES.sub("", text)
            if text:
                paragraphs.append(text)
        if paragraphs:
            item.description = "\n\n".join(paragraphs)
    photos: list[str] = []
    for tag in soup.select("img[data-full-image]"):
        url = urljoin(item.url, str(tag["data-full-image"]))
        if url not in photos:
            photos.append(url)
    if photos:
        item.image_urls = photos
        item.images_are_complete = True


class HorseSoldierScraper(CatalogPagesScraper):
    slug = "horse-soldier"
    name = "Horse Soldier"
    base_url = SITE_BASE
    description = "Gettysburg dealer in Civil War longarms, carbines and handguns."
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-06"
    shipping_note = (
        "Shipping determined by method and the buyer's location; orders by phone or email"
    )
    sources = SOURCES
    reads_details = True

    def parse_page(self, html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
        return parse_page(html_text, page_url, category)

    def read_detail(self, item: ScrapedItem, html_text: str) -> None:
        read_detail(item, html_text)
