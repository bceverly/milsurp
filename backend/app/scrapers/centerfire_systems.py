"""Centerfire Systems (centerfiresystems.com).

A general firearms retailer that happens to carry surplus, which makes the
collection list the entire job here. Their top-level ``/products.json`` opens
with Browning hunting ammunition, and the biggest collections in the shop are
455 AR-15 rifles and 288 AR-15 pistols — none of which belongs in a military
surplus catalog.

**Their parts-kit collection is the exception to that caution and was
measured before it was added.** 417 listings across two pages, and 239 of the
first 250 read as a parts kit from the *title alone* -- FAL, AK, UZI, PPS43,
MG42, Tavor. A section that homogeneous is worth having whole: the catalog held
25 parts kits before it.

So this reads four collections and nothing else. That is the same call already
made about Arms Unlimited, which was written, run, and backed out when all 97
listings turned out to be police trade-in gear and modern Colt M4s.
"""

from __future__ import annotations

from .shopify import ShopifyScraper

SITE_BASE = "https://centerfiresystems.com/"


class CenterfireSystemsScraper(ShopifyScraper):
    slug = "centerfire-systems"
    name = "Centerfire Systems"
    base_url = SITE_BASE
    description = (
        "General retailer; only their C&R, classic military and certified used "
        "sections are read. Their modern AR and AK stock is not."
    )
    default_interval_minutes = 1440

    sources = (
        {"category": "C&R Eligible", "url": f"{SITE_BASE}collections/c-r-eligible"},
        {
            "category": "Classic Military",
            "url": f"{SITE_BASE}collections/firearms-classic-firearms-military",
        },
        {"category": "Certified Used", "url": f"{SITE_BASE}collections/firearms-certified-used"},
        {
            # The one non-firearm category the catalog wants: a parts kit is a
            # whole gun minus its receiver, priced and watched like one.
            "category": "Parts Kits",
            "url": f"{SITE_BASE}collections/parts-kits-surplus-parts-kits",
        },
    )
