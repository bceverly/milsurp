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
    )
