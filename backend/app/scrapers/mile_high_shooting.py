"""Mile High Shooting Accessories (milehighshooting.com).

A Colorado precision-rifle shop, added on 2026-10-25 with the Suppressors Type:
Thunder Beast, Abel and HUXWRX cans, about a hundred, at its own prices. A
BigCommerce Stencil store; robots.txt disallows sorting and the faceted
``_bc_fsnf`` filters, and nothing this reads.

Read: "Suppressors" only. Its titles often name only the maker and model
("Abel: Pi, FDE", "HUXWRX: Flow Range 36 Ti"), so the section is what says
suppressor (app/services/suppressors.py). A part sold there -- a mount, a cap
-- is left out by name (``suppressors.names_a_part``), as is everything in
"Suppressor Accessories".
"""

from __future__ import annotations

from bs4 import Tag

from ..services import suppressors
from .base import ScrapedItem
from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://www.milehighshooting.com/"


class MileHighShootingScraper(BigCommerceScraper):
    slug = "mile-high-shooting"
    name = "Mile High Shooting"
    base_url = SITE_BASE
    description = "Colorado precision-rifle shop: Thunder Beast, Abel and HUXWRX suppressors."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "new"
    newsletter_url = None
    newsletter_note = "No signup form found on the site; checked 2026-10-25"
    shipping_note = (
        "Suppressors go only to a Class III dealer, transferred on a Form 3; "
        "shipping rates at checkout"
    )
    shipping_source = f"{SITE_BASE}shipping-returns/"

    sources = ({"category": "Suppressors", "url": f"{SITE_BASE}suppressors/"},)

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is None or suppressors.names_a_part(item.title):
            return None
        return item
