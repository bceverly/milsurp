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
* ``Crawl-delay: 10`` — which turned out to be optimistic twice over. A first
  scan kept to it exactly and was refused with a 429 after sixteen minutes, so
  this scraper asked for twenty; twenty was refused too once it grew to nine
  sections, so it now asks for thirty. A pass is a few hundred requests, almost
  no bandwidth, and a couple of hours of wall clock; the detail pages are
  fetched once per listing ever, so it is the *first* scan that is long and
  later ones are short.

Their robots.txt also disallows about a dozen individual pages deep inside
categories we do not read. If one ever appears in a section we do, the walk
stops there with a warning rather than failing the scan.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime

from .base import ScrapeContext, ScrapedItem
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
    #: seconds and refuse at ten *and* at twenty, so this asks for thirty, and a
    #: first pass over 691 listings is hours of somebody else's bandwidth. Their
    #: stock is antique and collector guns that sit for months; nothing about it
    #: turns over in a day.
    #:
    #: Later passes are much shorter — a product page is fetched once per
    #: listing ever — but the catalog pages alone are still ~70 requests at
    #: thirty seconds each, so the cadence is set for the work, not the diff.
    default_interval_minutes = 20_160

    #: Thirty seconds, not the ten their robots.txt asks for. The first scan
    #: kept to ten exactly and was refused with a 429 after sixteen minutes and
    #: ninety listings: their limiter counts over a window that ten seconds a
    #: request eventually fills. Obeying the stated delay and being refused
    #: anyway means the stated delay is not the real one, and the honest
    #: response is to go slower rather than to keep walking into it.
    #:
    #: Twenty was still not enough once this scraper grew from two sections to
    #: nine: a run on 8 Sep was refused again and backed off to forty, so the
    #: pace that works is somewhere above twenty and the back-off was finding it
    #: one 429 at a time. Starting at thirty pays the same wall clock without
    #: the refusal -- the run is long either way, and a scan that provokes a
    #: 429 and recovers is a scan that annoyed somebody's server first.
    #:
    #: A 429 still slows the scan further on its own; this is where it starts.
    #:
    #: **A browser would not help**, which is worth writing down because it is
    #: the obvious next idea: this is rate limiting rather than bot detection,
    #: they answer plain requests perfectly well, and headless Chrome makes
    #: *more* requests per page -- stylesheets, scripts, fonts, images -- so it
    #: would reach the limit sooner and cost Chrome's overhead to do it.
    min_request_delay = 30.0

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

    #: One file listing all 227 of their product categories with a ``lastmod``.
    #:
    #: Their robots.txt declares a sitemap index, and almost all of it is no
    #: use here: 208 ``product-sitemap*.xml`` files carrying about 208,000
    #: product URLs -- their whole catalog, ammunition and scopes and swords
    #: included -- with nothing to say which category any of them is in.
    #: Reading 208 files to save 70 category pages, and then being unable to
    #: tell the 691 listings that matter from the rest without opening every
    #: one, is worse than walking the categories.
    #:
    #: The category sitemap is the useful part, and it is one request.
    CATEGORY_SITEMAP = f"{SITE_BASE}product_cat-sitemap.xml"

    _LASTMOD = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]*)</lastmod>")

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        """Walk the sections, skipping any the shop says have not changed.

        **Measured before it was built, and the saving is modest**: on the
        fortnightly cadence this site runs at, two of the nine sections are
        typically untouched -- Foreign Military Antique Handguns and Mausers,
        the latter unedited since June -- which is about five of some seventy
        catalog pages. At thirty seconds a request that is a couple of minutes
        off a three-hour pass. It costs one request to find out, so it is worth
        having, and it is not the answer to a slow scan.

        Two safeties, and the second one was learned the hard way.

        A skipped section is declared unread, so the reconcile does not treat
        its listings as withdrawn -- without that this would de-list every
        Mauser on the first run.

        **And a section is only skipped if we have actually read it before.**
        "Unchanged" is not "already have it", and conflating the two is a trap
        that closes permanently: a section nobody opens never changes either,
        so it is skipped again on every future run. The scan on 9 Sep skipped
        U.S. Military Antique Long Guns as unchanged -- correctly, it had not
        been edited -- when it was 132 listings this scraper had never read,
        because it was one of the seven sections added after the last
        successful scan. Five more of the new sections were still ahead of that
        run and would have gone the same way.
        """
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._detail_failures = 0
        self._gave_up_on_details = False

        changed_since = self._changed_since(ctx)
        seen: set[str] = set()
        for source in self.sources:
            unchanged = changed_since is not None and source["url"] in changed_since
            if unchanged and not ctx.holds_category(source.get("category")):
                # Unchanged, and never read. Skipping here would be permanent:
                # a section nobody opens never changes either, so it would be
                # skipped again on every future run. Read it once, and the
                # ordinary skip applies from the next scan onwards.
                ctx.log(
                    f"{source['category']}: the shop says unchanged, but nothing is "
                    f"stored from it yet; reading it."
                )
                unchanged = False
            if unchanged:
                ctx.log(f"{source['category']}: unchanged since the last scan; skipping it.")
                ctx.not_read(source.get("category"))
                continue
            yield from self._walk(ctx, source, seen)

    def _changed_since(self, ctx: ScrapeContext) -> set[str] | None:
        """The sources whose category has *not* changed since we last succeeded.

        None when the question cannot be answered -- no previous scan, or the
        sitemap did not load -- and then every section is walked, which is the
        behavior this replaced and the right thing to fall back to.
        """
        since = ctx.last_success_at
        if since is None:
            return None
        try:
            body = ctx.get_text(self.CATEGORY_SITEMAP)
        except Exception as exc:
            ctx.log(f"Could not read the category sitemap ({exc}); walking every section.")
            return None

        stamps: dict[str, datetime] = {}
        for url, stamp in self._LASTMOD.findall(body):
            try:
                stamps[url.rstrip("/") + "/"] = datetime.fromisoformat(stamp)
            except ValueError:
                continue

        unchanged = set()
        for source in self.sources:
            stamp = stamps.get(source["url"].rstrip("/") + "/")
            if stamp is not None and stamp <= since:
                unchanged.add(source["url"])
        return unchanged

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
