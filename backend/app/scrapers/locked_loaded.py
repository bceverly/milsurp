"""Locked & Loaded (lockedloaded.com).

A gun shop asked for on 2026-10-20 for concealed carry pistols and revolvers.
Coreware's storefront with a Meilisearch catalog (see
:mod:`app.scrapers.coreware_search`): about 5,400 handguns in stock that day,
282 of them on the shop's own shelf and the rest at its distributors; about
2,250 in the carry calibers, which are what is read.
"""

from __future__ import annotations

from .coreware_search import CorewareSearchScraper

SITE_BASE = "https://lockedloaded.com/"


class LockedLoadedScraper(CorewareSearchScraper):
    slug = "locked-loaded"
    name = "Locked & Loaded"
    base_url = SITE_BASE
    description = "Gun shop with a distributor's catalog: carry pistols and revolvers, new."
    default_interval_minutes = 1440
    newsletter_url = SITE_BASE
    newsletter_note = '"Join Our Mailing List" form in the footer of every page'
    shipping_note = (
        "No firearm shipping rate published; charges set at checkout (checked 2026-10-20)"
    )
    shipping_source = "https://lockedloaded.com/store-policies"
