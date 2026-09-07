"""Ancestry Guns (ancestryguns.com).

WooCommerce. Their theme puts the product name in an ``h3`` and a "Share on:"
widget in the ``h2`` above it, which is the only thing that needed saying:
without the override every listing came back titled "Share on:".

Curio and Relic is the section worth having — that is the C&R-eligible stock,
which is what this application is about. They also sell modern firearms and a
large militaria collection, and neither is taken.
"""

from __future__ import annotations

from .woocommerce import WooCommerceScraper

SITE_BASE = "https://www.ancestryguns.com/"


class AncestryGunsScraper(WooCommerceScraper):
    slug = "ancestry-guns"
    name = "Ancestry Guns"
    base_url = SITE_BASE
    description = (
        "Missouri collector dealer. Their Curio and Relic section is read; the "
        "modern firearms and militaria are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = ({"category": "Curio & Relic", "url": f"{SITE_BASE}product-category/curio-relic/"},)

    #: The h2 above the name is a "Share on:" widget, so the h3 goes first.
    title_selectors = ("h3.upper", "h3", *WooCommerceScraper.title_selectors)
