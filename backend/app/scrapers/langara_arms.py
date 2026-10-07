"""Langara Arms & Antiques (langaraarms.com).

A Franklin, Pennsylvania dealer whose catalog is almost all military:
Mausers, Mosins, Enfields, Arisakas, Swiss straight-pulls and their pistols,
measured 2026-10-06 at 83 military long guns and 60 military handguns, every
one priced and in stock. WooCommerce with the Store API answering, so the
whole read is a handful of JSON requests.

Three sections are read: Military Rifles/Shotguns, Military Handguns and
Antique. "Modern Rifles/Shotguns" and "Modern Handguns" are their retail
shelf, and "New Arrivals" repeats the others. robots.txt turns away only SEO
crawlers.
"""

from __future__ import annotations

from .woo_store_api import WooStoreApiScraper

SITE_BASE = "https://www.langaraarms.com/"


class LangaraArmsScraper(WooStoreApiScraper):
    slug = "langara-arms"
    name = "Langara Arms & Antiques"
    base_url = SITE_BASE
    description = "Pennsylvania dealer in military surplus and antique rifles and handguns."
    default_interval_minutes = 1440
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-06"
    shipping_note = (
        "Flat $30 per handgun, $45-$60 per long gun by length; more to Alaska and Hawaii"
    )
    shipping_source = "https://www.langaraarms.com/orders-returns/"
    shipping_handgun = 30.0
    shipping_long_gun = 45.0

    sources = (
        {"category": "Military Rifles/Shotguns", "id": 26},
        {"category": "Military Handguns", "id": 25},
        {"category": "Antique", "id": 24},
    )
