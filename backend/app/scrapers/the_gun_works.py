"""The Gun Works Muzzleloading Emporium (thegunworks.com).

A Springfield, Oregon muzzleloading shop, asked for on 2026-10-20 "for
flintlock and percussion rifles and pistols": custom-built longrifles and
pistols, used customs, and new Traditions, Lyman and Uberti guns. WooCommerce
on WP Engine, behind Cloudflare, with the Store API answering. robots.txt
allows the store and asks for ten seconds between requests, which the
fetcher honors.

Read: the finished guns in each maker's section and in the two used
sections -- rifles, pistols and percussion revolvers, about a hundred on
2026-10-20. Not read: the parts sections under each maker (locks, triggers,
barrels, about four hundred), the kits (a gun in pieces), the used shotguns
and the one used cartridge gun, and everything else the shop sells (books,
flints, leather, horns). A modern inline that turns up in a section read is
left out by name, as at Muzzle-Loaders.com, and so is a part the used
sections sell beside the guns (:func:`is_part`).
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .muzzle_loaders import INLINE
from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://thegunworks.com/"

#: A title part that says the listing is a part, not a gun: the used sections
#: also carry "Original / Lock / 1842 Model / Percussion" and "Colt 2nd
#: Generation / Pin" (2026-10-20), each "/" an en dash in the shop's titles.
_A_PART = re.compile(
    r"^(?:locks?|pins?|barrels?|stocks?|triggers?|hammers?|nipples?|parts?|kits?|"
    r"cylinders?|grips?|springs?)$",
    re.I,
)


def is_part(title: str) -> bool:
    """Whether one of the title's dash-separated parts names a part alone."""
    return any(_A_PART.match(piece.strip()) for piece in re.split("\\s[\u2013\u2014-]\\s", title))


class TheGunWorksScraper(WooStoreApiScraper):
    slug = "the-gun-works"
    name = "The Gun Works"
    base_url = SITE_BASE
    description = (
        "Oregon muzzleloading shop: custom and production flintlock and percussion "
        "rifles, pistols and revolvers."
    )
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-20"
    shipping_note = "No firearm shipping rate published; checked 2026-10-20"

    #: Category ids from /wp-json/wc/store/v1/products/categories, 2026-10-20.
    sources = (
        {"category": "Custom Muzzleloading Rifles", "id": 120},
        {"category": "Custom Muzzleloading Pistols", "id": 147},
        {"category": "Used Muzzleloading Rifles", "id": 4380},
        {"category": "Used Muzzleloading Pistols", "id": 4404},
        {"category": "Used Muzzleloading Rifles", "id": 4433},
        {"category": "Used Muzzleloading Pistols", "id": 4407},
        {"category": "Muzzleloading Rifles", "id": 128},  # Traditions
        {"category": "Muzzleloading Rifles", "id": 139},  # Lyman
        {"category": "Muzzleloading Pistols", "id": 130},  # Traditions
        {"category": "Muzzleloading Pistols", "id": 148},  # Lyman
        {"category": "Percussion Revolvers", "id": 132},  # Traditions
        {"category": "Percussion Revolvers", "id": 4425},  # Uberti
    )

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None or INLINE.search(item.title) or is_part(item.title):
            return None
        return item
