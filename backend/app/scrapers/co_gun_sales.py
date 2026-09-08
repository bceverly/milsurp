"""CO Gun Sales (cogunsales.com).

Stock WooCommerce throughout — cards, prices and "next" link all where the base
class expects them, so this is the whole scraper.

The roadmap recorded their entry URL as page 6 of the category, which is where
somebody happened to be browsing when it was written. Pagination is followed
from the shop's own "next" link, so it starts at page one.
"""

from __future__ import annotations

from .woocommerce import WooCommerceScraper

SITE_BASE = "https://cogunsales.com/"


class CoGunSalesScraper(WooCommerceScraper):
    slug = "co-gun-sales"
    name = "CO Gun Sales"
    base_url = SITE_BASE
    description = "Colorado dealer; their Curio & Relic (C&R) section is read."
    requires_browser = False
    default_interval_minutes = 1440

    sources = (
        {"category": "Curio & Relic", "url": f"{SITE_BASE}product-category/curio-relics-cr/"},
        {
            # The full path, not /product-category/parts-kits/. That shorter
            # URL answers 200 with a page of sub-category tiles -- "FAL Parts
            # (23)", "Luger Parts (1)" -- and only a dozen products among them.
            #
            # 27 listings, and not all of them kits: a $9.99 cleaning kit, a
            # $24.95 service kit and a gas block are filed here too. The
            # classifier now requires a listing to say "kit" of its own before
            # a section heading may call it one -- see _is_a_parts_kit.
            "category": "Parts Kits",
            "url": f"{SITE_BASE}product-category/parts-accessories/parts-kits/",
        },
    )
