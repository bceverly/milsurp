"""SARCO, Inc. (sarcoinc.com).

An Easton, Pennsylvania dealer that has been selling military surplus parts and
firearms since 1983, and one of the deepest catalogs on the list -- 11,699
products, of which 509 are guns rather than parts, tools, books or clothing.

The roadmap had this filed under **needs a browser**, and the evidence for that
was real: the category pages arrive as 236KB of HTML containing no product
cards, no prices and no product links, because a Searchanise widget draws the
grid after load. The conclusion drawn from it was wrong for the same reason it
was wrong about J&G Sales. What the HTML looks like is not what a site *is*.
The widget reads a public JSON endpoint, and so does this -- the whole catalog
in three requests, no browser anywhere.

**The product pages, unlike the category pages, are ordinary server-rendered
Stencil.** That matters because the API's description stops at 200 characters:
508 of the 509 come back cut off mid-sentence. So the description is taken from
``#tab-description`` on the shop's own page, once per listing, for listings the
scan has not described before.

**The sections are ordered, and the order is the point.** A listing is taken by
the first section that offers it, and that section's name becomes the
``category`` the classifier trusts over its own reading of the title. Measured
across SARCO's 283 pistols: arriving under the parent "Shop All Firearms", 200
were recognized as handguns, 77 as nothing at all and 6 as rifles. Arriving
under "Pistols", 281 of 283 are handguns. So the specific sections go first and
the catch-all goes last.

"Shop All Firearms" is still needed, and only as the catch-all, because the one
section that cannot be asked for by name is the one this application most wants:
SARCO's rifles live in a category called **"Rifles | Military Surplus Guns"**,
and ``restrictBy[categories]`` splits on the pipe. Asking for the full name
returns zero. So does asking for either half -- it was tried. The 75 rifles are
reachable only through the parent, where the label says nothing about type; they
are left to the classifier and the armory, which is what those are for.

**Frames and Actions & Receivers are skipped.** SARCO files them under
firearms, and legally that is right -- a stripped receiver is the serialized
part. For this application they are components, and the standing rule is that
the only non-firearm category worth ingesting is a parts *kit*. That is 83
listings that would otherwise arrive to be filed as accessories. They have to be
suppressed rather than filtered out afterwards, because fifteen of the fifty
frames are also in "Pistols" and would be claimed by it first.

"Exciting New Firearms" comes last: not quite a subset, since three of its 73
were not yet in the parent when this was measured, and a new arrival is exactly
what is worth catching early.

The result is 429 listings from 512 offered, of which 379 classify as a firearm
without further help.
"""

from __future__ import annotations

from .searchanise import SearchaniseScraper

SITE_BASE = "https://www.sarcoinc.com/"


class SarcoScraper(SearchaniseScraper):
    slug = "sarco"
    name = "SARCO, Inc."
    base_url = SITE_BASE
    description = "Military surplus firearms, parts and collectibles from an Easton, Pennsylvania dealer since 1983."
    default_interval_minutes = 1440

    #: From the widget the storefront loads on every page:
    #: ``searchanise-ef84.kxcdn.com/widgets/bigcommerce/init.js?api_key=…``.
    api_key = "7I8v4I9z4m"

    #: Specific first, catch-all last -- see the module docstring.
    sources = (
        {"category": "Pistols"},
        {"category": "Shotgun", "label": "Shotguns"},
        {"category": "Shop All Firearms"},
        {"category": "Exciting New Firearms"},
    )

    #: Components, not firearms. Read first and skipped everywhere.
    exclude_categories = ("Frames", "Actions & Receivers")

    #: The tab body, not the ``.productView-description`` wrapper around it --
    #: that one begins with the literal word "Description" from the tab label.
    detail_description_selectors = ("#tab-description", ".productView-description")

    def product_url(self, url: str) -> str:
        """Canonical host. Every link in the feed is bare and 301s to ``www``."""
        return url.replace("https://sarcoinc.com/", SITE_BASE, 1)
