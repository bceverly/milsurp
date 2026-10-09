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


def option(id_, label, price, in_stock):
    """One variation as the Store API returns it."""
    return {
        "id": id_,
        "parent": 105809,
        "variation": f"Condition: {label}",
        "prices": {"price": price, "currency_minor_unit": 2},
        "is_in_stock": in_stock,
    }


class TestAProductSoldAsOptions:
    """Reported from the running site, 2026-10-08: Moka's Raifus' West German
    AP66 read as available at $99.99, and every one of its pistols was gone.
    The shop sells each gun as an option of one product, and adds one called
    "RESTOCK EMAIL SIGNUP" -- a waiting list -- which never runs out.
    WooCommerce calls a product in stock when any option is, and quotes the
    cheapest option, sold or not."""

    AP66 = {
        "id": 105809,
        "type": "variable",
        "name": "West German WELT WAFFEN AP66 Pistol \u2013 .32 ACP",
        "is_in_stock": True,
        "prices": {"price": "9999", "currency_minor_unit": 2},
    }

    def test_the_waiting_list_does_not_keep_it_on_sale(self):
        from app.scrapers.woo_store_api import is_sold, price_now, with_options_settled

        settled = with_options_settled(
            self.AP66,
            [
                option(105832, "Welt Waffen Pistol - 3", "9999", False),
                option(105830, "Welt Waffen Pistol - 1", "19999", False),
                option(109808, "RESTOCK EMAIL SIGNUP", "27999", True),
            ],
        )
        assert is_sold(settled)
        # Gone, and keeping the last real price it carried.
        assert price_now(settled) == 99.99

    def test_one_real_pistol_left_is_on_sale_at_its_own_price(self):
        from app.scrapers.woo_store_api import is_sold, price_now, with_options_settled

        settled = with_options_settled(
            self.AP66,
            [
                option(105832, "Welt Waffen Pistol - 3", "9999", False),
                option(105830, "Welt Waffen Pistol - 1", "19999", True),
                option(109808, "RESTOCK EMAIL SIGNUP", "27999", True),
            ],
        )
        assert not is_sold(settled)
        assert price_now(settled) == 199.99

    def test_options_that_are_only_placeholders_change_nothing(self):
        from app.scrapers.woo_store_api import with_options_settled

        only = [option(1, "Notify me when back in stock", "100", True)]
        assert with_options_settled(self.AP66, only) is self.AP66

    @pytest.mark.parametrize(
        "label",
        ["RESTOCK EMAIL SIGNUP", "Email Signup", "Coming Soon", "Pre-Order Deposit", "Waitlist"],
    )
    def test_what_counts_as_a_placeholder(self, label):
        from app.scrapers.woo_store_api import is_placeholder_option

        assert is_placeholder_option({"variation": f"Condition: {label}"})

    @pytest.mark.parametrize("label", ["Welt Waffen Pistol - 4", "Very Good", "Grade 2"])
    def test_and_what_is_a_gun(self, label):
        from app.scrapers.woo_store_api import is_placeholder_option

        assert not is_placeholder_option({"variation": f"Condition: {label}"})
