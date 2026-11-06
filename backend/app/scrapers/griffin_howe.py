"""Griffin & Howe (griffinhowe.com) -- the gun room's shotguns.

The Andover, New Jersey gunmaker and dealer, added on 2026-11-06 when the
application widened to every used shotgun: consigned and acquired best guns
-- Piotti, David McKay Brown, Boss, Purdey, A.H. Fox -- beside new Berettas,
Perazzis and their own guns. About 330 shotguns that day, 60 to a page.

WooCommerce, but its Store API answers 500, so the category pages are read as
HTML through :class:`~app.scrapers.woocommerce.WooCommerceScraper`. Their
cards are Elementor loop items rather than ``li.product``, and still carry
WooCommerce's ``product type-product post-N`` classes, which is all the base
class needs. robots.txt disallows ``/shop/category-`` (a dash, not the
``/shop/category/`` path read here), feeds, the cart and the admin.

**New or used is in the card's classes.** A pre-owned gun is filed in
``product_cat-used-guns`` and ``product_cat-used-shotguns`` as well as
``product_cat-shotguns``; a new one in ``product_cat-shotguns`` alone (33 and
25 on the first page that day). The product page says the same in its spec
table ("Condition: Preowned"), which is what the description is taken from:
make, model, gauge, barrels, chokes, chambers, stock dimensions.

Not read: the gun room's rifles and handguns, optics, and the shop's apparel
and accessories.
"""

from __future__ import annotations

from bs4 import Tag

from .base import ScrapedItem
from .woocommerce import WooCommerceScraper

SITE_BASE = "https://griffinhowe.com/"


def is_used_card(classes: str) -> bool:
    """Whether a card's classes file the gun as pre-owned."""
    return any(name.startswith("product_cat-used") for name in classes.split())


class GriffinHoweScraper(WooCommerceScraper):
    slug = "griffin-howe"
    name = "Griffin & Howe"
    base_url = SITE_BASE
    description = (
        "New Jersey gunmaker's gun room: pre-owned best guns and new over/unders, "
        "side-by-sides and their own shotguns."
    )
    requires_browser = False
    default_interval_minutes = 1440
    sells = "mixed"
    newsletter_url = SITE_BASE
    newsletter_note = '"Stay in the Loop" email signup at the foot of every page'
    shipping_note = "No firearm shipping rate published; checked 2026-11-06"
    shipping_source = f"{SITE_BASE}terms-conditions/"

    sources = ({"category": "Shotguns", "url": f"{SITE_BASE}shop/category/gun-room/shotguns/"},)

    #: The spec table ("Make | Piotti | Model | Round Body SLE | Gauge-Caliber
    #: | 20 Gauge ..."), which is the only description the page has.
    detail_description_selectors = (".gh-specs", *WooCommerceScraper.detail_description_selectors)

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is not None:
            item.is_new = not is_used_card(" ".join(card.get("class") or []))
        return item
