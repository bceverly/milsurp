"""1898andB-4 (1898andb-4.com).

A California antique arms dealer: percussion and cartridge revolvers,
deringers, pepperboxes, flintlocks, Civil War and US military longarms.
WooCommerce with the Store API answering.

Most of the 672 products are their **sold archive**, kept up as a reference
library, so a product with no price is common and is read as no price (the
base class treats a zero as none). An item **pending sale** says so in its
title -- "Jenks Carbine Made By N.P. Ames Co. -- PENDING SALE" -- and is read
as no longer for sale, with the words taken off the title.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://www.1898andb-4.com/"

_PENDING = re.compile(r"\s*[-\u2013\u2014]+\s*PENDING SALE\s*$", re.I)


class B4AntiquesScraper(WooStoreApiScraper):
    slug = "1898-and-b4"
    name = "1898andB-4"
    base_url = SITE_BASE
    description = (
        "California dealer in antique revolvers, pistols, Civil War and US military longarms."
    )
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-06"
    shipping_note = "No shipping policy published on the site; checked 2026-10-06"

    sources = (
        {"category": "Antique Pistols", "id": 94},
        {"category": "Antique Long Guns", "id": 30},
        {"category": "Military", "id": 569},
        {"category": "US Military", "id": 115},
        {"category": "Civil War", "id": 44},
    )

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None:
            return None
        if _PENDING.search(item.title):
            item.title = _PENDING.sub("", item.title).strip()
            item.is_sold = True
        return item
