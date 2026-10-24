"""Antique Weapon Store (antiqueweaponstore.com).

An Asheville, North Carolina dealer in antique arms and armor, asked for on
2026-10-24 with the other black powder shops. Mostly swords, polearms and
armor; its Firearms category is original flintlock, percussion, matchlock and
wheellock guns, every one made before 1898 as its terms of sale say -- 162 on
2026-10-24, 31 of them in stock. WooCommerce, with the Store API answering and
robots.txt asking nothing of it.

Read: the Firearms category, the sold guns with it (kept as sold). Not read:
everything else. The category also files a few things that are not guns --
a bronze cannon barrel and model cannons, wheellock spanners, a holster, a
line-throwing pistol, "vampire killing kits" -- and those are left out by
name (:func:`is_not_a_gun`). A gun priced at zero is priced on request, and
reads as unpriced (the Store API base's rule).
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://www.antiqueweaponstore.com/"

#: What the Firearms category files beside the guns (2026-10-24). Not a
#: bayonet, which is sold *with* a gun ("Rifle Musket, with Bayonet"), nor a
#: tool company ("Providence Tool Co."), nor a holster a gun comes with.
_NOT_A_GUN = re.compile(
    r"\b(?:cannons?|killing\s+kits?|spanners?|tools?(?!\s+co\b)|line[\s-]throwing|powder\s+(?:flask|horn|measure)|"
    r"bullet\s+mou?ld|(?<!with\s)holsters?|lock\s+only)\b",
    re.I,
)


def is_not_a_gun(title: str) -> bool:
    """Whether the title names something the Firearms category sells that is no gun."""
    return bool(_NOT_A_GUN.search(title))


class AntiqueWeaponStoreScraper(WooStoreApiScraper):
    slug = "antique-weapon-store"
    name = "Antique Weapon Store"
    base_url = SITE_BASE
    description = (
        "North Carolina antique arms dealer: original flintlock, percussion, matchlock "
        "and wheellock muskets, rifles and pistols."
    )
    default_interval_minutes = 1440
    newsletter_url = (
        "https://visitor.r20.constantcontact.com/manage/optin?v=0019KAcuqVaX-593ov2L1kH9-"
        "H4ADgzoRFP1t8qogS38x_AOVzqNOKd_rnBhj7BOBjVU7mavQaJ-sRPjxPTQfGFYfRdEFU-xHX3pFqpynWQkd"
        "eLyamAWx7XegBboGBvHwLRRVcCYIOd5dhXzlB3TWOI141C4mSiQpoj"
    )
    newsletter_note = "Constant Contact signup, linked from every page"
    #: Shipping is in the listed price.
    shipping_long_gun = 0.0
    shipping_handgun = 0.0
    shipping_note = "Shipping included in the listed price (UPS or USPS, insured)"
    shipping_source = f"{SITE_BASE}terms-of-sale/#shipping"

    #: Category id from /wp-json/wc/store/v1/products/categories, 2026-10-24.
    sources = ({"category": "Antique Firearms", "id": 15},)

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None or is_not_a_gun(item.title):
            return None
        return item
