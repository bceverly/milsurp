"""Recoil Gun Works (recoilgunworks.com).

**The first police-surplus vendor here, and the reason the category exists.**
Departments trade their duty weapons in by the lot and a dealer sells them as a
named section, which is the same question this catalog has always asked about
military surplus: somebody's service weapon, sold on, in quantity, at a price
worth watching. It is not old, and "old" was never the point.

A stock BigCommerce shop, so the work is entirely in which sections to read.

**Three leaves, and the parent is not one of them.** ``/police-trade-in/``
looks like the section to take and is not: it is a mixed shelf, and the twelve
cards on its first page include Federal HST and Speer Gold Dot ammunition and a
Glock magazine at $10.99. The firearms live one level down, under
``/police-trade-in/firearms/``, split three ways -- pistols, rifles, shotguns --
and those are what is read. Opening the parent before judging it is the lesson
Collectors Firearms cost, and it applies here in reverse: there the parent held
no products, here it holds the wrong ones.

**What is deliberately left out.**

* ``/police-trade-in/equipment`` and ``/police-trade-in/magazines`` are gear and
  accessories, on the standing rule that has kept this catalog to firearms.
* ``/surplus/`` is the trap of the four, because the name is exactly right and
  the contents are not. It is police-surplus *training* stock: Scott M98
  respirators, UTM and Simunition marking cartridges, a Sig P226 UTM conversion
  kit, an AR-15 conversion bolt carrier. Sampled and rejected, the same way
  Arms Unlimited's ``/surplus/`` was.

What the sections hold, as measured when this was written: Glock 17/19/21/22/23
in Gen 4 and Gen 5, Sig P226s on German frames, CMMG, Windham, Rock River,
Bushmaster and S&W M&P-15 patrol rifles, Remington 870 Police Magnums and
Mossberg 590A1s.

**Almost all of it is sold.** 229 listings, every one priced, and **222 of them
are OutOfStock in their own structured data** -- seven are actually buyable.
This shop leaves sold stock up, which on the grid is indistinguishable from
stock they have: the price is still there and the card looks the same. So the
browse page's default filter shows seven of these, not 229, and the rest are
under Sold.

That is worth knowing before reading the catalog count as coverage, and it is
not a reason to skip the shop: a police trade-in that sold is a price somebody
paid for a department Glock on a day that has passed, which is the one thing
this application collects that cannot be fetched again.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://www.recoilgunworks.com/"


class RecoilGunWorksScraper(BigCommerceScraper):
    slug = "recoil-gun-works"
    name = "Recoil Gun Works"
    base_url = SITE_BASE
    description = (
        "Police trade-in firearms: department Glocks and Sigs, patrol rifles and "
        "shotguns. Their gear, magazine and training-ammunition sections are not read."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: Leaves only. The category name is the strongest signal available for
    #: what a police trade-in is, so it is carried onto every listing.
    sources = (
        {
            "category": "Police Trade-In Pistols",
            "url": f"{SITE_BASE}police-trade-in/firearms/pd-trade-pistols/",
        },
        {
            "category": "Police Trade-In Rifles",
            "url": f"{SITE_BASE}police-trade-in/firearms/pd-trade-rifles/",
        },
        {
            "category": "Police Trade-In Shotguns",
            "url": f"{SITE_BASE}police-trade-in/firearms/pd-trade-shotguns/",
        },
    )
