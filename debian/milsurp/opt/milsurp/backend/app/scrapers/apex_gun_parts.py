"""Apex Gun Parts (apexgunparts.com).

The richest parts-kit source on the list, and the least ambiguous: a Beretta
M38/49 SMG, a BGS FAL, a Brazilian 1908 Mauser by DWM, a British Hotchkiss
M1909 "Portative" LMG with a torch-cut receiver, STEN Mk 3s, a C93, and CETME
Model C and L kits by the dozen.

A live run over five of their six pages returned **98 listings, no warnings,
and a price on every single one**. 93 read
as parts kits. The five that do not are their "Parts Set", "Parts Selection"
and "Spare Parts Set" listings, plus one sectioned Lee-Enfield drill purpose
musket: a listing has to corroborate its section heading by saying "kit"
somewhere of its own before the heading may call it one (see
``classify._is_a_parts_kit``), and these say "set". That rule is worth more
than five listings an admin can see and judge.

**They sell no complete firearms.** Their "Rifles", "Handguns" and "Machine
Guns" menus are *parts* sections organized by the gun the part fits -- the
whole shop is components -- so there is nothing else here to take. Parts kits
are the one category the standing rule admits, and they are all of it.

Magento, on the base class Classic Firearms already proved. Their robots.txt is
served empty, so nothing is restricted -- unlike Classic Firearms, who disallow
``?p=``, which is why that scraper walks facets instead. Here ordinary
pagination is allowed and is what this uses.
"""

from __future__ import annotations

from .magento import MagentoScraper

SITE_BASE = "https://www.apexgunparts.com/"


class ApexGunPartsScraper(MagentoScraper):
    slug = "apex-gun-parts"
    name = "Apex Gun Parts"
    base_url = SITE_BASE
    description = (
        "Surplus parts kits in quantity — CETME, STEN, FAL, Mauser, Beretta SMG. "
        "They sell parts only; there are no complete firearms to read."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: Their theme puts the description in an id with dots in it, which no
    #: stock Magento selector matches -- and their schema.org ``description``
    #: is Magento's auto-generated meta description, which on a Page Builder
    #: page is the opening of its own stylesheet. So the base class falls back
    #: to the markup here (see ``is_prose``), and this is the markup to ask.
    detail_description_selectors = (
        '[id="product.info.description"]',
        ".product.attribute.description",
    )

    sources = ({"category": "Parts Kits", "url": f"{SITE_BASE}parts-kits.html"},)
