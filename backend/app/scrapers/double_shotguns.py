"""Double Shotguns (doubleshotguns.com).

A Port Matilda, Pennsylvania shop of new and used sporting guns, trading
since 1974, added on 2026-11-06 when the application widened to every used
shotgun: Browning Citoris, AYA 4/53s, Remington Model 31s and 1100s, Savage
220s and CZ Mallards, beside rifles and handguns. WooCommerce with the Store
API answering; robots.txt turns away only WooCommerce's own working files.

Read: the three top-level sections, Shotguns (43 that day), Rifles (44) and
Pistols & Handguns (32), each of which holds its own children (over/under,
side-by-side, pump and automatic; bolt, lever and semi-auto; revolvers and
pistols). Every one priced and in stock. The shop sells new guns beside used
ones and says which nowhere but in the odd description, so it is ``mixed``
and most listings stay unknown.

**Each description names the gun's serial**: "This CZ Mallard (SKU 17743,
Serial 0754056) is a 20 gauge O/U...". It is taken out, as at Greentop:
a serial number has no business being republished here.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://doubleshotguns.com/"

#: ", Serial 0754056" -- and "Serial: 0754056", "Serial # 0754056", or a
#: serial standing first in the parentheses.
_SERIAL = re.compile(r",?\s*\bSerial\b\s*(?:#|No\.?|Number)?\s*:?\s*[\w-]+", re.I)


def without_serial(text: str | None) -> str | None:
    """The text with any serial number taken out."""
    if not text:
        return text
    return _SERIAL.sub("", text).replace("( ", "(").replace("()", "").strip() or None


class DoubleShotgunsScraper(WooStoreApiScraper):
    slug = "double-shotguns"
    name = "Double Shotguns"
    base_url = SITE_BASE
    description = (
        "Pennsylvania shop of new and used sporting shotguns, rifles and handguns, "
        "trading since 1974."
    )
    default_interval_minutes = 1440
    sells = "mixed"
    newsletter_url = SITE_BASE
    newsletter_note = '"Sign Up to Our Newsletter" form in the footer of every page'
    shipping_note = "No firearm shipping rate published; checked 2026-11-06"
    shipping_source = f"{SITE_BASE}ordering-shipping/"

    #: Category ids from /wp-json/wc/store/v1/products/categories, 2026-11-06.
    sources = (
        {"category": "Shotguns", "id": 38},
        {"category": "Rifles", "id": 34},
        {"category": "Handguns", "id": 31},
    )

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is not None:
            item.description = without_serial(item.description)
        return item
