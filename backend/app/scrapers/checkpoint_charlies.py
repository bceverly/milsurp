"""Checkpoint Charlie's (checkpointcharlies.com).

Stock WooCommerce. The one thing worth noting is that the section is a product
*tag* rather than a category — ``/product-tag/cr/`` — which changes nothing
here: a tag archive renders the same product loop and paginates the same way.
It is recorded because the URL looks like a mistake otherwise.
"""

from __future__ import annotations

from .woocommerce import WooCommerceScraper

SITE_BASE = "https://checkpointcharlies.com/"


class CheckpointCharliesScraper(WooCommerceScraper):
    slug = "checkpoint-charlies"
    name = "Checkpoint Charlie's"
    base_url = SITE_BASE
    description = "Collector dealer; the C&R-tagged stock is read."
    requires_browser = False
    default_interval_minutes = 1440

    sources = ({"category": "Curio & Relic", "url": f"{SITE_BASE}product-tag/cr/"},)
