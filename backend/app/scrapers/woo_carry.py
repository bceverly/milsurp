"""WooCommerce gun shops whose handguns are a distributor's catalog.

G4G Guns and Frisco Guns, asked for on 2026-10-20 for concealed carry pistols
and revolvers. Both sell new guns drop-shipped from distributors -- their SKUs
say whose ("LIP|" Lipsey's, "RSR|", "KRL|" Kroll, "CSSI|") -- about 4,600
handguns in stock at each that day, and neither has a used shelf. Read through
the Store API (:mod:`app.scrapers.woo_store_api`): in-stock handguns only, in
the carry calibers (:func:`carry.is_carry_caliber`), new unless the title
says it is a demonstrator or used.

**The caliber** is the product's "Caliber/Gauge" attribute where the shop
filled one in -- G4G mostly does, Frisco mostly does not -- and otherwise the
classifier's reading of the title, as for every other listing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..services import carry, classify, newness
from .base import ScrapedItem
from .woo_store_api import WooStoreApiScraper


def stated_caliber(product: dict[str, Any]) -> str | None:
    """The shop's "Caliber/Gauge" attribute, where it has one."""
    for attribute in product.get("attributes") or []:
        if str(attribute.get("name") or "").lower().startswith("caliber"):
            for term in attribute.get("terms") or []:
                if term.get("name"):
                    return str(term["name"])
    return None


class WooCarryScraper(WooStoreApiScraper):
    """A distributor-catalog shop's in-stock handguns in the carry calibers."""

    sells = "new"
    #: The shop\'s own caliber and maker, from its records.
    states_facts = True
    #: A distributor catalog runs to thousands: 35 pages of a hundred at each
    #: shop's semi-automatics on 2026-10-20.
    max_pages_per_source = 80
    wanted_caliber: Callable[[str], bool] = staticmethod(carry.is_carry_caliber)

    def endpoint(self, page: int, category: Any) -> str:
        return super().endpoint(page, category) + "&stock_status=instock"

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        item = super().item_from_product(product, label)
        if item is None:
            return None
        caliber = stated_caliber(product) or classify.extract_caliber(item.title)
        if not caliber or not self.wanted_caliber(caliber):
            return None
        item.caliber = caliber
        # New, unless the title says otherwise: Frisco sells its demonstrators
        # ("DEMO Canik METE MC9") beside the distributor's guns.
        item.is_new = newness.decide(None, newness.MIXED, item.title) is not False
        return item
