"""DBG Firearms (dbgfirearms.com).

A general gun shop on Wix Stores whose used rack is where the surplus is: a
Siamese Type 46/66 Mauser, a Spanish M43, an FTR 1957 Enfield No4 Mk2, a Swiss
K11, a Carcano M91 TS, a Tula 91/30 hex receiver of 1933, a 1943 Underwood M1
Carbine, a Smith-Corona 1903 A3, a Savage No.4 Mk 1 sniper, a Turkish K.Kale
M1938, a Loewe Berlin 1891 Mauser, a Chinese Type 56S-2 -- 128 listings, beside
used Glocks, Rugers, Sigs and a run of S&W revolvers.

**So the whole Used section is read**, which is the Madison Guns case: the
shop does not shelve surplus apart from modern trade-ins, and the choice is to
read the mixed section and let ``classify.enrich`` sort it or to read nothing.

**Their "Mokas Raifusak Surplus" section is not read**, although the name is
the obvious one. Measured at 27 listings, it is magazines, slings, mag pouches
and furniture sets -- the individual components the standing rule keeps out --
plus nine guns, every one of which is also on the Used rack. **Nor is
Firearms**: of its 57, the 11 not also under Used are new modern production
(Daniel Defense, Noveske, ArmaLite, an ATI MP40 replica).

**This is the shop that taught the base class to stop on a repeated page.**
Asked for a page past the end, their sections serve the last page again rather
than an empty grid; see :mod:`app.scrapers.wix_stores`.

robots.txt gives ``User-agent: *`` ``Allow: /`` and disallows only
``*?lightbox=``, so ``?page=`` is fine. The ``Disallow: /`` near the bottom is
scoped to PetalBot.
"""

from __future__ import annotations

from .wix_stores import WixStoresScraper

SITE_BASE = "https://www.dbgfirearms.com/"


class DbgFirearmsScraper(WixStoresScraper):
    slug = "dbg-firearms"
    name = "DBG Firearms"
    base_url = SITE_BASE
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-09-26"
    description = (
        "A general gun shop with a large used rack. Surplus Mausers, Enfields, "
        "Mosins and M1s are mixed in among modern trade-ins, so the whole used "
        "section is read and the classifier sorts it."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = ({"category": "Used Firearms", "path": "category/used"},)
