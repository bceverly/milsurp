"""G4G Guns (g4gguns.com).

Asked for on 2026-10-20 for concealed carry pistols and revolvers; a
distributor's catalog of new guns, read as :mod:`app.scrapers.woo_carry` says.
WooCommerce behind Cloudflare, which lets this application through; robots.txt
allows the store.
"""

from __future__ import annotations

from .woo_carry import WooCarryScraper

SITE_BASE = "https://g4gguns.com/"


class G4gGunsScraper(WooCarryScraper):
    slug = "g4g-guns"
    name = "G4G Guns"
    base_url = SITE_BASE
    description = "Online gun shop with a distributor's catalog: carry pistols and revolvers, new."
    default_interval_minutes = 1440
    newsletter_url = f"{SITE_BASE}subscribe/"
    newsletter_note = "Subscribe page, linked from the site's navigation"
    shipping_note = "No firearm shipping rate published (checked 2026-10-20)"
    shipping_source = "https://g4gguns.com/store-policies/"

    #: Category ids from /wp-json/wc/store/v1/products/categories, 2026-10-20.
    sources = (
        {"category": "Semi-Auto Handguns", "id": 179},
        {"category": "Revolvers", "id": 172},
        {"category": "Derringers", "id": 197},
    )
