"""Arms of America (armsofamerica.com).

A Pennsylvania importer and builder, and the first vendor here added for its
**parts kits** rather than its firearms. 43 of them, and they are the real
thing: a PPSh-41 with drum, IWI UZI, Yugo M72B1 RPK, Polish Radom DPM and RPD
light machine guns, a Sig STG 57, a VZ61 Skorpion, G3/HK91.

Their four **Military Surplus** rifles are Swiss and C&R -- an 1889, a K11, an
1896/11 and an 1911 -- so that section is read too, small as it is.

A full run is 47 listings with no warnings, and every one of them lands where
it belongs: 43 read as parts kits, 4 as rifles, nothing miscategorized.

**Their other firearm sections are deliberately left out**, and this is the
fourth time that call has been made on this list. `/firearms/rifles/` and
`/our-products/firearms/pistols/` are modern builds: WBP Fox and Jack AKs, FB
Radom Beryls, Mini Jack AK pistols, and the shop's own custom AKM builds. Good
guns, and no more surplus than the Colt M4s that got Arms Unlimited backed out.

**25 of the 47 carry no price, and that is correct.** BigCommerce hides the
price on an out-of-stock product, and a sold-out kit has no current price to
track. They arrive as "call for price" and start reporting one when the shop
restocks.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://armsofamerica.com/"


class ArmsOfAmericaScraper(BigCommerceScraper):
    slug = "arms-of-america"
    name = "Arms of America"
    base_url = SITE_BASE
    description = (
        "Importer and builder. Their parts kits and four Swiss C&R rifles are "
        "read; their modern AK builds are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = (
        {"category": "Parts Kits", "url": f"{SITE_BASE}all-products/parts-kits/"},
        {"category": "Military Surplus", "url": f"{SITE_BASE}firearms/military-surplus/"},
    )
