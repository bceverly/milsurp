"""Bowman Arms (bowmanarms.com).

Small and entirely on-subject: seventeen parts kits, and the stock is the kind
this catalog exists for -- a Polish PM63 RAK, WZ.43/52, a Yugoslav M56, an
Israeli FAL, a Colt 653, a Heckler & Koch G36 Schnittmodell and a 1928 Thompson.
Every one carries a price, which is more than can be said for some larger shops
here.

Parts kits are all they list. There is no firearms section to leave out.

**All seventeen read as kits and all seventeen carry a price**, which no other
shop on this list manages. Five of them are titled "BASE MODEL - NO BARREL"
and never say the word "kit" in the title -- the classifier wants a listing to
corroborate its section heading before that heading may call it a kit, see
``classify._is_a_parts_kit`` -- and they are caught anyway, because the product
page says it. That is the detail fetch earning its keep.

**Priced is not the same as in stock**, and on this platform the two look
identical from the grid: six of seventeen sampled are ``OutOfStock`` in their
own structured data while still showing a price. See
``bigcommerce.sold_out()``.

One product page answers 403 to every request, including retries: their
Colt 653. It is not a block on us -- the shop's own server says "You Do Not
Have Permission To Access This Page", and its navigation renders around the
message -- it is a product filed in a category restricted to signed-in
customers. The base class keeps the catalog entry, so seventeen listings
arrive rather than a failure with none.

**It is logged rather than warned**, because a shop's standing access policy
is not a fault and a site permanently PARTIAL over one teaches whoever reads
the scan list that PARTIAL means nothing. A *run* of refusals still warns and
still stops the walk -- see `base.vendors_answer`.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://bowmanarms.com/"


class BowmanArmsScraper(BigCommerceScraper):
    slug = "bowman-arms"
    name = "Bowman Arms"
    base_url = SITE_BASE
    description = "Parts kits only, and all of them surplus. Seventeen listings, every one priced."
    requires_browser = False
    default_interval_minutes = 1440

    sources = ({"category": "Parts Kits", "url": f"{SITE_BASE}parts-kits/"},)
