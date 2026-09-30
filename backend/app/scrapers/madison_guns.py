"""Madison Guns (madisonguns.com).

A general gun shop whose used rack is worth reading. 164 listings, and the
milsurp is scattered through them rather than shelved apart: a Steyr M95, a
Springfield 1903 A3, an all-matching WWII Japanese paratrooper Arisaka, a
Winchester 1895 Russian contract with its bayonet, a Zastava M57 Tokarev, a
broken CZ vz.50, a Spanish Mauser receiver and bolt, a drill-purpose SMLE.
Police trade-ins turn up in the same section -- an F1 Firearms AR-15 and a
Remington 700P among them.

**So the whole used section is read, not a surplus corner of it**, because
there is no surplus corner. This is the Arms Unlimited case rather than the
Bowman Arms one: a shop that does not sort its stock the way this catalog
does, where the choice is to read a mixed section and let ``classify.enrich``
sort it or to read nothing. Their new-guns section is a modern gun shop and is
left alone, and so is Police Gear, which is a Taser.

**Their "Used Guns" lives under /ammunition/**, which is a category tree
somebody rearranged without moving the URLs. It is not a mistake in this file;
following the shop's own navigation is what produces it.

**Antique Firearms & Accessories is read as well** and currently holds one
listing, a Springfield 1884 Trapdoor. A section of one is worth a source entry
when it is the section this application exists for -- it costs one request per
scan, and the alternative is noticing in six months that a Trapdoor was never
imported.

robots.txt names a long list of AI crawlers and gives them ``Crawl-delay: 10``.
We are not one of them -- the configured user agent is MilsurpMonitor -- so the
``User-agent: *`` group applies and asks for nothing but the cart and account
paths, which `app.robots` already honors. The faceted-nav parameter
``_bc_fsnf`` is disallowed for everybody; the base class paginates with
``?page=``, which is not.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://madisonguns.com/"


class MadisonGunsScraper(BigCommerceScraper):
    slug = "madison-guns"
    shipping_note = "Ships FedEx within two business days; no firearm shipping cost stated"
    shipping_source = "https://madisonguns.com/web-policy/"
    name = "Madison Guns"
    base_url = SITE_BASE
    newsletter_url = "https://madisonguns.com/"
    newsletter_note = "Newsletter footer form on the home page"
    description = (
        "A general gun shop with a large used rack. The surplus is mixed in "
        "among modern trade-ins rather than shelved apart, so the whole used "
        "section is read and the classifier sorts it."
    )
    requires_browser = False
    default_interval_minutes = 1440
    #: Their red "STOP -- You must be 21+ to purchase this item. Please read the
    #: ENTIRE description." sign, and its "18+" twin for long guns. Between them
    #: they led 171 galleries (September 2026), at two sizes and each at its own
    #: URL, so the sign is recognized by how it looks and moved last.
    demoted_images = ("61e894a4ece06294",)

    sources = (
        {"category": "Used Guns", "url": f"{SITE_BASE}ammunition/used-guns/"},
        {
            "category": "Antique Firearms",
            "url": f"{SITE_BASE}products-for-sale-online/antique-firearms-accessories/",
        },
    )
