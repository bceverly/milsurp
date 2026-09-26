"""Classic Firearms (classicfirearms.com).

The most-visited site on the roadmap, and a genuine surplus catalog: M96
Swedish Mausers, MAS 49/56, Finnish M39s, K-98s, Schmidt-Rubins, Mosins.

Their theme shares almost no CSS class with stock Magento — the grid is
``.products-grid .item`` and the cards carry no ``product-item-info`` id — so
the selectors below replace the defaults rather than extending them. What their
product pages do carry is schema.org ``Product`` JSON-LD with the name, SKU,
price, availability, description and original-resolution images, which is where
the base class gets everything that matters.

**They disallow their own pagination.** ``Disallow: /*?p=`` in robots.txt, with
an ``Allow:`` only for ``/news``, so a category stops at page one. Two ways
round it were measured before settling for that:

- ``?product_list_limit=96`` *is* permitted by robots and is *ignored* by the
  server, which returns 24 cards either way.
- The sitemap index declared in their robots.txt lists product URLs, and
  product pages are allowed. That is the sanctioned route to the rest of the
  catalog and is worth doing, at one request per product; it is not this
  scraper yet.

There is a third way past the page-one limit, better than the sitemap, and it
is the one taken: their caliber facets are **paths**, not query strings —
``/firearms/rifles/military-surplus/30_06/`` is 19 rifles and is allowed. See
``follow_facets`` below.

**Their police trade-ins, added September 2026.** Classic shelve department
trade-ins in two sections of their own, found in the site's navigation rather
than guessed: ``/firearms/handguns/leo-police-trade-ins/`` (63 listings: Glock
17/19/21/22/45s, Sig P226 and P229s, M&Ps, a Beretta Puma) and
``/firearms/rifles/leo-police-trade-ins/`` (15). There is no shotgun section,
and no used or parts-kit one.

Unlike every other police section read here, the rifle one is **not all
trade-ins**. Six of its fifteen are new guns sold under a law-enforcement name:
Henry's Golden Boy "Law Enforcement Tribute", Hi-Point's "LEOP" Leopard,
Savage's 10 GRS LE, FN's PS90 "Law Enforcement Edition", and two Live Free
Armory "LEO Carbines". The trade-ins all say so in the title ("Used LE Trade
In", "Law Enforcement Turn-In", "Used ... Surplus Good Condition") and the new
guns never do. So in these two sections a listing is read only when its title
says it is used, a trade-in, a turn-in or surplus. That is a rule about what to
*read* from this shop, not about what police surplus is: everything that
passes it is flagged by its section, exactly as at every other vendor.
"""

from __future__ import annotations

import re

from bs4 import Tag

from .base import ScrapedItem
from .magento import MagentoScraper

SITE_BASE = "https://www.classicfirearms.com/"

#: Classic's two police sections, by the category each is read under. The names
#: are what the classifier reads the police-surplus flag from.
POLICE_SECTIONS = frozenset({"Police Trade-In Handguns", "Police Trade-In Rifles"})

#: What a real trade-in in those sections says in its title. See the module
#: docstring: the new "LE edition" guns shelved beside them never do.
_SECONDHAND = re.compile(r"\b(?:trade[\s-]?ins?|turn[\s-]?ins?|used|surplus)\b", re.I)


class ClassicFirearmsScraper(MagentoScraper):
    slug = "classic-firearms"
    name = "Classic Firearms"
    base_url = SITE_BASE
    newsletter_url = "https://www.classicfirearms.com/"
    newsletter_note = (
        "Email footer form on the home page (their /sms-signup/ is text messages, not email)"
    )
    description = (
        "Large surplus retailer: military-surplus rifles and handguns, C&R, and "
        "police trade-ins. Their robots.txt disallows category pagination, so "
        "each section is read one caliber facet at a time instead."
    )
    default_interval_minutes = 1440

    #: Their pagination is disallowed, so each section is read one facet at a
    #: time instead. See MagentoScraper.follow_facets — on their rifle section
    #: that is 19 caliber facets covering all 122 listings, where the category
    #: pages could only ever show 24.
    follow_facets = True

    card_selector = ".products-grid .item"
    # Their cards name the product in the photograph's alt text and in the
    # link, and the link text is whitespace-only in the grid, so the base
    # class's alt-text fallback does the work.
    title_selectors = ("a.product-name", ".product-name a", ".product-item-link")

    #: Their three surplus sections, taken from the site's own navigation.
    #:
    #: Guessing these cost two 404s: "/firearms/curio-relic/" and
    #: "/firearms/handguns/surplus-handguns/" are the obvious names and neither
    #: exists. Read the nav.
    sources = (
        {
            "category": "Military Surplus Rifles",
            "url": f"{SITE_BASE}firearms/rifles/military-surplus/",
        },
        {
            "category": "Military Surplus Handguns",
            "url": f"{SITE_BASE}firearms/handguns/military-surplus/",
        },
        {"category": "C&R Eligible", "url": f"{SITE_BASE}firearms/c-and-r-eligible/"},
        {
            "category": "Police Trade-In Handguns",
            "url": f"{SITE_BASE}firearms/handguns/leo-police-trade-ins/",
        },
        {
            "category": "Police Trade-In Rifles",
            "url": f"{SITE_BASE}firearms/rifles/leo-police-trade-ins/",
        },
    )

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is not None and category in POLICE_SECTIONS and not _SECONDHAND.search(item.title):
            return None
        return item
