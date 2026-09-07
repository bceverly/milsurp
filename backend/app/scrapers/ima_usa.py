"""IMA-USA (ima-usa.com).

International Military Antiques: trading since 1981, and the largest catalog in
the Shopify group. Their whole business is original militaria, so almost the
entire shop is in scope — but not quite, which is what the collection list is
for. ``/collections/all`` is 2,898 items and includes gun parts, holsters and
cases; the collections below are the firearms.

Everything comes out of ``products.json`` in one request per collection, so
this is the cheapest scan in the application: no browser, no HTML parsing, no
per-listing detail fetch.
"""

from __future__ import annotations

from .shopify import ShopifyScraper

SITE_BASE = "https://www.ima-usa.com/"


class ImaUsaScraper(ShopifyScraper):
    slug = "ima-usa"
    name = "IMA-USA"
    base_url = SITE_BASE
    description = (
        "International Military Antiques. Their antique and collectible firearm "
        "collections are read; gun parts, holsters and cases are not."
    )
    default_interval_minutes = 1440

    #: The four firearm collections, and not `/collections/all`.
    #:
    #: They overlap — a Martini-Henry is in both "Original Antique Guns" and
    #: "Antique Long Guns" — which costs nothing: the walk de-duplicates on the
    #: product id, so a listing in three collections is read once and filed
    #: under the first that claimed it.
    sources = (
        {
            "category": "Original Antique Guns",
            "url": f"{SITE_BASE}collections/original-antique-guns",
        },
        {
            "category": "Collectible Antique Guns",
            "url": f"{SITE_BASE}collections/collectible-antique-guns",
        },
        {"category": "Antique Long Guns", "url": f"{SITE_BASE}collections/antique-long-guns"},
        {"category": "Antique Handguns", "url": f"{SITE_BASE}collections/antique-handguns"},
        {"category": "M1 Garand & U.S. Rifles", "url": f"{SITE_BASE}collections/garand-u-s-rifles"},
    )
