"""The two shops added on 2026-10-08 beside Moka's Raifus, and the one
classifier rule J & J's shelf turned up. The shape of a whole recorded scan is
checked in test_recorded_scrapers.py.
"""

from __future__ import annotations

import pytest

from app.scrapers.jj_military import JjMilitaryScraper
from app.services.classify import classify_firearm


def product(name, *categories, price="129500"):
    """One Store API product, as much of it as the scrapers read."""
    return {
        "id": 7,
        "name": name,
        "permalink": "https://jjmilitary.com/product/x/",
        "prices": {"price": price, "currency_minor_unit": 2},
        "is_in_stock": True,
        "categories": [{"name": c} for c in categories],
        "images": [],
    }


class TestJjMilitary:
    def read(self, name, *categories, price="129500"):
        return JjMilitaryScraper().item_from_product(
            product(name, *categories, price=price), "Antique Firearms"
        )

    def test_a_gun_is_read(self):
        item = self.read("US Navy Jenks Carbine", "Antique Firearms", "Longarm Carbines US")
        assert (item.title, item.price) == ("US Navy Jenks Carbine", 1295.0)

    @pytest.mark.parametrize(
        ("title", "filed"),
        [
            # A part names the gun it fits, which is enough for the classifier
            # to call an $18 screw a carbine. The shop's own filing says better.
            ("Spencer M-1865 Carbine & Rifle Hinge Pivot Screw", "Gun Parts"),
            ("Krag M-1897 Rifle & Carbine Tool", "Tools, Tompions, Cap Tins & Accessories"),
            # The case a revolver came in, without the revolver.
            (
                "Colt M-1851 Navy Revolver Factory Case",
                "Holsters, Slings, Belts, Buckles, Hangers, Boxes",
            ),
        ],
    )
    def test_parts_tools_and_cases_are_not(self, title, filed):
        assert self.read(title, "Antique Firearms", filed, price="1800") is None

    def test_a_price_on_request_is_no_price(self):
        item = self.read("Colt Baby Dragoon Percussion Revolver", "Antique Firearms", price="0")
        assert item.price is None


class TestACartridgeConversion:
    """A percussion revolver altered to take cartridges was filed as
    ammunition: "cartridge", as the last noun in the title, read as the thing
    being sold."""

    @pytest.mark.parametrize(
        "title",
        [
            "Whitney Navy Percussion Revolver Altered to Cartridge",
            "Colt 1860 Army Revolver Converted to Cartridge",
        ],
    )
    def test_is_the_revolver(self, title):
        assert classify_firearm(title, category="Antique Firearms") == (False, True)

    def test_while_cartridges_for_sale_are_still_not_a_gun(self):
        assert classify_firearm("Box of 50 .44 Colt Cartridges") == (False, False)
