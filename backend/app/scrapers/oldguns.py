"""OldGuns.net (oldguns.net).

"Antique and Collectable Firearms and Militaria Headquarters": a dealer whose
catalog is five long hand-written pages -- collectible foreign and US
longarms, antique longarms and handguns, collectible handguns -- about two
hundred guns between them, measured 2026-10-06, each with a long write-up of
its history and condition.

**There is no markup to speak of, so the anchors are the structure.** Every
listing begins with a named anchor carrying the shop's stock number
(``<a NAME=SMOF8071>``), then that number again in bold, then the title in
bold, then the write-up, which ends with the price and a "(View Picture)" link
to ``pix/<stock number>.jpg``. A listing runs from its anchor to the next one.
The stock number is the key and the anchor makes the address.

A badge in bold before the title says what the listing is: ``**NEW
ADDITION**``, ``**SOLD**``, or a hold. Sold and held items are read as not for
sale. "Modern Handguns and Longarms" is their retail page and is not read.
There is no robots.txt.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin

from .base import ScrapedItem, normalize_whitespace
from .catalog_pages import CatalogPagesScraper

SITE_BASE = "https://www.oldguns.net/"

SOURCES = (
    {"category": "Collectible Foreign Longarms", "url": f"{SITE_BASE}cat_fa_old_foreign_long.php"},
    {"category": "Collectible U.S. Longarms", "url": f"{SITE_BASE}cat_fa_old_us_long.php"},
    {"category": "Antique Longarms", "url": f"{SITE_BASE}cat_fa_antique_long.php"},
    {"category": "Collectible Handguns", "url": f"{SITE_BASE}cat_fa_old_hand.php"},
    {"category": "Antique Handguns", "url": f"{SITE_BASE}cat_fa_antique_hand.php"},
)

_ANCHOR = re.compile(r"<a\s+name\s*=\s*\"?([A-Z]{2,8}\d{2,6})\"?\s*>", re.I)
_PICTURE = re.compile(r"""href\s*=\s*["']?(pix/[^"'\s>]+\.(?:jpe?g|png|gif))""", re.I)
_PRICE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
_UNAVAILABLE = re.compile(r"\*\*\s*(?:SOLD|ON\s+HOLD|HOLD|PENDING)\b[^*]*\*\*", re.I)
_TAGS = re.compile(r"<[^>]+>")


def text_of(fragment: str) -> str:
    return normalize_whitespace(html.unescape(_TAGS.sub(" ", fragment)))


def parse_page(html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
    anchors = list(_ANCHOR.finditer(html_text))
    items: list[ScrapedItem] = []
    for index, anchor in enumerate(anchors):
        stock = anchor.group(1).upper()
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(html_text)
        segment = html_text[anchor.end() : end]
        # The stock number in bold, then the title in bold.
        number = re.search(rf"<b>\s*{re.escape(stock)}\s*-\s*</b>", segment, re.I)
        if number is None:
            continue
        title_match = re.search(r"<b>(.*?)</b>", segment[number.end() :], re.I | re.S)
        if title_match is None:
            continue
        title = text_of(title_match.group(1))
        if not title:
            continue
        body_start = number.end() + title_match.end()
        picture = _PICTURE.search(segment, body_start)
        body = segment[body_start : picture.start() if picture else len(segment)]
        prices = list(_PRICE.finditer(body))
        price = None
        if prices:
            whole, cents = prices[-1].group(1), prices[-1].group(2)
            value = float(whole.replace(",", "") + (f".{cents}" if cents else ""))
            price = value if value > 0 else None
        # The write-up, without the price that closes it.
        description = text_of(body[: prices[-1].start()] if prices else body) or None
        badges = text_of(segment[: number.start()])
        items.append(
            ScrapedItem(
                external_key=stock,
                url=f"{page_url}#{stock}",
                title=title,
                price=price,
                description=description,
                category=category,
                is_sold=bool(_UNAVAILABLE.search(badges)),
                image_urls=[urljoin(page_url, picture.group(1))] if picture else [],
                images_are_complete=True,
            )
        )
    return items


class OldGunsScraper(CatalogPagesScraper):
    slug = "oldguns"
    name = "OldGuns.net"
    base_url = SITE_BASE
    description = (
        "Antique and collectible firearms: foreign and US military longarms, "
        "antique longarms and handguns, each with a long write-up."
    )
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = (
        "A newsletter archive is published, but no signup was found; checked 2026-10-06"
    )
    shipping_note = "No firearm shipping charge stated; credit card orders add 4%"
    shipping_source = "https://oldguns.net/faq.php"
    sources = SOURCES

    def parse_page(self, html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
        return parse_page(html_text, page_url, category)
