"""Impact Guns (impactguns.com) -- the used guns.

A Utah dealer, added on 2026-10-28 with the used-gun shops asked for to catch
used carry pistols. A BigCommerce Stencil store behind Cloudflare, with no
challenge to this application; robots.txt allows ``?page=N`` and disallows
only the faceted ``_bc_fsnf`` filters, search and the account pages.

Read: ``/used-guns/``, about 90 cards on 2026-10-28, two thirds handguns --
but only 8 in stock that day, the rest "Out of Stock" or "This item is no
longer available" (kept as sold, as the BigCommerce base reads them). The
section also files guns that are not used: factory "Rebuilt" Glocks, "Demo"
and "Store Demo" guns, "Factory Blemished" new ones and a range "Rental".
Those are left out by name (:func:`is_not_used`), which is the earlier
survey's reason for calling this one only a maybe.
"""

from __future__ import annotations

import re

from bs4 import Tag

from .base import ScrapedItem
from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://www.impactguns.com/"

#: The card's own words for a gun that is not for sale (2026-10-28): the
#: BigCommerce base reads a sold-out badge, and Impact's theme writes these.
_GONE = re.compile(r"out of stock|no longer available", re.I)

_NOT_USED = re.compile(r"\b(?:rebuilt|demo|blem(?:ished)?|rental|refurb(?:ished)?)\b", re.I)


def is_not_used(title: str) -> bool:
    """Whether the used section's title says the gun is something else."""
    return bool(_NOT_USED.search(title or ""))


class ImpactGunsScraper(BigCommerceScraper):
    slug = "impact-guns"
    name = "Impact Guns"
    base_url = SITE_BASE
    description = "Utah dealer's used guns, two thirds of them handguns."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "used"
    newsletter_url = None
    newsletter_note = "No signup form found on the home page; checked 2026-10-28"
    shipping_note = "Free standard shipping on many firearms, to a licensed dealer"
    shipping_source = f"{SITE_BASE}free-shipping/"

    sources = ({"category": "Used Guns", "url": f"{SITE_BASE}used-guns/"},)

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is None or is_not_used(item.title):
            return None
        item.is_new = False
        if _GONE.search(card.get_text(" ", strip=True)):
            item.is_sold = True
        return item
