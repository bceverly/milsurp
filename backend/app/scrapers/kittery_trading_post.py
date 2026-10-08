"""Kittery Trading Post (kitterytradingpost.com).

A Kittery, Maine outfitter whose used-handgun rack is the largest found in the
October 2026 concealed-carry survey: 788 listings on 2026-10-08, about four in
ten of them carry guns -- J-frames (442, 637, 642), Taurus 605s, Colt Detective
Specials, Kimber Micro 9s, P365 XLs, Shield Plus and Walther PPS pistols.

A stock BigCommerce shop. One section is read, ``/used-guns/handguns/``; the
new-gun catalog and the rest of the store (clothing, fishing, home goods) are
not. robots.txt asks a handful of named crawlers to wait ten seconds and turns
away only BigCommerce's own filter URLs, which the walk never builds.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://www.kitterytradingpost.com/"


class KitteryTradingPostScraper(BigCommerceScraper):
    slug = "kittery-trading-post"
    name = "Kittery Trading Post"
    base_url = SITE_BASE
    description = "Maine outfitter's used-handgun rack: carry pistols and revolvers among them."
    default_interval_minutes = 1440
    requires_browser = False
    newsletter_url = SITE_BASE
    newsletter_note = "Klaviyo signup form on the home page"
    shipping_note = "Handguns ship for a flat $50, to a dealer in the buyer's state"
    shipping_source = "https://www.kitterytradingpost.com/firearm-purchase-faq/"
    shipping_handgun = 50.0

    sources = ({"category": "Used Handguns", "url": f"{SITE_BASE}used-guns/handguns/"},)
