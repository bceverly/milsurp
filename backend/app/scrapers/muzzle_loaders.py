"""Muzzle-Loaders.com.

The largest catalog of reproduction black powder guns found in the October 2026
survey: Pedersoli, Pietta, Investarm, Traditions and Lyman rifles, pistols and
revolvers, about 240 traditional sidelock guns in two collections. A Shopify
shop, read through ``products.json``.

Two collections are read: Traditional Muzzleloaders and Muzzleloader Pistols.
Not read: the kits (a gun in pieces belongs with Parts kits, and these are
hobby kits rather than surplus), the inline muzzleloaders -- about 350 of the
shop's 1,875 products, modern hunting guns rather than percussion or flintlock
-- and everything else (powder, patches, parts). An inline that turns up in the
two collections read is left out by name.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .shopify import ShopifyScraper

SITE_BASE = "https://www.muzzle-loaders.com/"

#: Modern inline muzzleloaders, by the word or by the line.
_INLINE = re.compile(
    r"\b(?:in[\s-]?line|209|vortek|accura|optima|wolf|pursuit|triumph|encore|impact|"
    r"buckstalker|strikerfire|nitrofire|code\s+black)\b",
    re.I,
)


class MuzzleLoadersScraper(ShopifyScraper):
    slug = "muzzle-loaders"
    name = "Muzzle-Loaders.com"
    base_url = SITE_BASE
    description = "Reproduction flintlock and percussion rifles, pistols and revolvers."
    default_interval_minutes = 1440
    newsletter_url = SITE_BASE
    newsletter_note = "Klaviyo signup on the home page"
    shipping_note = "No firearm shipping rate published; checked 2026-10-08"

    sources = (
        {
            "category": "Traditional Muzzleloaders",
            "url": f"{SITE_BASE}collections/traditional-muzzleloaders",
        },
        {"category": "Muzzleloader Pistols", "url": f"{SITE_BASE}collections/muzzleloader-pistols"},
    )

    def item_from_product(
        self, product: dict[str, Any], collection: str, category: str
    ) -> ScrapedItem | None:
        item = super().item_from_product(product, collection, category)
        if item is None or _INLINE.search(item.title):
            return None
        return item
