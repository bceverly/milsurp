"""Surplus Defense (surplusdefense.com).

Small and entirely on subject, which is a combination this list does not offer
often. Forty-five listings across three sections and every one of them is
collector milsurp: an IBM Corp. M1 Carbine of 1943, a Spanish Oviedo Mauser
1917, a matching Russian 91/30 Tula 1939, an M41 Carcano, a Turkish M1938
Mauser, a WW1 German DWM 1916 Artillery Luger matching with its holster, two
T-Series Browning High Powers, an 1895 Nagant revolver, a chromed 1941 Mauser
Luger, an SS dagger, an SA dagger by J.P. Sauer und Sohn, and a Japanese
Imperial Type 98 sword.

The first Wix Stores shop here, so the walk is in
:mod:`app.scrapers.wix_stores` and this is the sections and nothing else.

**Their edged weapons are read, unlike most shops'.** The standing rule keeps
gear and components out, and an SS dagger, an SA dagger by J.P. Sauer und Sohn
and a Japanese Imperial Type 98 sword are neither -- they are the collectible
objects this catalog is about, at $550 to $1,500 apiece. `/accessories`,
`/ammunition`, `/field-gear` and `/flags-and-armbands` are left alone on the
usual grounds.

**Daggers and swords file with the bayonets.** They used to land under
"Other" with the slings and magazines, which was a gap rather than a decision;
in September 2026 the decision was made to put collectible blades in the
bayonet bucket (``classify._EDGED``). Their fighting knife, a WW2 Ka-Bar, still
files under "Other": knives were not part of that decision.

**Eighteen of the forty-five are out of stock**, and on this platform that is
how a shop says sold: the price is removed with the listing's availability, so
a card with no price here is gone rather than "call for price". `/sold-items`
exists as its own page and is *not* read -- what it holds is already in the
three sections above, marked out of stock.
"""

from __future__ import annotations

from .wix_stores import WixStoresScraper

SITE_BASE = "https://www.surplusdefense.com/"


class SurplusDefenseScraper(WixStoresScraper):
    slug = "surplus-defense"
    name = "Surplus Defense"
    base_url = SITE_BASE
    newsletter_url = "https://www.surplusdefense.com/email-newsletter-signup"
    newsletter_note = "Email newsletter signup page"
    description = (
        "Small collector dealer, entirely surplus: matching Mosins, Lugers, "
        "Mausers and Carcanos, with a shelf of daggers and swords."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = (
        {"category": "Surplus Rifles", "path": "surplus-rifles"},
        {"category": "Surplus Handguns", "path": "surplus-handguns"},
        {"category": "Edged Weapons", "path": "edged-weapons"},
    )
