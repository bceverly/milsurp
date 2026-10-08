"""We Buy Guns (store.webuyguns.com).

A Westfield, Indiana shop that buys guns and sells them on: every handgun in its
online store is used. 38 listings on 2026-10-08, about three in ten of them
carry guns (Glock 43Xs, P365s, a Shield, an LC9, an S&W Model 36, a Detective
Special). Small, and read because it is all used.

A stock BigCommerce shop; ``/handguns/`` is the one section read. robots.txt
asks a handful of named crawlers to wait ten seconds and turns away only
BigCommerce's own filter URLs.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://store.webuyguns.com/"


class WeBuyGunsScraper(BigCommerceScraper):
    slug = "we-buy-guns"
    name = "We Buy Guns"
    base_url = SITE_BASE
    description = "Indiana shop selling the used handguns it buys, carry guns among them."
    default_interval_minutes = 1440
    requires_browser = False
    newsletter_url = SITE_BASE
    newsletter_note = "Newsletter form in the store's footer"
    shipping_note = "Handguns ship FedEx Express, long guns FedEx Ground; no cost published"
    shipping_source = "https://store.webuyguns.com/terms-conditions/"

    sources = ({"category": "Used Handguns", "url": f"{SITE_BASE}handguns/"},)
