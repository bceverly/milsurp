"""Buffalo Arms (buffaloarms.com) -- the black powder shelves.

An Idaho supplier to the black powder cartridge and muzzleloading trades,
added on 2026-10-28 (the October 8 black powder survey had it as a "maybe").
Magento: Pedersoli, Lyman and Uberti reproductions new, and a consignment
shelf of used and new-in-box muzzleloaders.

**Only the first page of each section can be read.** robots.txt disallows
``/*?`` -- every query string -- which rules out Magento's ``?p=N`` paging and
``?product_list_limit``, so each section gives its first 16 and the rest are
reported unread rather than worked around (the Magento base checks robots.txt
before each page). On 2026-10-28 the rifles were 34 with 16 readable and the
consignment shelf 55 with 16; the pistols and most revolver leaves fit on one
page. Not read: the kits, and the cartridge cowboy guns beside these shelves.
"""

from __future__ import annotations

from .magento import MagentoScraper

SITE_BASE = "https://www.buffaloarms.com/"
_BLACK_POWDER = (
    f"{SITE_BASE}firearms-consignments/cowboy-firearms-44-muzzle-loaders-vintage-military/"
)
_MUZZLELOADERS = f"{_BLACK_POWDER}black-powder-muzzleloaders/"
_REVOLVERS = f"{_BLACK_POWDER}black-powder-muzzleloading-percussion-revolvers/"


class BuffaloArmsScraper(MagentoScraper):
    slug = "buffalo-arms"
    name = "Buffalo Arms"
    base_url = SITE_BASE
    description = (
        "Idaho black powder supplier: Pedersoli, Lyman and Uberti muzzleloaders and "
        "percussion revolvers, and a consignment shelf. The first page of each section only."
    )
    requires_browser = False
    default_interval_minutes = 1440
    #: New reproductions, and consignment guns beside them.
    sells = "mixed"
    newsletter_url = SITE_BASE
    newsletter_note = "Newsletter signup form in the footer"
    shipping_note = (
        "Antiques ship to the door; other firearms to a licensed dealer; no rate published"
    )
    shipping_source = f"{SITE_BASE}shipping-policy/"
    #: One page a section, by robots.txt (see above): asking for the second
    #: would only be refused, and warn, on every scan.
    max_pages_per_source = 1

    sources = (
        {
            "category": "Consignment Muzzleloaders",
            "url": f"{SITE_BASE}firearms-consignments/consignment-firearms-accessories/consignment-muzzleloaders.html",
        },
        {
            "category": "Black Powder Muzzleloading Rifles",
            "url": f"{_MUZZLELOADERS}black-powder-muzzleloading-rifles.html",
        },
        {
            "category": "Black Powder Muzzleloading Pistols",
            "url": f"{_MUZZLELOADERS}black-powder-muzzle-loading-pistols.html",
        },
        {
            "category": "Black Powder Muzzleloading Shotguns and Muskets",
            "url": f"{_MUZZLELOADERS}black-powder-muzzleloader-shotguns-smoothbore-muskets.html",
        },
        *(
            {"category": "Black Powder Percussion Revolvers", "url": f"{_REVOLVERS}{leaf}.html"}
            for leaf in (
                "1849-pocket-pistols-47-percussion",
                "1851-navy-model-revolvers",
                "1858-remington-army-percussion",
                "1860-army-percussion-revolvers",
                "1861-navy-percussion-revolver",
                "1862-pocket-model-percussion-revolvers",
                "dragoon-percussion-revolvers",
            )
        ),
    )
