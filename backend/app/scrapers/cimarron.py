"""Cimarron Firearms (cimarron-firearms.com).

A Fredericksburg, Texas importer of Italian reproductions -- Uberti and Pietta
-- asked for on 2026-10-24 with the other black powder shops. Its cartridge
guns are sold through FFL dealers, but its own "How to Order" page says "Black
powder percussion arms may be purchased or ordered ... direct from Cimarron",
and that is the shelf read: the percussion revolvers, 24 on 2026-10-24, at
Cimarron's own prices. Its long guns held no percussion rifle that day (the
Sharps it sells is the cartridge 1874). Magento; robots.txt allows everything
and asks for three seconds between requests, inside the base class's five.

The section also files the cartridge conversions of the percussion patterns
("'62 Pocket Navy Conv 6\" 380 ACP"); they are read with it, and the
classifier's caliber rules tell the two apart.
"""

from __future__ import annotations

from .magento import MagentoScraper

SITE_BASE = "https://www.cimarron-firearms.com/"


class CimarronScraper(MagentoScraper):
    slug = "cimarron"
    name = "Cimarron Firearms"
    base_url = SITE_BASE
    description = (
        "Texas importer of Uberti and Pietta reproductions; its percussion "
        "revolvers, sold direct, at its own prices."
    )
    requires_browser = False
    default_interval_minutes = 1440
    #: An importer's new guns only.
    sells = "new"
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-24"
    shipping_note = (
        "Percussion arms sold direct; no shipping rate published (cartridge guns go "
        "through FFL dealers)"
    )
    shipping_source = f"{SITE_BASE}how-to-order/"

    sources = (
        {
            "category": "Percussion Revolvers",
            "url": f"{SITE_BASE}products/revolvers/percussion-revolvers-2.html",
        },
    )
