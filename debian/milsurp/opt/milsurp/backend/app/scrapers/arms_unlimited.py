"""Arms Unlimited (armsunlimited.com).

**Written, backed out, and restored on a section nobody had opened.** This shop
was refused once, and the refusal was right about what it examined: their
``/surplus/`` is police trade-in *gear* -- Tasers, Taser batteries, a Magpul
rear sight, a stainless water bottle -- and their ``/firearms/`` is current
production, Beretta A300s and 92FSs and B&T suppressors and a Colt M4A1 SOCOM.
Both are the "not a surplus dealer" call this catalog has made five times.

What was never checked is whether the shop had a section of its own for the
older stock, because it was condemned whole. It does:
``/used-collectible-firearms/``, and it is the only section here worth reading.

A stock BigCommerce shop, so a subclass is the sections and nothing else.

**Their department trade programme is a page, not a catalog.**
``/department-trade-program/`` describes how a department trades its duty
weapons in; it holds no products at all. The guns that come out of it are
shelved under used and collectible with everything else.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://armsunlimited.com/"


class ArmsUnlimitedScraper(BigCommerceScraper):
    slug = "arms-unlimited"
    name = "Arms Unlimited"
    base_url = SITE_BASE
    description = (
        "Police and military supplier. Their used and collectible firearms are "
        "read; their surplus gear and current-production sections are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = (
        {
            "category": "Used & Collectible Firearms",
            "url": f"{SITE_BASE}used-collectible-firearms/",
        },
    )
