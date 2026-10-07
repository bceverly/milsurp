"""David Condon, Inc. (davidcondon.com).

A Middleburg, Virginia arms dealer and appraiser with a large inventory of
military longarms -- foreign and US, measured 2026-10-06 at 98 and 128 -- beside
antique and collectible handguns, Colts, Winchesters and Confederate arms.
The site is its own: an IIS server and a hand-made catalog where a section is
one page, and each listing one link holding its photograph, its name and its
price.

**The key is the stock number** that ends every product address
(``.../ww2-german-gustloff-werke-...-29526``), which is also the number the
shop writes at the head of the description.

**Sold stock stays up**, three ways, and each is read as sold: a name starting
"SOLD-", a price of $0.00, and "(SOLD)" at the end of the description on the
product page. About half the foreign longarms were one or another when this
was written.

The product page is read once per listing, for the description and the
gallery, whose photographs are named for the stock number (``29526a.jpg``,
``29526b.jpg`` ...) in a thumbnail strip and served full size from
``/img/upload/fullsize/``. There is no robots.txt, and no mailing list.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import ScrapedItem, normalize_whitespace
from .catalog_pages import CatalogPagesScraper
from .storefront import parse_price

SITE_BASE = "https://www.davidcondon.com/"
INVENTORY = f"{SITE_BASE}inventory/"

#: The firearm sections. Edged weapons, militaria, books, flasks, tools,
#: ammunition, cannons and the arts-and-antiques shelf are left out.
SOURCES = (
    {"category": "Foreign Military Longarms", "url": f"{INVENTORY}foreign-military-longarms"},
    {"category": "US Military Longarms", "url": f"{INVENTORY}us-military-longarms"},
    {"category": "Confederate Weapons", "url": f"{INVENTORY}confederate-weapons"},
    {"category": "Antique Handguns", "url": f"{INVENTORY}antique-handguns"},
    {"category": "Collectible Modern Handguns", "url": f"{INVENTORY}collectible-modern-handguns"},
    {"category": "Other Antique Longarms", "url": f"{INVENTORY}other-antique-longarms"},
    {"category": "Colts", "url": f"{INVENTORY}colts"},
    {"category": "Winchesters", "url": f"{INVENTORY}winchesters"},
    {"category": "Sporting Shotguns/Rifles", "url": f"{INVENTORY}sporting-shotguns-rifles"},
)

_STOCK_NUMBER = re.compile(r"-(\d{3,7})/?$")
_SOLD_NAME = re.compile(r"^\s*SOLD\s*[-\u2013\u2014:]?\s*", re.I)
_SOLD_NOTE = re.compile(r"\(\s*SOLD\s*\)", re.I)
_GALLERY = re.compile(r"SetActiveImage\s*\(\s*'([^']+\.(?:jpe?g|png|gif|webp))'", re.I)


def address(page_url: str, href: str) -> str:
    """A product address made safe: the shop writes its sections with spaces."""
    return quote(urljoin(page_url, href), safe=":/?&=%#")


def parse_page(html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[ScrapedItem] = []
    for link in soup.select(".product-list a[href]"):
        href = str(link.get("href") or "")
        number = _STOCK_NUMBER.search(href)
        name = link.select_one(".product-name")
        if number is None or name is None:
            continue
        title = normalize_whitespace(name.get_text(" ", strip=True))
        sold = bool(_SOLD_NAME.match(title))
        title = _SOLD_NAME.sub("", title).rstrip(" .")
        if not title:
            continue
        price_tag = link.select_one(".product-price")
        price = parse_price(price_tag.get_text(" ", strip=True)) if price_tag else None
        image = link.select_one("img[src]")
        items.append(
            ScrapedItem(
                external_key=number.group(1),
                url=address(page_url, href),
                title=title,
                price=price,
                category=category,
                # $0.00 is how a sold item is priced here, as well as named.
                is_sold=sold or price is None,
                image_urls=(
                    [urljoin(page_url, str(image["src"]).replace("/midsize/", "/fullsize/"))]
                    if image is not None
                    else []
                ),
                images_are_complete=False,
            )
        )
    return items


def read_detail(item: ScrapedItem, html_text: str) -> None:
    soup = BeautifulSoup(html_text, "html.parser")
    content = soup.select_one("#internal-content")
    if content is None:
        return
    paragraphs = [normalize_whitespace(p.get_text(" ", strip=True)) for p in content.find_all("p")]
    description = "\n\n".join(text for text in paragraphs if text)
    if description:
        item.description = description
        if _SOLD_NOTE.search(description):
            item.is_sold = True
    photos: list[str] = []
    for name in _GALLERY.findall(html_text):
        url = urljoin(SITE_BASE, f"/img/upload/fullsize/{name}")
        if url not in photos:
            photos.append(url)
    if photos:
        item.image_urls = photos
        item.images_are_complete = True


class DavidCondonScraper(CatalogPagesScraper):
    slug = "david-condon"
    name = "David Condon, Inc."
    base_url = SITE_BASE
    description = (
        "Virginia dealer with a large inventory of foreign and US military longarms, "
        "antique and collectible handguns, Colts and Winchesters."
    )
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-06"
    shipping_note = 'Their shipping page reads "Coming soon"; no charge stated (checked 2026-10-06)'
    shipping_source = "https://www.davidcondon.com/shipping"
    sources = SOURCES
    reads_details = True

    def parse_page(self, html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
        return parse_page(html_text, page_url, category)

    def read_detail(self, item: ScrapedItem, html_text: str) -> None:
        read_detail(item, html_text)
