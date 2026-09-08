"""Ancestry Guns (ancestryguns.com).

WooCommerce. Their theme puts the product name in an ``h3`` and a "Share on:"
widget in the ``h2`` above it, which is the only thing that needed saying:
without the override every listing came back titled "Share on:".

**Three sections, and they do not overlap at all.** Curio and Relic was the
only one read for a long time, on the reasoning that C&R eligibility is what
this application is about. It is 12 listings -- and their ``/handguns/`` and
``/longguns/`` are 12 more each, with **not one product in common** with it or
with each other. What was being missed: a cased Gustave Young-engraved Colt
M1849, a Civil War surgeon's Colt M1860 Army, a Confederate-issue 3rd Model
Dragoon, a documented Sharps U.S. Navy M1855, an 1866 Winchester musket, a
Bank of England Brown Bess.

They are an antique dealer; "not C&R" here does not mean modern. Their
militaria is not taken, on the standing rule.
"""

from __future__ import annotations

from .woocommerce import WooCommerceScraper

SITE_BASE = "https://www.ancestryguns.com/"


class AncestryGunsScraper(WooCommerceScraper):
    slug = "ancestry-guns"
    name = "Ancestry Guns"
    base_url = SITE_BASE
    description = (
        "Missouri collector dealer. Their C&R, handgun and long-gun sections are "
        "read; their militaria is not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: Twelve listings each and disjoint, so all three are worth the request.
    #: The type-named ones come after C&R only because C&R is the more specific
    #: claim; nothing appears in two of them for the order to decide.
    sources = (
        {"category": "Curio & Relic", "url": f"{SITE_BASE}product-category/curio-relic/"},
        {"category": "Handguns", "url": f"{SITE_BASE}product-category/handguns/"},
        {"category": "Long Guns", "url": f"{SITE_BASE}product-category/longguns/"},
    )

    #: The h2 above the name is a "Share on:" widget, so the h3 goes first.
    title_selectors = ("h3.upper", "h3", *WooCommerceScraper.title_selectors)
