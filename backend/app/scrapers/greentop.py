"""Greentop (greentop.com).

A Virginia hunting and shooting store with a used-gun counter: 144 used pistols
and 41 used revolvers on 2026-10-08, about three in ten of them carry guns --
Ruger EC9s, M&P45 Shields, Taurus GX4s, Glock 19s and 27s, Kimber Ultra CDPs,
Walther PPK/Ss, Kel-Tec P3ATs. Titles state the barrel length and condition.

Magento. Two sections are read, Used Pistols and Used Revolvers, each paged by
``?p=``. Not read: their used rifles and shotguns (not what this was built
for), the new-gun catalog, and the archive of sold used guns. robots.txt asks
for five seconds between requests, which the scanner honors, and turns away
only Magento's sort and page-size parameters, which the walk never builds.

**The serial number comes out of the title.** Greentop write every used gun
the same way -- "Used GLOCK 19V 9X19 CHFR895 4" MATTE G GTO392819": make,
model, caliber, *serial*, barrel, finish, grade and their stock code -- and the
serial is always the word just before the barrel length. Left in, it is a gun's
serial number on a public page here, and the armory's discovery read each one
as a model designation ("CHFR895", "CEZE544") and proposed it, a new junk row
for every gun on every scan.
"""

from __future__ import annotations

import re

from bs4 import Tag

from .base import ScrapedItem
from .magento import MagentoScraper

SITE_BASE = "https://www.greentop.com/"


#: The word before a stated barrel length: '... 9X19 CHFR895 4" MATTE ...'.
_SERIAL = re.compile(r"\s+\S+(?=\s+\d{1,2}(?:\.\d+)?[\"”]\s)")


def without_serial(title: str) -> str:
    """A Greentop title with the gun's serial number taken out."""
    return _SERIAL.sub("", title, count=1)


class GreentopScraper(MagentoScraper):
    slug = "greentop"
    name = "Greentop"
    base_url = SITE_BASE
    description = "Virginia store's used pistols and revolvers, carry guns among them."
    default_interval_minutes = 1440
    newsletter_url = "https://www.greentop.com/email-sign-up/"
    shipping_note = "Firearm shipping free: handguns 2nd Day Air, long guns Ground"
    shipping_source = "https://www.greentop.com/shipping-info/"
    shipping_handgun = 0.0
    shipping_long_gun = 0.0

    sources = (
        {"category": "Used Pistols", "url": f"{SITE_BASE}shooting/used-guns/pistols/"},
        {"category": "Used Revolvers", "url": f"{SITE_BASE}shooting/used-guns/revolvers/"},
    )

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is not None:
            item.title = without_serial(item.title)
        return item
