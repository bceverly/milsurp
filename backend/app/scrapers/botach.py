"""Botach (botach.com).

A Las Vegas tactical retailer -- 11,136 products, of which 717 are firearms and
nearly all of those new modern production: HK, Glock, SIG, suppressors,
launchers and a shelf of law-enforcement-only machine guns. **One shelf is
read, "Trade-In / Used Guns"**, because that is where the surplus is: a
Lee-Enfield .303 and a K98 with Waffenamt, a 1927 Thompson, Colt SP1 and AR-15
A2 carbines, Remington 870s and Wingmasters, SIG P320s and a Beretta Model 70,
all police trade-ins.

**The catalog is Algolia's**, not the page's -- see :mod:`app.scrapers.algolia`.
The roadmap had this waiting on "the search endpoint read directly, the way
SARCO's is", and that is what this does.

**Twenty-nine of the shelf's 51 records are hidden** and are skipped: products
the shop has unpublished, whose pages are 404s, among them eight trade-ins all
priced at exactly $1,000. Of the 22 that are published, 7 were out of stock
when measured and arrive sold.

**The shelf is not only police stock**, so it is not labeled as if it were. It
also holds used civilian pistols (a Tanfoglio, two Ruger MKs, a Taurus 1911)
and an open-box Black Rain. The police-surplus bucket is read off the category,
so a listing is filed under "Police Trade-Ins" only when its own title says so
-- "Police Trade", "Police Demo", "Never Issued" -- and under "Used Guns"
otherwise.

robots.txt disallows the cart, account and search paths and nothing a product
page lives under; the Algolia host serves no robots.txt at all.
"""

from __future__ import annotations

import re
from typing import Any

from .algolia import AlgoliaScraper

SITE_BASE = "https://botach.com/"

#: A title that says where the gun came from. "Never Issued" is how Botach
#: title the department stock that went back unfired.
_POLICE = re.compile(r"\bpolice\s+(?:trade|demo)|\bnever\s+issued\b", re.I)


class BotachScraper(AlgoliaScraper):
    slug = "botach"
    name = "Botach"
    base_url = SITE_BASE
    description = (
        "Las Vegas tactical retailer. Only their trade-in and used shelf is read: "
        "police trade-in Colts, Remingtons, SIGs and the occasional Lee-Enfield or K98."
    )
    default_interval_minutes = 1440

    #: From the storefront's own ``algoliaConfig``. The key is Algolia's
    #: search-only kind, published in every page Botach serves -- not a secret,
    #: which is why gitleaks is told so on the line itself.
    app_id = "N6QOFUMLJZ"
    api_key = "5906d4bef736aeb9088dcd76a5d7424d"  # gitleaks:allow
    index = "Botach-Main"

    sources = (
        {
            "category": "Used Guns",
            "facet": "categories.lvl1:Firearms > Trade-In / Used Guns",
        },
    )

    detail_description_selectors = ("#tab-description",)

    def label_for(self, hit: dict[str, Any], label: str) -> str:
        return "Police Trade-Ins" if _POLICE.search(str(hit.get("name") or "")) else label
