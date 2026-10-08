"""Moka's Raifus (mokasraifus.com).

An importer-adjacent shop with the largest parts-kit shelf found in the
October 2026 survey: original-barrel kits from the Eastern Bloc and beyond (Yugo
M70s and M76s, Swiss StGW57, Czech UK59, HK G3K, Bulgarian PKM, a USGI M1A1
Thompson), and a small shelf of surplus guns (Radom P-83, Zastava M88 and M57,
Beretta 1934, SIG PE57). 1,318 products on 2026-10-08. WooCommerce with the
Store API answering, so the read is JSON throughout.

Two categories are read:

* **Firearms** (118), the shop's own gun shelf. Its "Surplus Firearms" and
  "C&R Firearms" sections are subsets of it, so reading those as well would only
  fetch the same products again. The API answers a category with its children
  too, and two of Firearms' children are not guns: Suppressors, and the ADAR
  line's 80% receivers, furniture and engraving service. So a product from this
  shelf is kept only when the shop filed it under "Firearms" itself, and never
  when it is filed as a suppressor.
* **Parts Kits and Misc Parts** (520), because it is the only home of some kits
  -- the Thompson is filed there and nowhere else -- and it holds every AK kit
  too. Most of it is single parts: barrels, bolt carriers, slides, sights. **Only
  a listing titled as a parts kit is kept**, the same line the rest of the
  application draws (a complete kit is a gun in pieces; a recoil spring is
  not). A "conversion kit" is a different thing -- the CZ75 Kadet .22 slide -- and
  is left out with the parts.

Not read: magazines, accessories, furniture, Khyber Pass goods and merch.

DBG Firearms resells a handful of their guns (five of DBG's 130 titles match
one here on 2026-10-08), so the two are different shops sharing some stock --
not one catalog under two names, as Gideon Tactical turned out to be.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper, html_to_text

SITE_BASE = "https://mokasraifus.com/"

#: The parts category's id. Listings from it are kept only when they are kits.
PARTS_CATEGORY = 34

#: A complete kit, by its title. "Parts Kit Build Clone" and "Original Barrel
#: Parts Kit" both say it; a barrel, a bolt carrier or a stock does not.
_PARTS_KIT = re.compile(r"\bparts?\s+kits?\b", re.I)

#: Kits that are not a gun in pieces.
_NOT_A_GUN_KIT = re.compile(r"\b(?:conversion|cleaning|repair|rebuild|spring)\s+kits?\b", re.I)


def _category_names(product: dict[str, Any]) -> set[str]:
    return {
        html_to_text(str(c.get("name") or "")) or ""
        for c in product.get("categories") or []
        if isinstance(c, dict)
    }


def is_a_whole_kit(title: str) -> bool:
    """Whether a title from the parts shelf names a complete parts kit."""
    return bool(_PARTS_KIT.search(title)) and not _NOT_A_GUN_KIT.search(title)


class MokasRaifusScraper(WooStoreApiScraper):
    slug = "mokas-raifus"
    name = "Moka's Raifus"
    base_url = SITE_BASE
    description = "Surplus parts kits with original barrels, and surplus pistols and rifles."
    default_interval_minutes = 1440
    newsletter_url = "https://mailchi.mp/befb944d24fd/email-signup"
    shipping_note = (
        "No shipping policy published; the site says orders other than parts kits "
        "ship in 5-7 business days"
    )

    sources = (
        {"category": "Firearms", "id": 1198},
        {"category": "Parts Kits", "id": PARTS_CATEGORY},
    )

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None:
            return None
        if label == "Parts Kits" and not is_a_whole_kit(item.title):
            return None
        if label == "Firearms":
            filed = _category_names(product)
            if "Firearms" not in filed or "Suppressors" in filed:
                return None
        return item
