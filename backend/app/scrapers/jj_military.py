"""J & J Military Antiques (jjmilitary.com).

A Pennsylvania dealer in American military antiques. Its Antique Firearms
section was 94 listings on 2026-10-08: Jenks and Ward-Burton carbines, Spencer
and Sharps carbines, Springfield and contract muskets, Colt and Remington
percussion revolvers. WooCommerce with the Store API answering.

**The section holds parts and tools too**, and they are left out. About thirty
of the 94 are a mainspring, a hinge pin, a sight screw, a rifle tool or an
empty factory case -- and a title like "Spencer M-1865 Carbine & Rifle Hinge
Pivot Screw" names a gun, which is enough for the classifier to file a $18
screw as a carbine. The shop files every one of them under "Gun Parts",
"Tools, Tompions, Cap Tins & Accessories" or "Holsters, Slings, Belts,
Buckles, Hangers, Boxes" as well, and a listing filed under any of those is
not read. No gun on the shelf was.

A gun priced "0" is on request; the Store API base reads that as no price.
The bayonets, swords, molds and flasks that are most of the shop are not read.
"""

from __future__ import annotations

from typing import Any

from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper, html_to_text

SITE_BASE = "https://jjmilitary.com/"

#: Sections a listing is filed in alongside the guns when it is not one.
NOT_GUNS = frozenset(
    {
        "Gun Parts",
        "Tools, Tompions, Cap Tins & Accessories",
        "Holsters, Slings, Belts, Buckles, Hangers, Boxes",
    }
)


class JjMilitaryScraper(WooStoreApiScraper):
    slug = "jj-military"
    name = "J & J Military Antiques"
    base_url = SITE_BASE
    description = "Pennsylvania dealer in American military antique firearms."
    default_interval_minutes = 1440
    newsletter_url = "https://jjmilitary.com/subscribe-to-our-mailing-list/"
    shipping_note = (
        "No shipping rates published; card orders ship in 2-7 days, per the terms of sale"
    )
    shipping_source = "https://jjmilitary.com/terms-of-sale/"

    sources = ({"category": "Antique Firearms", "id": 86},)

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None:
            return None
        filed = {
            html_to_text(str(c.get("name") or "")) or ""
            for c in product.get("categories") or []
            if isinstance(c, dict)
        }
        if filed & NOT_GUNS:
            return None
        return item
