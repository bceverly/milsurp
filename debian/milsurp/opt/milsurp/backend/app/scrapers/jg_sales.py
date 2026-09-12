"""J&G Sales (jgsales.com).

The roadmap had this filed under **needs a browser**, on the evidence of the
catalog page: sixteen ``li.product`` elements arrive empty and there is not one
dollar sign in 394KB of HTML, because the grid is rendered client-side. That
observation was correct and the conclusion drawn from it was not. The same
WordPress install publishes the WooCommerce Store API, which answers with the
whole catalog as JSON — price, stock, SKU, gallery and description — and needs
no browser at all.

The lesson is the one the roadmap already draws about platform inference: what
the HTML looks like is not what a site *is*. Measure the endpoints before
concluding a shop is expensive to read.

**Sections.** J&G is a general dealer; most of the catalog is ammunition,
magazines and modern sporting rifles. Only the collector sections are taken,
named by their numeric category id because that is what the endpoint filters
on. "Surplus Military Gear", "M1 Carbine & Surplus Stocks" and "US Military
Pattern" are deliberately left out: those are field gear, stocks and clothing,
and the accessory rules would spend their time throwing the results away.

**Their category ids are not guessable and the listing does not page far.**
`/wp-json/wc/store/v1/products/categories` returns 224 of them across three
pages, and reading only the first missed the parts-kit section entirely.
"""

from __future__ import annotations

from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://www.jgsales.com/"


class JgSalesScraper(WooStoreApiScraper):
    slug = "jg-sales"
    name = "J&G Sales"
    base_url = SITE_BASE
    description = "Military surplus, C&R and collectible firearms from a Prescott, Arizona dealer."
    default_interval_minutes = 1440

    #: The ids come from /wp-json/wc/store/v1/products/categories, which is
    #: public and paged. They are stable — WordPress term ids do not change —
    #: and the label beside each is what a listing is filed under here.
    sources = (
        {"category": "Military Mausers", "id": 3689},
        {"category": "Collector's Corner", "id": 3662},
        {"category": "Commercial Collectibles", "id": 3663},
        {"category": "C&R and Antique Guns", "id": 3685},
        {"category": "Military & Surplus Collectible", "id": 3686},
        # Their parts-kit section, five products deep and reading empty as of
        # 8 Sep 2026 -- the Store API returns none for it, as it does for
        # Military Mausers, whose 56 are simply out of stock. Kept because it
        # costs one request and the section is real; an empty first page ends
        # a walk silently, so nothing is reported when there is nothing there.
        {"category": "Parts Kits", "id": 3773},
        # Three small sections found by auditing their category list against
        # what this reads. Twelve listings between them and every one on
        # subject: a Swiss K11 short rifle, a Carcano M.91 cavalry carbine, a
        # Yugo M57 Tokarev, an Arisaka Type 38 trainer, three Springfield 1903s
        # and a Krag, an Izhevsk 91/30. Their big "Handguns" (239) and "Rifles"
        # (65) sections are the modern retail catalog and stay out.
        {"category": "Gunsmith Specials", "id": 3692},
        {"category": "US Military Pattern", "id": 3673},
        {"category": "Mosin Nagant", "id": 3761},
    )
