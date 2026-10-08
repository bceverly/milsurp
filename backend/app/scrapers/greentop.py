"""Greentop (greentop.com).

A Virginia hunting and shooting store with a used-gun counter: 144 used pistols
and 41 used revolvers on 2026-10-08, about three in ten of them carry guns --
Ruger EC9s, M&P45 Shields, Taurus GX4s, Glock 19s and 27s, Kimber Ultra CDPs,
Walther PPK/Ss, Kel-Tec P3ATs. Titles state the barrel length and condition.

Magento. Two sections are read, Used Pistols and Used Revolvers, each paged by
``?p=``. Not read: their used rifles and shotguns (not what this was built
for), the new-gun catalog, and the archive of sold used guns. robots.txt asks
for five seconds between requests, which the scanner honors, and turns away
only Magento's sort and page-size parameters, which the walk never builds.
"""

from __future__ import annotations

from .magento import MagentoScraper

SITE_BASE = "https://www.greentop.com/"


class GreentopScraper(MagentoScraper):
    slug = "greentop"
    name = "Greentop"
    base_url = SITE_BASE
    description = "Virginia store's used pistols and revolvers, carry guns among them."
    default_interval_minutes = 1440
    newsletter_url = "https://www.greentop.com/email-sign-up/"
    shipping_note = "Firearm shipping free: handguns 2nd Day Air, long guns Ground"
    shipping_source = "https://www.greentop.com/shipping-info/"
    shipping_handgun = 0.0
    shipping_long_gun = 0.0

    sources = (
        {"category": "Used Pistols", "url": f"{SITE_BASE}shooting/used-guns/pistols/"},
        {"category": "Used Revolvers", "url": f"{SITE_BASE}shooting/used-guns/revolvers/"},
    )
