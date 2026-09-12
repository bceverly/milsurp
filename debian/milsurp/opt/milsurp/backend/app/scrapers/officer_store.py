"""Officer Store (officerstore.com).

A police-equipment retailer whose firearms are one section: department trade-ins,
mostly Glocks, each graded. A stock BigCommerce shop.

**Their titles carry a condition grade**, which almost nothing else in this
catalog does: "LE Trade-In Glock 21 Gen 4, .45 ACP, 3 Mags, Grade 2". Grade 2
and Grade 3 at the same model number are different objects at different prices --
$339.99 against $329.99 for the same Gen 4 21 -- and that is the vendor stating
plainly what surplus listings usually leave to a photograph.

**One section, and it is genuinely one.** ``/firearms/used-firearms`` is the
whole of their firearms catalog; there is no wider shop to leave out here, which
makes this the cheapest of the ten police vendors surveyed. A handful of Glock
magazines are shelved among the pistols and are left to the classifier rather
than to a second section, because there is no second section to read.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://officerstore.com/"


class OfficerStoreScraper(BigCommerceScraper):
    slug = "officer-store"
    name = "Officer Store"
    base_url = SITE_BASE
    description = (
        "Police equipment retailer. Their one firearms section is department "
        "trade-ins, graded by condition and mostly Glocks."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = (
        {"category": "Law Enforcement Trade-Ins", "url": f"{SITE_BASE}firearms/used-firearms/"},
    )
