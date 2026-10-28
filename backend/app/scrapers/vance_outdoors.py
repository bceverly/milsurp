"""Vance Outdoors (vanceoutdoors.com) -- the used guns.

A Columbus, Ohio shop on the same ColdFusion storefront as Sportsman's Outdoor
(:mod:`app.scrapers.sportsmans_outdoor`), so it is that scraper with its own
section and stock label. Added on 2026-10-28 with the used-gun shops asked for
to catch used carry pistols: 36 in the used section that day, mostly Ohio
State Highway Patrol trade-ins (Remington 870 Police Magnums, Glock 22s) and
Bulgarian Makarovs -- but only 3 in stock, the rest "Notify Me" archive pages,
which are left out as at Sportsman's.

robots.txt allows the category and product pages; their cart, search and
``notify_me`` pages are not asked for.
"""

from __future__ import annotations

from bs4 import Tag

from .sportsmans_outdoor import SportsmansOutdoorScraper

SITE_BASE = "https://www.vanceoutdoors.com/"


class VanceOutdoorsScraper(SportsmansOutdoorScraper):
    slug = "vance-outdoors"
    name = "Vance Outdoors"
    base_url = SITE_BASE
    description = (
        "Ohio shop's used guns: Highway Patrol trade-ins and surplus pistols. Only "
        "in-stock listings are read."
    )
    sells = "used"
    shipping_long_gun = 24.99
    shipping_handgun = 24.99
    shipping_note = "Firearm shipping $24.99 standard, $29.99 select, $39.99 express"
    shipping_source = f"{SITE_BASE}shipping_costs_times.cfm"
    newsletter_url = SITE_BASE
    newsletter_note = '"Join Our Mailing List for Exclusive Savings!" form in the footer'

    sources = ({"category": "Used Firearms", "url": f"{SITE_BASE}category.cfm/outdoors/used-guns"},)

    def card_in_stock(self, card: Tag) -> bool:
        """Vance labels it in words: "In Stock", or "Notify Me When Available"."""
        status = card.select_one(".product-status")
        return status is not None and "in stock" in status.get_text(" ", strip=True).lower()
