"""October Country (octobercountry.com).

A Coeur d'Alene, Idaho muzzleloading supplier, asked for on 2026-10-24 with
the other black powder shops: Traditions sidelock rifles and muskets, Pietta
percussion revolvers, a Pedersoli Hawken and the odd used gun, among a large
catalog of horns, bags, ramrods and balls. A BigCommerce Stencil store.

Read: "Used Black Powder Guns" (1 on 2026-10-24), "Rifles - Muzzleloaders"
(15, the used gun among them), "Muzzleloaders" (the Pedersoli, which the
rifle section does not carry) and "Revolvers" (10). The used section is read
first, so a gun filed in both is kept as used. Not read: the kits, and
"Pistols and Accessories", which held only accessories that day. A modern
inline in a section read is left out by name
(:data:`app.scrapers.muzzle_loaders.INLINE`): the rifle section sells a
Traditions Buckstalker beside the sidelocks -- and so is the loading stand
the Revolvers section sells beside the Piettas.

robots.txt asks nothing of the paths read; its ten-second crawl delay is
addressed to a list of AI and data crawlers, not to every agent.
"""

from __future__ import annotations

import re

from bs4 import Tag

from .base import ScrapedItem
from .bigcommerce import BigCommerceScraper
from .muzzle_loaders import INLINE

SITE_BASE = "https://www.octobercountry.com/"

#: The Revolvers section also sells the stands a revolver is loaded on
#: ("Traditions Loading Stand Revolver .44 cal", 2026-10-24).
_A_STAND = re.compile(r"\b(?:loading|display)\s+stand\b", re.I)


class OctoberCountryScraper(BigCommerceScraper):
    slug = "october-country"
    name = "October Country"
    base_url = SITE_BASE
    description = (
        "Idaho muzzleloading supplier: Traditions and Pedersoli sidelock rifles and "
        "muskets, Pietta percussion revolvers and the odd used gun."
    )
    requires_browser = False
    default_interval_minutes = 1440
    #: New guns, and a used section beside them.
    sells = "mixed"
    newsletter_url = SITE_BASE
    newsletter_note = "Newsletter signup form in the footer of every page"
    shipping_note = "Firearms ship UPS; freight varies by location, rates calculated at checkout"
    shipping_source = f"{SITE_BASE}shipping-returns-policy/"

    sources = (
        {
            "category": "Used Black Powder Guns",
            "url": f"{SITE_BASE}categories/Used-Black-Powder-Guns/",
        },
        # The category's own link double-encodes its hyphen, and so must this.
        {
            "category": "Muzzleloading Rifles",
            "url": f"{SITE_BASE}categories/Rifles-%252d-Muzzleloaders/",
        },
        {"category": "Muzzleloading Rifles", "url": f"{SITE_BASE}muzzleloaders/"},
        {"category": "Percussion Revolvers", "url": f"{SITE_BASE}categories/Revolvers/"},
    )

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is None or INLINE.search(item.title) or _A_STAND.search(item.title):
            return None
        item.is_new = not category.startswith("Used ")
        return item
