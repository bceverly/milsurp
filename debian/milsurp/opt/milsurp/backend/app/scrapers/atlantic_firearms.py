"""Atlantic Firearms (atlanticfirearms.com).

The most-visited site on the roadmap -- roughly 837,000 visits a month when
that was last measured -- and the reason the PrestaShop base class exists.

**Three sections of nine, and the arithmetic is the whole story.** They are a
general dealer whose surplus corner is real but is mixed with a great deal of
gear, and measuring all six candidate sections before writing anything is what
kept most of them out:

===========================  =====  ==========================================
Section                      Rows   Verdict
===========================  =====  ==========================================
``/parts-kits``                 77  **Taken.** 38 read as kits -- Yugo, AK,
                                    VZ58, Galil, RPD. The other 39 are bare
                                    barrels, AR uppers and "IGLIM packages" of
                                    trigger guards and sights
``/c-r-eligible``               38  **Taken.** FN 1910s, a Radom P-64, a
                                    Bernardelli 60, Yugo M48A and M24/47
``/knives-blades``              13  **Taken.** 8 AKM bayonets, and the bayonet
                                    bucket is small enough to want them
``/military-surplus``          180  **Refused.** 98 read as neither gun nor
                                    kit: gas masks, rucksacks, ammo pouches,
                                    thread protectors, magazine grips
``/surplus-guns-gear``         165  **Refused.** The name is honest -- guns
                                    *and gear* -- and it overlaps the above
``/soviet-russian-surplus``     20  **Refused.** GP-5 gas masks, AKM wood
                                    grips, recoil spring assemblies
``/other-cool-firearms``       180  **Refused.** "Classic Military Arms" is
                                    modern Bula Defense M14 builds. The Arms
                                    Unlimited call again
===========================  =====  ==========================================

Taken together the four refused sections are 318 unique listings of which 123
are gear, so refusing them is the standing rule doing its job rather than
timidity.

A live run over the three returns **128 listings and no warnings**: 55 read as
parts kits, 47 as rifles, 13 as handguns and 13 as neither. (55 kits rather
than the 38 a title-only count suggested -- the product pages say "kit" where
several titles do not, which is the corroboration rule earning its keep again.)

**Half of what they list has no price, and that is the real caveat.** 71 of the
128 show nothing --
PrestaShop hides the price of an out-of-stock product. They are still worth
storing and they start reporting a price when the shop restocks, but a price
watcher gets less from this vendor than the listing count suggests. That is a
smaller version of the objection that dropped Century Arms, where the prices
were hidden by policy rather than by stock, and it is recorded here so nobody
re-measures it hopefully.

Their robots.txt is PrestaShop's generated one: it disallows the facet and sort
parameters -- ``?order=``, ``?tag=``, ``?search_query=``, ``?limit=`` -- and
says nothing about ``?page=``, so pagination is permitted where filtering is
not.
"""

from __future__ import annotations

from .prestashop import PrestaShopScraper

SITE_BASE = "https://www.atlanticfirearms.com/"


class AtlanticFirearmsScraper(PrestaShopScraper):
    slug = "atlantic-firearms"
    name = "Atlantic Firearms"
    base_url = SITE_BASE
    description = (
        "Large importer and retailer. Their parts kits, C&R guns and bayonets "
        "are read; their surplus *gear* sections and modern builds are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: Counts are what each section held when it was measured.
    sources = (
        {"category": "C&R Eligible", "url": f"{SITE_BASE}c-r-eligible"},  # 38
        {"category": "Parts Kits", "url": f"{SITE_BASE}parts-kits"},  # 77
        {"category": "Bayonets", "url": f"{SITE_BASE}knives-blades"},  # 13
    )
