"""Merz Antique Firearms (merzantiques.com).

A large antique and collector arms dealer -- Winchesters above all, then Colts,
Remingtons, Marlins and a long "other rare guns" shelf of military and
sporting pieces. Read: Winchester, Colt, Remington, Marlin and Other Various,
Rare & Collectable Guns; not read: flasks, tools, edged weapons and Native
American artifacts.

**Read from the category pages, not the Store API.** The API answers, but at
about 2.7 seconds a product (measured 2026-10-06: 54 seconds for twenty), so a
scan of the thousand products would run longer than most of this application's
scan intervals. The ordinary WooCommerce pages answer in under two seconds.

**Each title carries the shop's filing**: a stock number in front and a
class letter behind -- "C037 COLT 1849 POCKET MODEL WELLS FARGO MODEL [A]",
where A is antique and M modern. Both are taken off the title: neither is part
of what the gun is, and a stock number in front of every title would sort and
search the catalog by it. A "*Sale Pending*" in front of that is read as no
longer for sale.
"""

from __future__ import annotations

import re

from bs4 import Tag

from .base import ScrapeContext, ScrapedItem
from .woocommerce import WooCommerceScraper

SITE_BASE = "https://www.merzantiques.com/"

#: "*Sale Pending*" ahead of everything, then the stock number, which is
#: always the first word -- C020, JM1, MERZ105, MHG831A, 6-134, 12-34-LM -- so a
#: designation like M1903 is never mistaken for one: on this shop it can only
#: come after the code.
_FILING_PREFIX = re.compile(
    r"^\s*(?P<pending>\*\s*Sale\s+Pending\s*\*\s*)?[A-Z]{0,5}\d[A-Z0-9-]*\s+", re.I
)
_CLASS_SUFFIX = re.compile(r"\s*\[[A-Z]{1,3}\]\s*$")


def without_filing(title: str) -> tuple[str, bool]:
    """The title without the shop's filing, and whether it said sale pending."""
    match = _FILING_PREFIX.match(title)
    pending = bool(match and match.group("pending"))
    rest = title[match.end() :] if match else title
    return (_CLASS_SUFFIX.sub("", rest).strip() or title), pending


class MerzAntiquesScraper(WooCommerceScraper):
    slug = "merz-antiques"
    name = "Merz Antique Firearms"
    base_url = SITE_BASE
    description = (
        "Antique and collector arms: Winchesters, Colts, Remingtons, Marlins and military pieces."
    )
    requires_browser = False
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-06"
    shipping_note = (
        "UPS by value: handguns $70 to $2,000 value, long guns $100-$150 to $2,000, "
        "$175 over; air rates higher"
    )
    shipping_source = "https://www.merzantiques.com/terms-of-sale/"

    sources = (
        {"category": "Winchester", "url": f"{SITE_BASE}product-category/winchester/"},
        {"category": "Colt", "url": f"{SITE_BASE}product-category/colt/"},
        {"category": "Remington", "url": f"{SITE_BASE}product-category/remington/"},
        {"category": "Marlin", "url": f"{SITE_BASE}product-category/marlin/"},
        {
            "category": "Other Various, Rare & Collectable Guns",
            "url": f"{SITE_BASE}product-category/otherrareguns/",
        },
    )

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is not None:
            item.title, pending = without_filing(item.title)
            item.is_sold = item.is_sold or pending
        return item

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        # The product page's own heading carries the same filing.
        item = super().with_detail(ctx, item)
        item.title, pending = without_filing(item.title)
        item.is_sold = item.is_sold or pending
        return item
