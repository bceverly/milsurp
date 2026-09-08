"""The Searchanise base class.

There is no catalog markup to fixture: a Searchanise shop's category pages are
empty and the products come from JSON. The field shapes here are SARCO's, from
live responses on 8 September 2026 -- including the ones that look like stock
levels and are not.
"""

from __future__ import annotations

import json

import pytest
import responses

from app.scrapers import ScrapeContext
from app.scrapers.base import ScrapeError
from app.scrapers.searchanise import (
    API,
    PAGE_SIZE,
    SearchaniseScraper,
    full_size,
    html_to_text,
    price_now,
)

SHOP = "https://shop.test"
KEY = "7I8v4I9z4m"
CDN = "https://cdn11.bigcommerce.com/s-68ehg8csas/products"


def image(n: int, size: str = "386.513") -> str:
    return f"{CDN}/8645/images/{n}/gun012a__51865.1755106068.{size}.jpg?c=2"


def product(
    product_id: int,
    title: str = "Astra modelo 400 9mm Largo Pistol with Wood Grips",
    *,
    price: str = "349.9500",
    list_price: str = "0.0000",
    sale_price: str = "0",
    quantity: str = "1",
    inventory_level: str = "1",
    images: int = 2,
    description: str = "Astra 400 9mm largo pistol. Bores are dark but have plenty of ...",
    product_code: str = "GUN023",
) -> dict:
    return {
        "product_id": str(product_id),
        "title": title,
        "link": f"{SHOP}/{title.lower().replace(' ', '-')}-{product_id}/",
        "price": price,
        "list_price": list_price,
        "sale_price": sale_price,
        "quantity": quantity,
        "inventory_level": inventory_level,
        "product_code": product_code,
        "description": description,
        "image_link": image(1),
        "bigcommerce_images": [image(n) for n in range(1, images + 1)],
    }


def page(products: list[dict], total: int | None = None) -> str:
    return json.dumps(
        {
            "totalItems": len(products) if total is None else total,
            "startIndex": 0,
            "itemsPerPage": PAGE_SIZE,
            "currentItemCount": len(products),
            "items": products,
        }
    )


class Shop(SearchaniseScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    api_key = KEY
    sources = ({"category": "Shop All Firearms"},)


class DetailedShop(Shop):
    detail_description_selectors = ("#tab-description",)


def page_url(start: int = 0, category: str = "Shop All Firearms") -> str:
    return Shop().endpoint(start, category)


DETAIL_PAGE = """
<html><body>
  <div class="productView-description" itemprop="description">
    <ul class="tabs"><li><a class="tab-title" href="#tab-description">Description</a></li></ul>
    <div id="tab-description">
      <p>Astra 400 9mm largo pistol. Bores are dark but have plenty of life left.</p>
      <p>The Astra modelo 400 was a Spanish service pistol.</p>
    </div>
  </div>
</body></html>
"""


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)


@pytest.fixture
def no_global_cooldown(monkeypatch):
    """Neutralize the shared "leave this host alone" register.

    These tests drive a host to its refusal ceiling on purpose, to exercise the
    escalation *inside* one context. Reaching that ceiling is also what
    publishes a cooldown every other process obeys -- correct behavior, and a
    different subject. Tested separately in test_cooldown.py.
    """
    monkeypatch.setattr("app.scrapers.base.cooldown.paused_for", lambda _url: 0.0)
    monkeypatch.setattr("app.scrapers.base.cooldown.refused", lambda *_a, **_k: 0.0)


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestTheEndpointIsOnSomebodyElsesHost:
    """Which is the point, and the thing to get wrong quietly.

    The shop is at shop.test and the catalog is at searchserverapi.com, so it
    is that host's robots.txt that governs the request -- and it publishes an
    empty Disallow. A walk that asked the shop's robots.txt about its own URL
    would be asking the wrong file about the wrong host.
    """

    def test_the_request_goes_to_the_search_api(self):
        assert page_url().startswith(API)

    def test_carrying_the_shops_key(self):
        assert f"api_key={KEY}" in page_url()

    def test_and_the_category_it_was_asked_for(self):
        assert "restrictBy" in page_url()
        assert "Shop+All+Firearms" in page_url()

    def test_a_section_with_no_category_asks_for_everything(self):
        assert "restrictBy" not in page_url(category="")

    def test_paging_is_an_offset_not_a_page_number(self):
        assert "startIndex=0" in page_url(0)
        assert f"startIndex={PAGE_SIZE}" in page_url(PAGE_SIZE)


class TestMoney:
    """``price`` is the live figure; the other two are decoration.

    On a reduced item ``price`` already equals ``sale_price`` and
    ``list_price`` holds what it was. Reading ``list_price`` would hide every
    discount, which is the one event this application exists to notice.
    """

    def test_the_asking_price_is_read(self):
        assert price_now(product(1, price="349.9500")) == 349.95

    def test_a_sale_reports_the_reduced_price_not_the_old_one(self):
        raw = product(1, price="75.0000", list_price="99.0000", sale_price="75")
        assert price_now(raw) == 75.0

    def test_a_full_price_item_is_not_reported_as_free(self):
        """``sale_price`` is the string "0" on nine listings in ten."""
        assert price_now(product(1, price="200.0000", sale_price="0")) == 200.0

    @pytest.mark.parametrize("value", [None, "", "0", "0.0000"])
    def test_no_price_is_none_rather_than_zero(self, value):
        """Zero would read as free; None reads as "call for price"."""
        raw = product(1)
        raw["price"] = value
        assert price_now(raw) is None

    def test_and_so_is_nonsense(self):
        raw = product(1)
        raw["price"] = "call us"
        assert price_now(raw) is None


class TestNeitherStockFieldMeansWhatItLooksLike:
    """The measurement that stopped a plausible bug.

    ``quantity`` reads like a count and is 0 on 157 of SARCO's 509 firearms --
    including an Astra 400 whose product page has a working Add to Cart.
    ``inventory_level`` reads like the other half of the answer and is an empty
    string on 151 of them, and was never once observed as zero. Believing
    either would have marked a third of the catalog sold on the first scan.
    """

    def parse(self, raw: dict):
        return Shop().item_from_product(raw, "Shop All Firearms")

    def test_a_quantity_of_zero_does_not_mark_a_live_pistol_sold(self):
        assert self.parse(product(1, quantity="0")).is_sold is False

    def test_nor_does_an_empty_inventory_level(self):
        assert self.parse(product(1, inventory_level="")).is_sold is False

    def test_nothing_arrives_sold(self):
        """A sold listing stops arriving; the scan's de-listing handles that."""
        assert self.parse(product(1, quantity="0", inventory_level="0")).is_sold is False


class TestImages:
    """The size lives in the filename, not the path.

    ``…gun012a__51865.1755106068.386.513.jpg`` is a 30KB thumbnail of a 224KB
    photograph, and the two numbers before the extension are the only
    difference. This is not the ``/images/stencil/500x659/`` form the
    BigCommerce scraper rewrites -- the same CDN serves both.
    """

    def test_the_thumbnail_becomes_the_photograph(self):
        assert full_size(image(1)) == image(1, "1280.1280")

    def test_rewriting_a_full_size_url_leaves_it_alone(self):
        """Some galleries already end with a 1280 copy of their first photo."""
        assert full_size(image(1, "1280.1280")) == image(1, "1280.1280")

    def test_a_url_with_no_size_in_it_is_untouched(self):
        """Variant swatches live under a different path and are already whole."""
        swatch = f"{CDN[:-9]}/product_images/attribute_rule_images/1688_source_1776086303.jpg"
        assert full_size(swatch) == swatch

    def test_the_gallery_is_taken_whole(self):
        item = Shop().item_from_product(product(1, images=5), "")
        assert len(item.image_urls) == 5
        assert item.images_are_complete is True
        assert all("1280.1280" in url for url in item.image_urls)

    def test_a_duplicated_first_photo_lands_once(self):
        raw = product(1, images=2)
        raw["bigcommerce_images"].append(image(1, "1280.1280"))
        assert len(Shop().item_from_product(raw, "").image_urls) == 2

    def test_a_product_with_only_a_thumbnail_still_gets_it(self):
        raw = product(1)
        raw["bigcommerce_images"] = []
        assert Shop().item_from_product(raw, "").image_urls == [image(1, "1280.1280")]


class TestOneProduct:
    def parse(self, raw: dict, label: str = "Shop All Firearms"):
        return Shop().item_from_product(raw, label)

    def test_the_key_is_the_bigcommerce_one(self):
        """`bc-` and the shop's own product id -- the same key
        app.scrapers.bigcommerce builds from `data-entity-id`, so a shop that
        went back to server-rendered pages would keep its listings."""
        assert self.parse(product(8645)).external_key == "bc-8645"

    def test_which_survives_a_rename(self):
        before = self.parse(product(42, "Astra 400"))
        after = self.parse(product(42, "Astra modelo 400 9mm Largo"))
        assert before.external_key == after.external_key
        assert before.title != after.title

    def test_the_sku_is_kept(self):
        assert self.parse(product(1, product_code="GUN023")).extra["sku"] == "GUN023"

    def test_a_product_with_no_sku_carries_no_empty_one(self):
        assert self.parse(product(1, product_code="")).extra == {}

    def test_the_section_label_is_the_category(self):
        assert self.parse(product(1), "Exciting New Firearms").category == "Exciting New Firearms"

    @pytest.mark.parametrize("missing", ["product_id", "link", "title"])
    def test_a_product_missing_what_identifies_it_is_skipped(self, missing):
        raw = product(1)
        raw[missing] = None
        assert self.parse(raw) is None


class TestTheWalk:
    @responses.activate
    def test_a_short_page_ends_the_section(self, ctx):
        responses.add(responses.GET, API, body=page([product(n) for n in range(3)]))
        items = list(Shop().scrape(ctx))
        assert len(items) == 3
        assert len(responses.calls) == 1

    @responses.activate
    def test_a_full_page_is_followed(self, ctx):
        responses.add(responses.GET, API, body=page([product(n) for n in range(PAGE_SIZE)], 251))
        responses.add(responses.GET, API, body=page([product(9001)], 251))
        assert len(list(Shop().scrape(ctx))) == PAGE_SIZE + 1

    @responses.activate
    def test_one_product_in_two_sections_arrives_once(self, ctx):
        """A shop's "new arrivals" is a slice of its catalog, not a separate one."""

        class TwoSections(Shop):
            sources = (
                {"category": "Shop All Firearms"},
                {"category": "Exciting New Firearms"},
            )

        responses.add(responses.GET, API, body=page([product(1), product(2)]))
        responses.add(responses.GET, API, body=page([product(2), product(3)]))
        items = list(TwoSections().scrape(ctx))
        assert [i.external_key for i in items] == ["bc-1", "bc-2", "bc-3"]

    @responses.activate
    def test_a_category_that_matches_nothing_says_so(self, ctx):
        """The pipe trap: Searchanise splits `restrictBy[categories]` on `|`,
        so "Rifles | Military Surplus Guns" answers 200 with an empty list
        rather than erroring, and a silent zero looks like an empty shop."""
        responses.add(responses.GET, API, body=page([]))
        assert list(Shop().scrape(ctx)) == []
        assert any("'|'" in warning for warning in ctx.warnings)

    @responses.activate
    def test_html_where_json_was_expected_is_a_scrape_failure(self, ctx):
        responses.add(responses.GET, API, body="<!DOCTYPE html><title>Just a moment…")
        with pytest.raises(ScrapeError, match="expected JSON"):
            list(Shop().scrape(ctx))

    @responses.activate
    def test_a_bare_list_is_too(self, ctx):
        responses.add(responses.GET, API, body="[]")
        with pytest.raises(ScrapeError, match="expected an object"):
            list(Shop().scrape(ctx))

    @responses.activate
    def test_a_later_page_failing_keeps_what_was_read(self, ctx):
        responses.add(responses.GET, API, body=page([product(n) for n in range(PAGE_SIZE)], 251))
        responses.add(responses.GET, API, status=500)
        assert len(list(Shop().scrape(ctx))) == PAGE_SIZE
        assert ctx.warnings


class TestExcludedSections:
    """A shop whose "firearms" tree includes bare frames and stripped
    receivers. Those are components, and the standing rule here is that the
    only non-firearm category worth ingesting is a parts *kit*.

    Suppression rather than filtering, because the exclusion has to outrank the
    section that would otherwise claim the listing: fifteen of SARCO's fifty
    frames are also filed under "Pistols", and "Pistols" is read first.
    """

    class Excluding(Shop):
        sources = ({"category": "Pistols"},)
        exclude_categories = ("Frames",)

    @responses.activate
    def test_an_excluded_product_never_arrives(self, ctx):
        responses.add(responses.GET, API, body=page([product(7)]))  # Frames
        responses.add(responses.GET, API, body=page([product(7), product(8)]))  # Pistols
        items = list(self.Excluding().scrape(ctx))
        assert [item.external_key for item in items] == ["bc-8"]

    @responses.activate
    def test_the_excluded_section_is_read_before_any_other(self, ctx):
        """Reading it afterwards would be too late: the section that claims the
        listing has already yielded it."""
        responses.add(responses.GET, API, body=page([product(7)]))
        responses.add(responses.GET, API, body=page([product(7)]))
        list(self.Excluding().scrape(ctx))
        first = responses.calls[0].request.url
        assert "Frames" in first

    @responses.activate
    def test_an_excluded_listing_costs_no_product_page(self, ctx):
        class Both(self.Excluding):
            detail_description_selectors = ("#tab-description",)

        responses.add(responses.GET, API, body=page([product(7)]))
        responses.add(responses.GET, API, body=page([product(7)]))
        list(Both().scrape(ctx))
        assert all(API in call.request.url for call in responses.calls)

    @responses.activate
    def test_a_section_that_cannot_be_read_warns_rather_than_failing(self, ctx, no_global_cooldown):
        """Failing here lets some components through to be filed as
        accessories, which is untidy. Failing the scan costs the whole
        catalog, which is worse."""
        shop = self.Excluding()
        responses.add(responses.GET, shop.endpoint(0, "Frames"), status=500)
        responses.add(
            responses.GET, shop.endpoint(0, "Pistols"), body=page([product(7), product(8)])
        )

        items = list(shop.scrape(ctx))

        assert [item.external_key for item in items] == ["bc-7", "bc-8"]
        assert any("will be scanned like any other" in w for w in ctx.warnings)


class TestTheDescriptionComesFromTheProductPage:
    """Searchanise indexes 200 characters and stops.

    508 of SARCO's 509 firearms come back cut off mid-sentence, and the
    description is the half of a listing this application reads most closely --
    the caliber, the condition, the import marks. So a shop that says where to
    look gets the real one from its own page.
    """

    @responses.activate
    def test_the_truncated_one_is_replaced(self, ctx):
        raw = product(1)
        responses.add(responses.GET, API, body=page([raw]))
        responses.add(responses.GET, raw["link"], body=DETAIL_PAGE)
        item = next(iter(DetailedShop().scrape(ctx)))
        assert item.description.endswith("Spanish service pistol.")
        assert "..." not in item.description

    @responses.activate
    def test_the_tab_body_is_read_not_the_wrapper(self, ctx):
        """`.productView-description` opens with the literal word "Description"
        from the tab label above it."""
        raw = product(1)
        responses.add(responses.GET, API, body=page([raw]))
        responses.add(responses.GET, raw["link"], body=DETAIL_PAGE)
        item = next(iter(DetailedShop().scrape(ctx)))
        assert not item.description.startswith("Description")

    @responses.activate
    def test_a_shop_that_names_no_selectors_fetches_no_product_pages(self, ctx):
        responses.add(responses.GET, API, body=page([product(1)]))
        item = next(iter(Shop().scrape(ctx)))
        assert item.description.endswith("...")
        assert len(responses.calls) == 1

    @responses.activate
    def test_a_listing_already_described_is_not_fetched_again(self, app_config):
        """Bounded by ctx.needs_detail: once per listing ever, not per scan."""
        ctx = ScrapeContext(app_config, needs_detail=lambda _key: False)
        responses.add(responses.GET, API, body=page([product(1)]))
        item = next(iter(DetailedShop().scrape(ctx)))
        assert len(responses.calls) == 1
        assert item.description.endswith("...")
        ctx.close()

    @responses.activate
    def test_an_unreadable_product_page_costs_the_listing_nothing_else(self, ctx):
        raw = product(1)
        responses.add(responses.GET, API, body=page([raw]))
        responses.add(responses.GET, raw["link"], status=500)
        item = next(iter(DetailedShop().scrape(ctx)))
        assert item.price == 349.95
        assert item.image_urls
        assert item.description.endswith("...")
        assert ctx.warnings

    @responses.activate
    def test_a_shop_that_refuses_every_product_page_stops_being_asked(
        self, ctx, no_global_cooldown
    ):
        """Otherwise the whole catalog gets walked one pointless request at a
        time, each one paying the full retry-and-backoff bill -- an hour spent
        learning the same thing five hundred times."""
        wanted = DetailedShop.MAX_DETAIL_FAILURES
        products = [product(n) for n in range(wanted + 4)]
        responses.add(responses.GET, API, body=page(products))
        for raw in products:
            responses.add(responses.GET, raw["link"], status=429)

        items = list(DetailedShop().scrape(ctx))

        assert len(items) == wanted + 4
        asked = {call.request.url for call in responses.calls if API not in call.request.url}
        assert len(asked) == wanted
        assert any("from the API only" in warning for warning in ctx.warnings)

    @responses.activate
    def test_one_that_recovers_is_not_given_up_on(self, ctx, no_global_cooldown):
        """The count is failures *in a row*. A shop having a bad minute in the
        middle of a long catalog should not lose the rest of its descriptions."""
        products = [product(n) for n in range(4)]
        responses.add(responses.GET, API, body=page(products))
        responses.add(responses.GET, products[0]["link"], status=429)
        responses.add(responses.GET, products[1]["link"], status=429)
        for raw in products[2:]:
            responses.add(responses.GET, raw["link"], body=DETAIL_PAGE)

        items = list(DetailedShop().scrape(ctx))

        assert [item.description.endswith("...") for item in items] == [
            True,
            True,
            False,
            False,
        ]


class TestDescriptions:
    def test_markup_is_flattened_to_prose(self):
        assert html_to_text("<p>Hello <b>there</b></p>") == "Hello there"

    def test_nothing_is_none_rather_than_empty(self):
        assert html_to_text("") is None
        assert html_to_text(None) is None
