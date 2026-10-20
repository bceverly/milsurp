"""Frisco Guns (friscoguns.com).

Asked for on 2026-10-20 for concealed carry pistols and revolvers; a
distributor's catalog of new guns, read as :mod:`app.scrapers.woo_carry` says.
WooCommerce behind Cloudflare, which lets this application through; robots.txt
allows everybody but the AI-training crawlers it names.
"""

from __future__ import annotations

from .woo_carry import WooCarryScraper

SITE_BASE = "https://friscoguns.com/"


class FriscoGunsScraper(WooCarryScraper):
    slug = "frisco-guns"
    name = "Frisco Guns"
    base_url = SITE_BASE
    description = "Online gun shop with a distributor's catalog: carry pistols and revolvers, new."
    default_interval_minutes = 1440
    newsletter_url = SITE_BASE
    newsletter_note = '"Newsletter Sign Up" form on the home page'
    shipping_note = "Calculated at checkout by order amount and destination (checked 2026-10-20)"
    shipping_source = "https://friscoguns.com/shipping-returns/"

    #: Category ids from /wp-json/wc/store/v1/products/categories, 2026-10-20.
    sources = (
        {"category": "Semi-Auto Handguns", "id": 284},
        {"category": "Revolvers", "id": 313},
        {"category": "Derringers", "id": 331},
    )
