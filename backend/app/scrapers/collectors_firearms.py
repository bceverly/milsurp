"""Collectors Firearms (collectorsfirearms.com).

A WooCommerce shop, so nearly all of the work is in
:class:`~app.scrapers.woocommerce.WooCommerceScraper`. What is specific to this
vendor is which sections to read and how their theme differs from stock.

**Only the military and antique sections are taken.** They are a general
dealer with around 207,000 products — modern handguns, shotguns, ammunition,
scopes, swords — and this reads the seven categories that are surplus and
collector firearms.

**It read two of the seven for a long time, and this file said the other five
did not exist.** "Their military handguns are not separately categorized", it
claimed, and that was simply wrong: ``/modern-handguns/military-handguns/`` is
91 listings, ``/lugers/`` is 48 and ``/mausers/`` is 20. The mistake was
reading their *nav* — where "Antique Handguns" and "Modern Handguns" are
top-level — and stopping there. On this shop a parent category renders a page
of **sub-category tiles**, not products; the products are one level down, and
the two sections already read were leaves reached from `/rifles/`. Every parent
here has to be opened before it can be judged.

Measured: the two sections read were 218 listings and the five added are 473,
so this was reading **32%** of what it could. What was missed is not marginal —
US Model 1861 and 1842 muskets, a B.S.A. Snider, a Spandau 1871/84, a
Vetterli-Carcano 1870/87/15, a Type 14 Nambu, an Astra 600/43, Mauser S/42
Lugers, a C96 flatside, a byf 44 P.38.

Their remaining categories are left alone on the standing rule: `/militaria/`
is eighteen sub-categories of gear, `/rifles/` has sporting, tactical and
rimfire leaves beside the two military ones, and `/japanese-swords-.../`
publishes an empty firearms leaf.

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
        "Houston collector dealer trading since 1975. Their military and antique "
        "firearm sections are read; the rest of their general catalog is not."
    )
    requires_browser = False
    #: Every two weeks, which is the longest cadence the site list offers.
    #:
    #: This was daily, and daily was defensible when it read two sections. It
    #: reads nine now, and their crawl delay is the real cost: they ask for ten
    #: seconds and refuse at ten, so this asks for twenty, and a first pass over
    #: 691 listings is a couple of hours of somebody else's bandwidth. Their
    #: stock is antique and collector guns that sit for months; nothing about it
    #: turns over in a day.
    #:
    #: Later passes are much shorter — a product page is fetched once per
    #: listing ever — but the catalog pages alone are still ~70 requests at
    #: twenty seconds each, so the cadence is set for the work, not the diff.
    default_interval_minutes = 20_160

    #: Twenty seconds, not the ten their robots.txt asks for. The first scan
    #: kept to ten exactly and was refused with a 429 after sixteen minutes and
    #: ninety listings: their limiter counts over a window that ten seconds a
    #: request eventually fills. Obeying the stated delay and being refused
    #: anyway means the stated delay is not the real one, and the honest
    #: response is to go slower rather than to keep walking into it.
    #:
    #: A 429 still slows the scan further on its own; this is where it starts.
    min_request_delay = 20.0

    #: Seven leaf categories, with the counts each held when they were added.
    #:
    #: Leaves only. A parent on this shop is a page of sub-category tiles with
    #: no products on it at all, which is the trap the roadmap records against
    #: MCT Defense and which cost this scraper five sections for months.
    #:
    #: The type-named ones come first: a section name outranks the classifier's
    #: reading of a title, and "Lugers" says nothing about type while
    #: "U.S. Martial Antique Handguns" says it plainly.
    sources = (
        {
            "category": "Foreign Military Rifles",  # 167
            "url": f"{SITE_BASE}product-category/rifles/foreign-military-rifles/",
        },
        {
            "category": "U.S. Military Rifles",  # 51
            "url": f"{SITE_BASE}product-category/rifles/u-s-military-rifles/",
        },
        {
            "category": "U.S. Military Antique Long Guns",  # 132
            "url": f"{SITE_BASE}product-category/antique-long-guns/u-s-military-antique-long-guns/",
        },
        {
            "category": "Foreign Military Antique Long Guns",  # 108
            "url": (
                f"{SITE_BASE}product-category/antique-long-guns/"
                "foreign-military-antique-long-guns/"
            ),
        },
        {
            "category": "Military Handguns",  # 91
            "url": f"{SITE_BASE}product-category/modern-handguns/military-handguns/",
        },
        {
            "category": "U.S. Martial Antique Handguns",  # 46
            "url": (f"{SITE_BASE}product-category/antique-handguns/u-s-martial-antique-handguns/"),
        },
        {
            "category": "Foreign Military Antique Handguns",  # 28
            "url": (
                f"{SITE_BASE}product-category/antique-handguns/"
                "foreign-military-antique-handguns/"
            ),
        },
        {
            "category": "Lugers",  # 48
            "url": f"{SITE_BASE}product-category/modern-handguns/lugers/",
        },
        {
            "category": "Mausers",  # 20
            "url": f"{SITE_BASE}product-category/modern-handguns/mausers/",
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
