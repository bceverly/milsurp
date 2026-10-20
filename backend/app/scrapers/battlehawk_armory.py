"""Battlehawk Armory (battlehawkarmory.com).

A Grimes, Iowa gun shop, asked for on 2026-10-20 for concealed carry pistols
and revolvers. Coreware's older storefront (see
:mod:`app.scrapers.coreware_store`): 5,911 handguns in stock that day, 772 of
them in the shop, and a used-pistol section. The carry calibers are read.
"""

from __future__ import annotations

from .coreware_store import CorewareStoreScraper

SITE_BASE = "https://battlehawkarmory.com/"


class BattlehawkArmoryScraper(CorewareStoreScraper):
    slug = "battlehawk-armory"
    name = "Battlehawk Armory"
    base_url = SITE_BASE
    description = (
        "Iowa gun shop with a distributor's catalog: carry pistols and revolvers, new and used."
    )
    default_interval_minutes = 1440
    newsletter_url = SITE_BASE
    newsletter_note = "Signup form in the footer of every page"
    shipping_note = "No firearm shipping rate published (checked 2026-10-20)"
    shipping_source = "https://battlehawkarmory.com/store-policies"
    image_cdn = "cdn33.coreware.com"

    #: Category ids from the shop's productCategories, 2026-10-20.
    sources = (
        {"category": "Used Pistols", "id": 2329, "used": True},
        {"category": "Pistols", "id": 1719},
        {"category": "Revolvers", "id": 1751},
    )
