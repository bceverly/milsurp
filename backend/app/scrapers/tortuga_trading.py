"""Tortuga Trading (tortugatrading.com).

A Florida dealer in original antique arms -- English flintlock dueling pistols,
cased pairs, blunderbusses, Continental military holster pistols -- most priced
in five figures. About forty guns on 2026-10-08. A Shopify shop, read through
``products.json``.

One collection, Firearms, and within it only what the shop files as a firearm
(``product_type`` "Firearms" or "ANTIQUE Firearms"): the same collection holds
powder flasks, a bronze cannon and militaria.
"""

from __future__ import annotations

from typing import Any

from .base import ScrapedItem
from .shopify import ShopifyScraper

SITE_BASE = "https://www.tortugatrading.com/"

#: What the shop files its guns under; the rest of the collection is not one.
FIREARM_TYPES = frozenset({"firearms", "antique firearms"})


class TortugaTradingScraper(ShopifyScraper):
    slug = "tortuga-trading"
    name = "Tortuga Trading"
    base_url = SITE_BASE
    description = "Florida dealer in original antique flintlock and percussion arms."
    default_interval_minutes = 1440
    newsletter_url = SITE_BASE
    newsletter_note = "Klaviyo signup on the home page"
    shipping_note = "No firearm shipping rate published; checked 2026-10-08"
    shipping_source = "https://www.tortugatrading.com/pages/shipping-policy"

    sources = ({"category": "Antique Firearms", "url": f"{SITE_BASE}collections/firearms"},)

    def item_from_product(
        self, product: dict[str, Any], collection: str, category: str
    ) -> ScrapedItem | None:
        if str(product.get("product_type") or "").strip().lower() not in FIREARM_TYPES:
            return None
        return super().item_from_product(product, collection, category)
