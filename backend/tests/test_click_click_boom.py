"""Click-Click-Boom (app.scrapers.click_click_boom), added 2026-11-04.

The scan itself is replayed from its recording (test_recorded_scrapers);
these pin the rules that decide which of the shop's guns are used.
"""

from __future__ import annotations

from app.robots import Robots
from app.scrapers.click_click_boom import ClickClickBoomScraper, is_used, section
from app.scrapers.woo_store_api import WooStoreApiScraper


def _product(name, condition=None, categories=("Firearms",), tags=()):
    product = {
        "id": 338906,
        "permalink": "https://click-click-boom.com/shop/firearms/handguns/x/",
        "name": name,
        "prices": {"price": "34995", "currency_minor_unit": 2},
        "is_in_stock": True,
        "categories": [{"name": c} for c in categories],
        "tags": [{"name": t} for t in tags],
        "attributes": [],
    }
    if condition is not None:
        product["attributes"].append(
            {"name": "Condtion", "terms": [{"name": term} for term in condition]}
        )
    return product


class TestWhichGunsAreUsed:
    def test_the_condition_attribute_decides(self):
        assert is_used(_product("Beretta 950B .25 ACP", ["Used"]))
        assert not is_used(_product("Ruger American Gen II", ["New"]))

    def test_new_and_used_at_once_is_a_new_in_box_collectible(self):
        assert not is_used(_product("Winchester 9410 w/Original Box, Unfired", ["New", "Used"]))

    def test_without_one_the_title_says_it(self):
        assert is_used(_product("Used Remington Model 31 12-Gauge"))
        assert not is_used(_product("Henry All-Weather Side Gate .45-70"))
        assert not is_used(_product("Unfired Taylor&#8217;s 1851 Navy Snub Nose"))

    def test_the_shop_correcting_its_spelling_changes_nothing(self):
        product = _product("Beretta 950B")
        product["attributes"] = [{"name": "Condition", "terms": [{"name": "Used"}]}]
        assert is_used(product)


class TestTheListing:
    def test_a_used_handgun_is_filed_as_one_and_is_not_new(self):
        scraper = ClickClickBoomScraper()
        item = scraper.item_from_product(
            _product(
                "Used Beretta 950B .25 ACP Pistol",
                ["Used"],
                ("Firearms", "Handguns, Pistols &amp; Revolvers", "IN STOCK GUNS"),
            ),
            "Used Firearms",
        )
        assert item is not None
        assert item.category == "Used Handguns"
        assert item.is_new is False
        assert item.price == 349.95

    def test_a_long_gun_and_one_in_neither(self):
        assert section(_product("x", categories=("Firearms", "Long Guns"))) == "Used Long Guns"
        assert section(_product("x")) == "Used Firearms"

    def test_new_guns_and_special_orders_are_left_out(self):
        scraper = ClickClickBoomScraper()
        assert scraper.item_from_product(_product("Glock 19", ["New"]), "x") is None
        special = _product("Used Colt Python", ["Used"], tags=("Special Order",))
        assert scraper.item_from_product(special, "x") is None


def test_its_requests_are_ones_robots_allows():
    """The shop disallows ``&orderby=``, which the shared walk sends."""
    robots = Robots.parse("User-agent: *\nAllow: /\nDisallow: /*?orderby=\nDisallow: /*&orderby=\n")
    scraper = ClickClickBoomScraper()
    agent = "Mozilla/5.0"
    assert not robots.allows(WooStoreApiScraper.endpoint(scraper, 2, 22039), agent)
    assert robots.allows(scraper.endpoint(2, 22039), agent)
