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

So each section here yields its first page, and three sections are listed
rather than one, because 24 listings from each of three is a better read of the
catalog than 24 from one.

There is a third way past the page-one limit, better than the sitemap and not
yet taken: their caliber facets are **paths**, not query strings —
``/firearms/rifles/military-surplus/30_06/`` is 19 rifles and is allowed. A
later pass could walk those and reach most of the catalog within the rules.
"""

from __future__ import annotations

from .magento import MagentoScraper

SITE_BASE = "https://www.classicfirearms.com/"


class ClassicFirearmsScraper(MagentoScraper):
    slug = "classic-firearms"
    name = "Classic Firearms"
    base_url = SITE_BASE
    description = (
        "Large surplus retailer. Their robots.txt disallows category "
        "pagination, so each section is read to its first page only."
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
    )
