"""Pre98 Antiques (pre98.com).

A Winchester, Virginia dealer in military pistols and rifles -- Lugers, P.38s,
Nambus, 1903s, Arisakas, Sniders, Broomhandles -- adding a few every day.
WooCommerce with the Store API answering. The "Long Guns" and "Handguns"
sections are read, each of which includes its by-country children;
everything else is holsters, magazines, militaria and the 6,000-listing sold
archive.

**Every title starts with the day it was listed** -- "TUE OCT 6, JAPANESE WWII
TYPE 38 ARISAKA..." -- and a sold one with "SOLD" before that. The date is
taken off, because it is not part of what the gun is and it would put a
weekday in front of every title in the catalog; "SOLD" is read as sold.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://pre98.com/"

#: "TUE OCT 6, " or "SOLD THU OCT 1, " at the head of a title.
_LISTED_ON = re.compile(
    r"^\s*(?P<sold>SOLD\s+)?(?:MON|TUE|WED|THU|FRI|SAT|SUN)\w*\.?\s+[A-Z]{3,5}\w*\.?\s+\d{1,2},\s*",
    re.I,
)


def without_date(title: str) -> tuple[str, bool]:
    """The title without its listing date, and whether it said SOLD."""
    match = _LISTED_ON.match(title)
    if match is None:
        return title, False
    return title[match.end() :].strip(), bool(match.group("sold"))


class Pre98Scraper(WooStoreApiScraper):
    slug = "pre98"
    name = "Pre98 Antiques"
    base_url = SITE_BASE
    description = "Virginia dealer in military pistols and rifles, with new listings most days."
    default_interval_minutes = 720
    newsletter_url = SITE_BASE
    newsletter_note = "Mailchimp signup form on the home page"
    shipping_note = "FedEx where possible; no firearm shipping charge stated"
    shipping_source = "https://pre98.com/faq/"

    sources = (
        {"category": "Long Guns", "id": 18},
        {"category": "Handguns", "id": 10},
    )

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None:
            return None
        item.title, sold = without_date(item.title)
        item.is_sold = item.is_sold or sold
        return item if item.title else None
