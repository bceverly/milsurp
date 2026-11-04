"""Click-Click-Boom (click-click-boom.com) -- the used guns.

A Waverly, Minnesota gun shop, added on 2026-11-04 while looking for shops
that carry used Raven MP-25s and the other small .25 ACP pistols: a dealer
that buys guns over the counter ("Sell Us Your Guns") lists a steady trickle
of exactly those. WooCommerce with the Store API answering.

Read: the Firearms category (512 guns on 2026-11-04, every one in stock --
the shop drops a gun from the catalog when it sells), keeping only the used
ones, about 190. The shop has no used category, so condition comes from the
product's own "Condtion" attribute (the shop's spelling), which 486 of the 512
carry: 184 Used, 301 New, 1 both. Where it is missing the title says it, and
"Used ..." is how this shop names every used gun it lists. A gun that says
both is a new-in-box collectible ("Original Box, Unfired") and stays out, as
do the six "Special Order" listings, which are a distributor's stock rather
than a gun on the shelf.

**robots.txt disallows ``&orderby=``,** which the shared walk sends, so this
shop's requests leave it out. The Store API's own default is newest first,
which is what the walk asked for anyway.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ScrapedItem
from .woo_store_api import PAGE_SIZE, WooStoreApiScraper, html_to_text

SITE_BASE = "https://click-click-boom.com/"

_USED_TITLE = re.compile(r"^\W*used\b", re.I)


def _terms(product: dict[str, Any], heading: re.Pattern[str]) -> set[str]:
    found: set[str] = set()
    for attribute in product.get("attributes") or []:
        if isinstance(attribute, dict) and heading.match(str(attribute.get("name") or "")):
            for term in attribute.get("terms") or []:
                name = html_to_text(term.get("name")) if isinstance(term, dict) else None
                if name:
                    found.add(name.strip().lower())
    return found


#: "Condtion" today; matched by its start so the shop correcting the spelling
#: does not quietly empty the scan.
_CONDITION = re.compile(r"^\s*cond", re.I)


def is_used(product: dict[str, Any]) -> bool:
    """Whether the shop lists this gun as used.

    Its condition attribute when it has one -- "Used" and not also "New" --
    and otherwise its title.
    """
    condition = _terms(product, _CONDITION)
    if condition:
        return "used" in condition and "new" not in condition
    title = html_to_text(product.get("name")) or ""
    return bool(_USED_TITLE.match(title))


def is_special_order(product: dict[str, Any]) -> bool:
    return any(
        isinstance(tag, dict) and str(tag.get("name") or "").strip().lower() == "special order"
        for tag in product.get("tags") or []
    )


def section(product: dict[str, Any]) -> str:
    """Handgun or long gun, from the shop's own subcategories."""
    names = {
        (html_to_text(category.get("name")) or "").lower()
        for category in product.get("categories") or []
        if isinstance(category, dict)
    }
    if any(name.startswith("handguns") for name in names):
        return "Used Handguns"
    if "long guns" in names:
        return "Used Long Guns"
    return "Used Firearms"


class ClickClickBoomScraper(WooStoreApiScraper):
    slug = "click-click-boom"
    name = "Click-Click-Boom"
    base_url = SITE_BASE
    description = (
        "Minnesota gun shop's used handguns, rifles and shotguns, bought over the counter."
    )
    default_interval_minutes = 1440
    sells = "used"
    newsletter_url = None
    newsletter_note = "No signup on the site, only a text line (763-310-1040); checked 2026-11-04"
    shipping_note = (
        "No firearm shipping rate published; ships to a licensed dealer; checked 2026-11-04"
    )
    shipping_source = f"{SITE_BASE}shipping-restrictions/"

    #: Firearms, from /wp-json/wc/store/v1/products/categories on 2026-11-04.
    #: Its Handguns (21963) and Long Guns (22040) children are inside it, and
    #: a listing is filed by them (:func:`section`).
    sources = ({"category": "Used Firearms", "id": 22039},)

    def endpoint(self, page: int, category: Any) -> str:
        # No orderby: see the module docstring.
        query = f"per_page={PAGE_SIZE}&page={page}"
        if category is not None:
            query += f"&category={category}"
        return f"{self.base_url.rstrip('/')}/wp-json/wc/store/v1/products?{query}"

    def item_from_product(
        self,
        product: dict[str, Any],
        label: str,  # noqa: ARG002 -- filed by its subcategory instead
    ) -> ScrapedItem | None:
        if not is_used(product) or is_special_order(product):
            return None
        item = super().item_from_product(product, section(product))
        if item is not None:
            item.is_new = False
        return item
