"""LugerMan (lugerman.com).

A Luger specialist: Lugers above all, with the C96s, Tokarevs and other
collector pistols and rifles that come through the shop. WooCommerce with the
Store API answering. Read: Curio and Relics, Other Firearms, Rifles and Luger
45 ACP. Not read: the Luger parts, restoration services and modern firearms.

**Raffles are left out.** A raffle ticket is a product in their Firearms
section at $25 or $50, titled for the gun it might win, and taken at face
value it is a Luger for twenty-five dollars.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://lugerman.com/"

_RAFFLE = re.compile(r"\braffles?\b|\btickets?\b", re.I)


class LugerManScraper(WooStoreApiScraper):
    slug = "lugerman"
    name = "LugerMan"
    base_url = SITE_BASE
    description = "Luger specialist: Lugers, C96s and other collector pistols and rifles."
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-06"
    shipping_note = "No shipping policy published on the site; checked 2026-10-06"

    sources = (
        {"category": "Curio and Relics", "id": 73},
        {"category": "Other Firearms", "id": 57},
        {"category": "Rifles", "id": 74},
        {"category": "Luger 45 ACP", "id": 53},
    )

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None:
            return None
        categories = " ".join(
            str(c.get("name") or "") for c in product.get("categories") or [] if isinstance(c, dict)
        )
        if _RAFFLE.search(item.title) or _RAFFLE.search(categories):
            return None
        return item
