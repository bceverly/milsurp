"""Checkpoint Charlie's (checkpointcharlies.com).

Stock WooCommerce. One section is a product *tag* rather than a category --
``/product-tag/cr/`` -- which changes nothing here: a tag archive renders the
same product loop and paginates the same way. It is recorded because the URL
looks like a mistake otherwise.

**The tag was the only thing read for a long time, and it is under half.**
Their ``/guns/`` tree has twelve military and antique leaves which together
hold 264 listings, **186 of them not carrying the C&R tag** -- a Winchester
Hotchkiss 1879 carbine, a Quality Hardware M1 Carbine, a Krieghoff Luftwaffe
flare pistol, Allen & Wheelock and Remington derringers. C&R eligibility is a
legal fact about a gun's age and the shop does not tag everything old, so it
was never going to be the catalog.

Their remaining leaves are left alone: `commercial-handguns`,
`commercial-long-guns`, `shotguns`, `revolvers`, `colt-handguns`,
`smith-wesson`, `winchester-remington-long-guns`, the two "JEJ Collection"
sections and `bb-guns-aire-rifles`, along with the whole
`/firearm-accessories/` tree.

**Their product pages refuse every request** -- 429 to any pace and any
headers -- so the base class stops asking after three failures in a row and
takes the rest of the run from the catalog. That makes extra sections cheap
here in a way they are not elsewhere: each one costs its category pages and
nothing more.
"""

from __future__ import annotations

from .woocommerce import WooCommerceScraper

SITE_BASE = "https://checkpointcharlies.com/"


class CheckpointCharliesScraper(WooCommerceScraper):
    slug = "checkpoint-charlies"
    name = "Checkpoint Charlie's"
    base_url = SITE_BASE
    description = (
        "Collector dealer. Their C&R tag and their military and antique gun "
        "sections are read; their commercial stock and accessories are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: The C&R tag first, because it is the most specific claim the shop makes
    #: about a listing, then the type-named leaves. Counts are what each held
    #: when it was added.
    _GUNS = f"{SITE_BASE}product-category/guns"
    sources = (
        {"category": "Curio & Relic", "url": f"{SITE_BASE}product-tag/cr/"},  # 163
        {"category": "Antique Handguns", "url": f"{_GUNS}/handguns/antique-handguns/"},  # 69
        {
            "category": "Other Military Handguns",
            "url": f"{_GUNS}/handguns/other-military-handguns/",
        },  # 112
        {"category": "Mauser & Walther Handguns", "url": f"{_GUNS}/handguns/mauser-walther/"},  # 41
        {
            "category": "U.S. Military Handguns",
            "url": f"{_GUNS}/handguns/us-military-handguns/",
        },  # 27
        {"category": "P38 Handguns", "url": f"{_GUNS}/handguns/p38-handguns/"},  # 26
        {"category": "Luger Handguns", "url": f"{_GUNS}/handguns/luger-handguns/"},  # 13
        {"category": "High Power Handguns", "url": f"{_GUNS}/handguns/high-power/"},  # 7
        {
            "category": "U.S. Military Long Guns",
            "url": f"{_GUNS}/long-guns/us-military-long-guns/",
        },  # 30
        {"category": "Antique Long Guns", "url": f"{_GUNS}/long-guns/antique-long-guns/"},  # 15
        {
            "category": "Other Military Long Guns",
            "url": f"{_GUNS}/long-guns/other-military-long-guns/",
        },  # 11
        {
            "category": "German Military Long Guns",
            "url": f"{_GUNS}/long-guns/german-military-long-guns/",
        },  # 9
        {"category": "Japanese Long Guns", "url": f"{_GUNS}/long-guns/japanese-long-gun/"},  # 1
    )
