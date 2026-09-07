"""Collectors Firearms (collectorsfirearms.com).

A WooCommerce shop, so nearly all of the work is in
:class:`~app.scrapers.woocommerce.WooCommerceScraper`. What is specific to this
vendor is which sections to read and how their theme differs from stock.

**Only the military rifle sections are taken.** They are a general dealer with
around 207,000 products — modern handguns, shotguns, ammunition, scopes, swords
— and the surplus this application exists to watch is in two of their
categories. Their military *handguns* are not separately categorized; they sit
in "modern handguns" and "antique handguns" among everything else, so there is
no way to ask for them without taking the rest, and they are left until there
is.

**Their robots.txt shapes the design.** Two rules matter:

* ``Disallow: /*?*`` rules out the WooCommerce Store API, which would otherwise
  be the obvious way to read this catalog: its category filter and its
  pagination are both query strings. So the category pages are read as HTML.
* ``Crawl-delay: 10`` — which turned out to be optimistic. A first scan kept to
  it exactly and was refused with a 429 after sixteen minutes, so this scraper
  asks for twenty. A pass is a few hundred requests, almost no bandwidth, and
  something over an hour of wall clock; the detail pages are fetched once per
  listing ever, so it is the *first* scan that is long and later ones are short.

Their robots.txt also disallows about a dozen individual pages deep inside
categories we do not read. If one ever appears in a section we do, the walk
stops there with a warning rather than failing the scan.
"""

from __future__ import annotations

from .woocommerce import WooCommerceScraper

SITE_BASE = "https://collectorsfirearms.com/"


class CollectorsFirearmsScraper(WooCommerceScraper):
    slug = "collectors-firearms"
    name = "Collectors Firearms"
    base_url = SITE_BASE
    description = (
        "Houston collector dealer trading since 1975. Their foreign and U.S. "
        "military rifle sections are read; the rest of their general catalog is not."
    )
    requires_browser = False
    #: Daily. A scan is long but light — a few hundred requests spaced ten
    #: seconds apart, because that is what their robots.txt asks for.
    default_interval_minutes = 1440

    #: Twenty seconds, not the ten their robots.txt asks for. The first scan
    #: kept to ten exactly and was refused with a 429 after sixteen minutes and
    #: ninety listings: their limiter counts over a window that ten seconds a
    #: request eventually fills. Obeying the stated delay and being refused
    #: anyway means the stated delay is not the real one, and the honest
    #: response is to go slower rather than to keep walking into it.
    #:
    #: A 429 still slows the scan further on its own; this is where it starts.
    min_request_delay = 20.0

    sources = (
        {
            "category": "Foreign Military Rifles",
            "url": f"{SITE_BASE}product-category/rifles/foreign-military-rifles/",
        },
        {
            "category": "U.S. Military Rifles",
            "url": f"{SITE_BASE}product-category/rifles/u-s-military-rifles/",
        },
    )

    # Their theme renames two things and keeps the rest of the WooCommerce
    # markup, so these go in front of the stock selectors rather than replacing
    # them: if the theme changes back, the defaults still answer.
    detail_description_selectors = (
        "div.single-product-description",
        *WooCommerceScraper.detail_description_selectors,
    )
    #: "Item Number: L2026-10918" — the label is inside the element, and the
    #: base class trims it.
    detail_sku_selectors = ("div.product-sku", *WooCommerceScraper.detail_sku_selectors)
