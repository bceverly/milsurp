"""Axis Arms (axisarmsonline.com).

WooCommerce behind an Elementor loop template, which is what makes it different
from the others: the card is an ``<article>`` full of Elementor widgets rather
than the stock product markup, and the widget holding the *price* is an ``h2``
while the one holding the *name* is an ``h1``. Reading headings in the usual
order therefore titled every rifle "$ 2,449.99 Original price was: …".

Two sections, one scraper, the same shape as Empire Arms.
"""

from __future__ import annotations

from .woocommerce import WooCommerceScraper

SITE_BASE = "https://axisarmsonline.com/"


class AxisArmsScraper(WooCommerceScraper):
    slug = "axis-arms"
    name = "Axis Arms"
    base_url = SITE_BASE
    description = "Curio and relic rifles and handguns, listed in two sections."
    requires_browser = False
    default_interval_minutes = 1440

    sources = (
        {"category": "Rifles", "url": f"{SITE_BASE}product-category/rifles/"},
        {"category": "Handguns", "url": f"{SITE_BASE}product-category/handguns/"},
    )

    #: An h1 per card, which is unusual and is the product name. The h2 beside
    #: it is the price widget.
    title_selectors = (
        "h1.elementor-heading-title",
        "h1",
        *WooCommerceScraper.title_selectors,
    )
