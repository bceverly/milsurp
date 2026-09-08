"""The WooCommerce Store API base class.

There is no markup to fixture here: the shop publishes JSON, so these describe
the document WooCommerce actually returns. The field shapes are from live
responses on 7 September 2026.
"""

from __future__ import annotations

import json

import pytest
import responses

from app.scrapers import ScrapeContext
from app.scrapers.base import ScrapeError
from app.scrapers.woo_store_api import (
    PAGE_SIZE,
    WooStoreApiScraper,
    html_to_text,
    is_sold,
    price_now,
)

SHOP = "https://shop.test"


def product(
    product_id: int,
    name: str = "Mauser K98k Rifle, 8mm, Exc, Used.",
    *,
    price: str = "82995",
    minor_unit: int = 2,
    in_stock: bool = True,
    backorder: bool = False,
    images: int = 2,
    description: str = "<p>A <strong>fine</strong> example.</p>",
    categories: list[str] | None = None,
) -> dict:
    return {
        "id": product_id,
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "permalink": f"{SHOP}/product/{product_id}/",
        "description": description,
        "short_description": "",
        "sku": "25-2929xq",
        "prices": {
            "price": price,
            "regular_price": price,
            "sale_price": price,
            "currency_code": "USD",
            "currency_symbol": "$",
            "currency_minor_unit": minor_unit,
        },
        "is_in_stock": in_stock,
        "is_on_backorder": backorder,
        "categories": [{"id": 1, "name": n} for n in (categories or ["Military Mausers"])],
        "images": [
            {"id": n, "src": f"{SHOP}/wp-content/uploads/photo{n}.jpg"}
            for n in range(1, images + 1)
        ],
    }


class Shop(WooStoreApiScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    sources = ({"category": "Military Mausers", "id": 3689},)


def page_url(page: int, category: int | None = 3689) -> str:
    query = f"per_page={PAGE_SIZE}&page={page}&orderby=date&order=desc"
    if category is not None:
        query += f"&category={category}"
    return f"{SHOP}/wp-json/wc/store/v1/products?{query}"


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestMoneyArrivesInMinorUnits:
    """The one field that would be plausible while catastrophically wrong.

    ``{"price": "82995", "currency_minor_unit": 2}`` is $829.95. Read as a
    float it is eighty-two thousand, and it would sit unremarked among the
    four-figure listings around it.
    """

    def test_the_scale_is_applied(self):
        assert price_now(product(1, price="82995")) == 829.95

    def test_a_shop_in_whole_units_is_not_divided(self):
        assert price_now(product(1, price="830", minor_unit=0)) == 830.0

    def test_three_decimal_places(self):
        assert price_now(product(1, price="829950", minor_unit=3)) == 829.95

    @pytest.mark.parametrize("prices", [None, {}, {"price": None}, {"price": ""}])
    def test_a_missing_price_is_none_rather_than_zero(self, prices):
        """Zero would read as free; None reads as "call for price"."""
        raw = product(1)
        raw["prices"] = prices
        assert price_now(raw) is None

    def test_and_so_is_nonsense(self):
        raw = product(1)
        raw["prices"]["price"] = "on request"
        assert price_now(raw) is None


class TestStock:
    def test_out_of_stock_is_sold(self):
        """On a dealer of one-off collectibles, gone is gone."""
        assert is_sold(product(1, in_stock=False)) is True

    def test_but_a_backorder_is_not(self):
        """They will still take money for it."""
        assert is_sold(product(1, in_stock=False, backorder=True)) is False

    def test_in_stock_is_not_sold(self):
        assert is_sold(product(1)) is False


class TestOneProduct:
    def parse(self, raw: dict, label: str = "Military Mausers"):
        return Shop().item_from_product(raw, label)

    def test_the_shops_own_id_is_the_key(self):
        assert self.parse(product(504802)).external_key == "woo-504802"

    def test_which_survives_a_rename(self):
        before = self.parse(product(42, "Mauser K98k"))
        after = self.parse(product(42, "Mauser K98k, Exc, Used."))
        assert before.external_key == after.external_key
        assert before.title != after.title

    def test_the_whole_record_arrives_at_once(self):
        """The point of this platform: no second request per listing."""
        item = self.parse(product(42, images=9))
        assert item.price == 829.95
        assert len(item.image_urls) == 9
        assert item.description == "A fine example."
        assert item.images_are_complete is True

    def test_the_name_is_unescaped(self):
        """WooCommerce writes typographic characters as entities: a 2&#8243;
        barrel is a 2″ barrel, and the raw entity is not a title."""
        item = self.parse(product(1, "Colt Agent Revolver, 38 Special, 2&#8243; Barrel"))
        assert "&#8243;" not in item.title
        assert "2″ Barrel" in item.title

    def test_the_section_label_wins_over_the_shops_own_category(self):
        item = self.parse(product(1, categories=["Handguns"]), label="Collector's Corner")
        assert item.category == "Collector's Corner"

    def test_and_the_shops_category_is_the_fallback(self):
        item = self.parse(product(1, categories=["Handguns"]), label="")
        assert item.category == "Handguns"

    @pytest.mark.parametrize("missing", ["id", "permalink", "name"])
    def test_a_product_missing_what_identifies_it_is_skipped(self, missing):
        raw = product(1)
        raw[missing] = None
        assert self.parse(raw) is None


class TestTheWalk:
    @responses.activate
    def test_a_short_page_ends_the_section(self, ctx):
        responses.add(responses.GET, page_url(1), body=json.dumps([product(n) for n in range(3)]))
        items = list(Shop().scrape(ctx))
        assert len(items) == 3
        assert len(responses.calls) == 1

    @responses.activate
    def test_a_full_page_is_followed(self, ctx):
        responses.add(
            responses.GET,
            page_url(1),
            body=json.dumps([product(n) for n in range(PAGE_SIZE)]),
        )
        responses.add(responses.GET, page_url(2), body=json.dumps([product(9001)]))
        assert len(list(Shop().scrape(ctx))) == PAGE_SIZE + 1

    @responses.activate
    def test_one_product_in_two_sections_arrives_once(self, ctx):
        """WooCommerce categories nest, so a rifle in "Collector's Corner" is
        usually also in a child of it."""

        class TwoSections(Shop):
            sources = (
                {"category": "Collector's Corner", "id": 3662},
                {"category": "Military & Surplus", "id": 3686},
            )

        responses.add(responses.GET, page_url(1, 3662), body=json.dumps([product(1), product(2)]))
        responses.add(responses.GET, page_url(1, 3686), body=json.dumps([product(2)]))
        items = list(TwoSections().scrape(ctx))
        assert [i.external_key for i in items] == ["woo-1", "woo-2"]

    @responses.activate
    def test_an_error_body_is_a_scrape_failure_not_a_crash(self, ctx):
        """A shop with the endpoint switched off answers with an object, and
        behind a challenge with an HTML interstitial."""
        responses.add(
            responses.GET,
            page_url(1),
            body=json.dumps({"code": "rest_no_route", "message": "No route was found."}),
        )
        with pytest.raises(ScrapeError, match="No route was found"):
            list(Shop().scrape(ctx))

    @responses.activate
    def test_html_where_json_was_expected_is_too(self, ctx):
        responses.add(responses.GET, page_url(1), body="<!DOCTYPE html><title>Just a moment…")
        with pytest.raises(ScrapeError, match="expected JSON"):
            list(Shop().scrape(ctx))

    @responses.activate
    def test_a_later_page_failing_keeps_what_was_read(self, ctx):
        """The pages already read are worth keeping; only the first is fatal."""
        responses.add(
            responses.GET,
            page_url(1),
            body=json.dumps([product(n) for n in range(PAGE_SIZE)]),
        )
        responses.add(responses.GET, page_url(2), status=500)
        assert len(list(Shop().scrape(ctx))) == PAGE_SIZE


class TestDescriptions:
    def test_markup_is_flattened_to_prose(self):
        assert html_to_text("<p>Hello <b>there</b></p>") == "Hello there"

    def test_nothing_is_none_rather_than_empty(self):
        assert html_to_text("") is None
        assert html_to_text(None) is None
