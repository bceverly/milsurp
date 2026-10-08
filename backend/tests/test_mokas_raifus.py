"""Moka's Raifus: what is read off two shelves that hold more than guns.

The shape of a whole recorded scan is checked in test_recorded_scrapers.py.
These are the two rules a recording cannot pin.
"""

from __future__ import annotations

import pytest

from app.scrapers.mokas_raifus import MokasRaifusScraper, is_a_whole_kit


def product(name, *categories, price="149499"):
    """One Store API product, as much of it as the scraper reads."""
    return {
        "id": 7,
        "name": name,
        "permalink": "https://mokasraifus.com/product/x/",
        "prices": {"price": price, "currency_minor_unit": 2},
        "is_in_stock": False,
        "categories": [{"name": c} for c in categories],
        "images": [],
    }


class TestThePartsShelf:
    @pytest.mark.parametrize(
        "title",
        [
            "USGI M1A1 Thompson Parts Kit",
            "Yugoslavian M76 Original Barrel Parts Kit",
            "Bulgarian “AK74M” Parts Kit Build Clone \u2013 5.45x39mm \u2013 USED",
        ],
    )
    def test_a_kit_is_kept(self, title):
        assert is_a_whole_kit(title)

    @pytest.mark.parametrize(
        "title",
        [
            # Most of the shelf: one part of a gun, not a gun in pieces.
            "Chinese M80 PKM Barrel \u2013 7.62x54r",
            "Romanian PM90/AIMR Bolt Carrier",
            # A .22 slide for a CZ75, which says "kit" and is not one.
            "Czech CZ75 Kadet Conversion Kit \u2013 .22LR",
        ],
    )
    def test_a_part_is_not(self, title):
        assert not is_a_whole_kit(title)

    def test_the_thompson_comes_through_with_its_price(self):
        item = MokasRaifusScraper().item_from_product(
            product("USGI M1A1 Thompson Parts Kit", "Parts Kits and Misc Parts"), "Parts Kits"
        )
        assert (item.title, item.price, item.is_sold) == (
            "USGI M1A1 Thompson Parts Kit",
            1494.99,
            True,
        )


class TestTheGunShelf:
    """The API answers "Firearms" with its child categories too, and two of
    them are not guns."""

    def read(self, name, *categories):
        return MokasRaifusScraper().item_from_product(product(name, *categories), "Firearms")

    def test_a_gun_filed_under_firearms_is_kept(self):
        assert self.read(
            "Polish Radom P-83 Pistol \u2013 9MM Makarov", "Firearms", "Surplus Firearms"
        )

    def test_a_suppressor_is_not(self):
        assert self.read("RS9 \u2013 Resilient Suppressors", "Suppressors") is None
        assert self.read("Putnik", "Accessories", "Muzzle Devices", "Suppressors") is None

    def test_nor_is_the_adar_lines_furniture(self):
        assert self.read("Mokas Raifus ADAR Wood Stock", "ADAR", "Stocks") is None
        # Their rifle is filed under Firearms as well, and stays.
        assert self.read("Mokas Raifus ADAR 2-15 Rifle \u2013 5.56x45mm", "ADAR", "Firearms")
