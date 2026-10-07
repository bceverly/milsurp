"""Shoot It (shootitllc.com).

A Phoenix, Arizona dealer whose collectibles shelves are high-end: engraved
and inscribed Colts, Winchesters and lawman's guns, among the curio-and-relic
military pieces. An ordinary BigCommerce Stencil store. Read: Curio & Relic
and Antique Firearms. Not read: memorabilia, old ammunition and the modern
retail catalog.

robots.txt disallows the cart, account and search paths and the faceted
``_bc_fsnf`` parameter, and nothing this reads. A 21-and-over notice is shown
to visitors but gates nothing on the server.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://www.shootitllc.com/"


class ShootItScraper(BigCommerceScraper):
    slug = "shoot-it"
    name = "Shoot It"
    base_url = SITE_BASE
    description = "Arizona dealer's curio-and-relic and antique shelves: engraved Colts, Winchesters, military pieces."
    requires_browser = False
    default_interval_minutes = 1440
    newsletter_url = SITE_BASE
    newsletter_note = (
        "No form in the page itself; Klaviyo is loaded, so signup is a popup on the home page"
    )
    shipping_note = "Free shipping on orders over $500; otherwise calculated at checkout"
    shipping_source = "https://www.shootitllc.com/terms-conditions/"

    sources = (
        {"category": "Curio & Relic", "url": f"{SITE_BASE}collectibles/curio-relic/"},
        {
            "category": "Antique Firearms",
            "url": f"{SITE_BASE}collectibles/antique-firearms-for-sale/",
        },
    )
