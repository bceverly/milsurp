"""Allegheny Arsenal (mg34.com).

A machine-gun parts house in Pennsylvania that also sells complete guns, from
one section: "Guns for Sale". A stock BigCommerce shop -- the product id is on
every card, pagination is ``?page=N``, and robots.txt disallows only the cart,
account and search pages.

**The section is two shops in one.** Measured 2026-09-27: 113 listings, every
one priced. About 45 are what this application is for -- No. 4 Mk1 (T)
snipers, an SVT-38, P08 Lugers, Mosins, a Nambu, a Thompson, and semi-auto
belt-feds built on surplus parts (Vz.59, PKM, SG-43, Breda M37, Vickers). The
rest is new retail stock on the same shelf: fourteen closeout Remington 700
barreled actions, POF ARs, Vigilance .50s, a Kriss Vector, a Nighthawk 1911.
Also a Bramit suppressor, and a "Trench Gun Conversion Service" that is work
done on your own shotgun rather than a gun at all.

**So a listing is read only when its title says it is military**, which is
the other way round from Classic Firearms' police sections, where the section
is right and a few titles are wrong. A list of modern guns to leave out would
lose to the next closeout. A listing gets in by:

* a marker the shop writes on surplus: "C&R", "WWII", "WW1", "USGI",
  "Surplus", "Military", "Bring Back", "Civil War", "Police Trade In";
* or a military model name: Mosin, Enfield, P08, Nambu, Makarov, SVT, Garand,
  M1 Carbine, the belt-feds, and so on (:data:`_MILITARY_MODEL`).

"Luger" alone is not a model name here, because "9mm Luger" is a caliber, and
a Kriss Vector in 9mm Luger is not a P08. Suppressors, a listing marked "not
available for sale", and conversion services are left out even when their
titles name a war.
"""

from __future__ import annotations

import re

from bs4 import Tag

from .base import ScrapedItem
from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://mg34.com/"

_MILITARY_MARKER = re.compile(
    r"\bC&R\b|\bWW\s?(?:I{1,2}|[12])\b|\bWorld\s+War\b|\bCivil\s+War\b|\bUSGI\b"
    r"|\bsurplus\b|\bmilitary\b|\bbring\s*back\b|\bpolice\s+trade",
    re.I,
)

_MILITARY_MODEL = re.compile(
    r"\bMosin\b|\bEnfield\b|\bP0?8\b|\bNambu\b|\bMakarov\b|\bSVT\b|\bGarand\b"
    r"|\bM1\s+Carbine\b|\bM1911(?:A1)?\b|\b1903(?:A[34])?\b|\bKrag\b|\bArisaka\b"
    r"|\bWebley\b|\bSharps\b|\bThompson\b|\bVickers\b|\bMG\s?34\b|\bMG\s?42\b"
    r"|\bBreda\b|\bZB\s?37\b|\bSG\s?43\b|\bVz\.?\s?59\b|\bPKM\b|\bRPD\b|\bDTM\b"
    r"|\bBrowning\s+1919\b|\bOerlikon\b|\bM134\b",
    re.I,
)

_NOT_A_GUN = re.compile(
    r"\bsuppressor\b|\bnot\s+available\s+for\s+sale\b|\bconversion\s+service\b", re.I
)


def is_military(title: str) -> bool:
    """Whether a listing's title says it is surplus or a military model."""
    if _NOT_A_GUN.search(title):
        return False
    return bool(_MILITARY_MARKER.search(title) or _MILITARY_MODEL.search(title))


class AlleghenyArsenalScraper(BigCommerceScraper):
    slug = "allegheny-arsenal"
    shipping_note = "USPS and FedEx only; no firearm shipping cost stated"
    shipping_source = "https://mg34.com/ordering/"
    name = "Allegheny Arsenal"
    base_url = SITE_BASE
    newsletter_url = SITE_BASE
    newsletter_note = "Newsletter Signup form in the home page footer"
    description = (
        "Machine-gun parts house with a mixed gun shelf: surplus rifles and "
        "pistols, C&R pieces, and semi-auto belt-feds on surplus parts. Its "
        "new modern guns are not read."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = ({"category": "Guns for Sale", "url": f"{SITE_BASE}product-category/guns-for-sale"},)

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        item = super().item_from_card(card, page_url, category)
        if item is None or not is_military(item.title):
            return None
        return item
