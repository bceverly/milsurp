"""The Gun Works (app.scrapers.the_gun_works), added 2026-10-20."""

from __future__ import annotations

import pytest

from app.scrapers.the_gun_works import TheGunWorksScraper, is_part


@pytest.mark.parametrize(
    ("title", "part"),
    [
        ("Original \u2013 Lock \u2013 1842 Model \u2013 Percussion", True),
        ("Colt 2nd Generation \u2013 Pin", True),
        ("Original \u2013 Full Stock \u2013 Kentucky \u2013 Percussion \u2013 38Cal", False),
        ("Kentucky Pistol \u2013 Flint", False),
        ("1858 Remington \u2013 Steel Frame \u2013 44 Cal", False),
    ],
)
def test_a_part_sold_beside_the_guns(title, part):
    assert is_part(title) is part


def test_a_modern_inline_and_a_part_are_left_out():
    scraper = TheGunWorksScraper()

    def product(name):
        return {
            "id": 1,
            "permalink": "https://thegunworks.com/product/x/",
            "name": name,
            "prices": {"price": "50000", "currency_minor_unit": 2},
            "is_in_stock": True,
        }

    assert scraper.item_from_product(product("Kentucky Pistol &#8211; Flint"), "Pistols")
    assert (
        scraper.item_from_product(product("Pursuit &#8211; XT &#8211; In-line"), "Rifles") is None
    )
    assert scraper.item_from_product(product("Colt 2nd Generation &#8211; Pin"), "Pistols") is None
