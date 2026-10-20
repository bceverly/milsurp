"""Florida Guns (floridaguns.com).

Asked for on 2026-10-20 for concealed carry pistols and revolvers. Coreware's
storefront with a Meilisearch catalog (see :mod:`app.scrapers.coreware_search`):
about 4,900 handguns in stock that day, 29 of them on the shop's own shelf and
the rest at its distributors. The carry calibers are what is read.
"""

from __future__ import annotations

from .coreware_search import CorewareSearchScraper

SITE_BASE = "https://www.floridaguns.com/"


class FloridaGunsScraper(CorewareSearchScraper):
    slug = "florida-guns"
    name = "Florida Guns"
    base_url = SITE_BASE
    description = "Gun shop with a distributor's catalog: carry pistols and revolvers, new."
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-20"
    shipping_note = '"Flat rate" shipping to the lower 48, no amount stated (checked 2026-10-20)'
    shipping_source = "https://www.floridaguns.com/store-policies"
