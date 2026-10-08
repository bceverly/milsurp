"""Old Steel Arsenal (oldsteelarsenal.com).

A Plano, Texas shop selling consigned and acquired guns: Finnish Mosins, K98ks
and Swedish Mausers, a Hakim, Garands, West German police P6s, beside used
modern guns. Measured 2026-10-08 at 321 firearms, every one priced, about half
of them military. WooCommerce with the Store API answering.

Three of the Firearms category's children are read: Rifles, Pistols and
Revolvers. Not read: NFA (suppressors, SBRs and transferable machine guns),
Shotguns (modern sporting guns), "Other Firearms" (one listing), and the rest
of the shop -- 1,170 products in all, most of them optics, lights and parts.
robots.txt turns away only WooCommerce's own working files.
"""

from __future__ import annotations

from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://oldsteelarsenal.com/"


class OldSteelArsenalScraper(WooStoreApiScraper):
    slug = "old-steel-arsenal"
    name = "Old Steel Arsenal"
    base_url = SITE_BASE
    description = "Texas dealer in consigned military surplus and used rifles and handguns."
    default_interval_minutes = 1440
    newsletter_url = SITE_BASE
    newsletter_note = 'Signup box on every page ("$20 off your first order over $300")'
    shipping_note = "No shipping rates published; checked 2026-10-08"

    sources = (
        {"category": "Rifles", "id": 77},
        {"category": "Pistols", "id": 78},
        {"category": "Revolvers", "id": 35},
    )
