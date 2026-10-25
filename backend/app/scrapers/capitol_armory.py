"""Capitol Armory (capitolarmory.com).

An Austin, Texas suppressor dealer -- SilencerCo's largest, and every other
maker beside it -- added on 2026-10-25 with the Suppressors Type: 334 cans,
each card with its price and "In stock" or "Out of stock". Magento with
Amasty's layered navigation; robots.txt allows the ``?p=N`` paging this reads
and disallows the filter and list-mode parameters.

Its grid is not ``li.product-item``: each card is a ``.product-item-info``,
which is what ``card_selector`` says. Read: "Suppressors" only; parts sold
there are left out by name (``suppressors.names_a_part``), and its own
accessory sections (mounts, caps, covers) are not read.
"""

from __future__ import annotations

from bs4 import Tag

from ..services import suppressors
from .base import ScrapedItem
from .magento import MagentoScraper

SITE_BASE = "https://www.capitolarmory.com/"


class CapitolArmoryScraper(MagentoScraper):
    slug = "capitol-armory"
    name = "Capitol Armory"
    base_url = SITE_BASE
    description = "Austin suppressor dealer: SilencerCo and every other maker, over 300 cans."
    requires_browser = False
    default_interval_minutes = 1440
    #: New cans, and used ones titled so ("AAC Ti-RANT 9S - USED").
    sells = "mixed"
    newsletter_url = None
    newsletter_note = "Footer signup is behind a Cloudflare Turnstile check; not linked"
    shipping_note = "Suppressors ship to your dealer for a flat $29.95 by UPS"
    shipping_source = f"{SITE_BASE}support/shipping_returns_policy.html"

    card_selector = ".product-item-info"

    sources = ({"category": "Suppressors", "url": f"{SITE_BASE}suppressor.html"},)

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is None or suppressors.names_a_part(item.title):
            return None
        return item
