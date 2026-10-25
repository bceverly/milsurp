"""Rainier Arms (rainierarms.com).

A Washington AR shop with a large suppressor wall -- B&T, Q, Dead Air,
SilencerCo, Rugged, Thunder Beast and more, 211 on 2026-10-25 -- added that day
with the Suppressors Type. Magento; robots.txt asks for eight seconds between
requests and allows the ``?p=N`` paging this reads, disallowing only sort
order and ``limit=all``.

Read: "Suppressors" only. A part sold there is left out by name
(``suppressors.names_a_part``).
"""

from __future__ import annotations

from bs4 import Tag

from ..services import suppressors
from .base import ScrapedItem
from .magento import MagentoScraper

SITE_BASE = "https://www.rainierarms.com/"


class RainierArmsScraper(MagentoScraper):
    slug = "rainier-arms"
    name = "Rainier Arms"
    base_url = SITE_BASE
    description = "Washington AR shop's suppressor wall: B&T, Q, Dead Air, SilencerCo and more."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "new"
    newsletter_url = None
    newsletter_note = "No signup form found on the site; checked 2026-10-25"
    shipping_note = "Suppressors transfer through a Class III dealer; shipping rates at checkout"
    shipping_source = f"{SITE_BASE}shipping/"
    #: Their robots.txt asks for eight.
    min_request_delay: float = 8.0

    sources = ({"category": "Suppressors", "url": f"{SITE_BASE}suppressors/"},)

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is None or suppressors.names_a_part(item.title):
            return None
        return item
