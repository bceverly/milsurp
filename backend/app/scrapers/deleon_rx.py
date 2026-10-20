"""DeLeon RX Guns and Ammo (deleonrxgunsandammo.com).

A De Leon, Texas pharmacy and gun counter, asked for on 2026-10-20 for
concealed carry pistols and revolvers. Coreware's older storefront (see
:mod:`app.scrapers.coreware_store`): 5,855 handguns in stock that day, 66 of
them in the store. The carry calibers are read.
"""

from __future__ import annotations

from .coreware_store import CorewareStoreScraper

SITE_BASE = "https://deleonrxgunsandammo.com/"


class DeleonRxScraper(CorewareStoreScraper):
    slug = "deleon-rx"
    name = "DeLeon RX Guns and Ammo"
    base_url = SITE_BASE
    description = (
        "Texas gun counter with a distributor's catalog: carry pistols and revolvers, new."
    )
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-20"
    shipping_note = "No firearm shipping rate published (checked 2026-10-20)"
    shipping_source = "https://deleonrxgunsandammo.com/store-policies"
    image_cdn = "cdn30.coreware.com"

    #: Category ids from the shop's productCategories, 2026-10-20. "Used &
    #: Refurbished" also holds optics and parts, which the caliber test drops.
    sources = (
        {"category": "Used & Refurbished", "id": 22764, "used": True},
        {"category": "Pistols", "id": 22644},
        {"category": "Revolvers", "id": 22676},
        {"category": "Break-Action Handguns", "id": 22459},
    )
