"""The Shopify base class.

Unlike the HTML scrapers there is no markup to fixture here: the shop publishes
JSON, so the tests describe the document Shopify actually returns. The fields
asserted are the ones taken from live responses on 7 September 2026.
"""

from __future__ import annotations

import json

import pytest
import responses

from app.scrapers import ScrapeContext
from app.scrapers.base import ScrapeError
from app.scrapers.shopify import (
    PAGE_SIZE,
    ShopifyScraper,
    html_to_text,
    is_sold_out,
    original_image,
    price_now,
)

SHOP = "https://shop.test"
COLLECTION = f"{SHOP}/collections/antiques"
CDN = "https://cdn.shopify.com/s/files/1/1524/1342/files"


def product(
    product_id: int,
    title: str = "Original Martini-Henry Rifle",
    *,
    price: str = "1250.00",
    available: bool = True,
    images: int = 2,
    body: str = "<p>Original Item: <strong>Only One Available</strong>.</p>",
    variants: list[dict] | None = None,
) -> dict:
    return {
        "id": product_id,
        "handle": title.lower().replace(" ", "-"),
        "title": title,
        "body_html": body,
        "vendor": "Original Items",
        "variants": variants
        or [{"id": 1, "sku": "ONJR26", "price": price, "available": available}],
        "images": [
            {"id": n, "position": n, "src": f"{CDN}/photo{n}.jpg?v=1788544991&width=500"}
            for n in range(1, images + 1)
        ],
    }


def feed(products: list[dict]) -> str:
    return json.dumps({"products": products})


class Shop(ShopifyScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    sources = ({"category": "Antiques", "url": COLLECTION},)


def page_url(page: int) -> str:
    return f"{COLLECTION}/products.json?limit={PAGE_SIZE}&page={page}"


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestOneProduct:
    def parse(self, raw: dict):
        return Shop().item_from_product(raw, COLLECTION, "Antiques")

    def test_the_shops_own_id_is_the_key(self):
        assert self.parse(product(8269387497541)).external_key == "shopify-8269387497541"

    def test_which_survives_a_rename(self):
        """A handle changes when a title is edited; the id does not. On a
        handle key that reads as one listing de-listed and another appearing."""
        before = self.parse(product(42, "Martini Henry"))
        after = self.parse(product(42, "Original Martini-Henry Mk II"))
        assert before.external_key == after.external_key
        assert before.url != after.url

    def test_the_url_points_at_the_product_not_the_collection(self):
        item = self.parse(product(42, "Martini Henry"))
        assert item.url == f"{SHOP}/products/martini-henry"

    def test_the_whole_record_arrives_at_once(self):
        """The point of this platform: no second request per listing."""
        item = self.parse(product(42, images=24))
        assert item.price == 1250.00
        assert item.extra["sku"] == "ONJR26"
        assert len(item.image_urls) == 24
        assert item.description.startswith("Original Item: Only One Available")
        assert item.images_are_complete is True

    def test_a_product_missing_its_identity_is_skipped(self):
        assert self.parse({"id": 1, "title": "No handle"}) is None
        assert self.parse({"handle": "no-id", "title": "x"}) is None
        assert self.parse({"id": 1, "handle": "h", "title": "  "}) is None


class TestPrice:
    def test_the_plain_case(self):
        assert price_now(product(1, price="2395.00")) == 2395.00

    def test_several_variants_report_the_cheapest(self):
        """Which is the number a shop shows as "from $X". A firearm is one
        variant; ammunition is not."""
        raw = product(
            1,
            variants=[
                {"price": "38.99", "available": True},
                {"price": "21.50", "available": True},
            ],
        )
        assert price_now(raw) == 21.50

    def test_a_sold_listing_keeps_its_price(self):
        """ "Sold" and "call for price" are different things, and a listing with
        no price reads as the second."""
        raw = product(1, price="900.00", available=False)
        assert price_now(raw) == 900.00
        assert is_sold_out(raw) is True

    def test_sold_out_needs_every_variant_to_be_unavailable(self):
        raw = product(
            1,
            variants=[{"price": "1", "available": False}, {"price": "2", "available": True}],
        )
        assert is_sold_out(raw) is False

    def test_a_product_with_no_variants_is_not_assumed_sold(self):
        """A shape this code has not seen. Guessing "sold" would quietly retire
        a live listing."""
        assert is_sold_out({"id": 1, "variants": []}) is False

    def test_an_unparseable_price_is_no_price(self):
        assert price_now({"variants": [{"price": "call"}]}) is None


class TestImages:
    def test_the_size_is_stripped_so_the_original_is_asked_for(self):
        assert original_image(f"{CDN}/a.jpg?v=17885&width=500") == f"{CDN}/a.jpg?v=17885"

    def test_but_the_version_is_kept(self):
        """It identifies that version of the photograph. Dropping it would make
        a re-uploaded image look like the same file."""
        assert "v=17885" in original_image(f"{CDN}/a.jpg?v=17885&width=500&height=500")

    def test_a_url_with_no_query_is_untouched(self):
        assert original_image(f"{CDN}/a.jpg") == f"{CDN}/a.jpg"

    def test_a_url_that_is_only_a_size_loses_its_question_mark(self):
        assert original_image(f"{CDN}/a.jpg?width=500") == f"{CDN}/a.jpg"

    def test_the_gallery_keeps_the_shops_own_order(self):
        raw = product(1, images=3)
        raw["images"].reverse()
        item = Shop().item_from_product(raw, COLLECTION, "")
        assert item.image_urls == [f"{CDN}/photo{n}.jpg?v=1788544991" for n in (1, 2, 3)]


class TestDescription:
    def test_markup_becomes_prose(self):
        assert html_to_text("<p>An <em>original</em> item.</p>") == "An original item."

    def test_an_empty_body_is_no_description(self):
        assert html_to_text("") is None
        assert html_to_text(None) is None
        assert html_to_text("<p> </p>") is None


class TestWalkingTheCollection:
    @responses.activate
    def test_a_short_page_ends_the_collection(self, ctx):
        responses.add(responses.GET, page_url(1), body=feed([product(1), product(2)]))

        items = list(Shop().scrape(ctx))

        assert [item.external_key for item in items] == ["shopify-1", "shopify-2"]
        # One request, because two products is fewer than a full page.
        assert len(responses.calls) == 1

    @responses.activate
    def test_a_full_page_asks_for_another(self, ctx):
        responses.add(responses.GET, page_url(1), body=feed([product(n) for n in range(PAGE_SIZE)]))
        responses.add(responses.GET, page_url(2), body=feed([product(9001)]))

        items = list(Shop().scrape(ctx))

        assert len(items) == PAGE_SIZE + 1

    @responses.activate
    def test_an_empty_page_ends_it_too(self, ctx):
        responses.add(responses.GET, page_url(1), body=feed([product(n) for n in range(PAGE_SIZE)]))
        responses.add(responses.GET, page_url(2), body=feed([]))

        assert len(list(Shop().scrape(ctx))) == PAGE_SIZE

    @responses.activate
    def test_a_product_in_two_collections_is_read_once(self, ctx):
        class TwoSections(Shop):
            sources = (
                {"category": "Antiques", "url": COLLECTION},
                {"category": "Long guns", "url": f"{SHOP}/collections/long-guns"},
            )

        responses.add(responses.GET, page_url(1), body=feed([product(7)]))
        responses.add(
            responses.GET,
            f"{SHOP}/collections/long-guns/products.json?limit={PAGE_SIZE}&page=1",
            body=feed([product(7)]),
        )

        items = list(TwoSections().scrape(ctx))

        assert len(items) == 1
        # Filed under the collection that claimed it first.
        assert items[0].category == "Antiques"

    @responses.activate
    def test_html_where_json_was_expected_is_a_scrape_error(self, ctx):
        """What a shop that has turned the endpoint off actually returns."""
        responses.add(responses.GET, page_url(1), body="<html><body>Not found</body></html>")

        with pytest.raises(ScrapeError, match="expected JSON"):
            list(Shop().scrape(ctx))

    @responses.activate
    def test_a_later_page_that_fails_keeps_the_earlier_ones(self, ctx):
        responses.add(responses.GET, page_url(1), body=feed([product(n) for n in range(PAGE_SIZE)]))
        responses.add(responses.GET, page_url(2), status=500)

        items = list(Shop().scrape(ctx))

        assert len(items) == PAGE_SIZE
        assert any("Stopping this section" in warning for warning in ctx.warnings)

    @responses.activate
    def test_but_a_first_page_that_fails_is_a_failure(self, ctx):
        responses.add(responses.GET, page_url(1), status=500)

        with pytest.raises(ScrapeError):
            list(Shop().scrape(ctx))

    @responses.activate
    def test_a_shop_that_disallows_query_strings_stops_rather_than_fails(self, app_config):
        """The rule that ruled out the WooCommerce Store API, and this whole
        module depends on a query string."""
        import dataclasses

        config = dataclasses.replace(
            app_config, scraping=dataclasses.replace(app_config.scraping, obey_robots=True)
        )
        responses.add(
            responses.GET,
            f"{SHOP}/robots.txt",
            body="User-agent: *\nDisallow: /*?*",
            content_type="text/plain",
        )

        context = ScrapeContext(config)
        try:
            items = list(Shop().scrape(context))
        finally:
            context.close()

        assert items == []
        assert any("robots.txt disallows" in warning for warning in context.warnings)


class TestTheShops:
    def test_ima_usa_leaves_the_parts_and_holsters_alone(self):
        from app.scrapers.ima_usa import ImaUsaScraper

        urls = [source["url"] for source in ImaUsaScraper.sources]
        assert not any(url.endswith("/collections/all") for url in urls)
        assert not any("parts" in url or "holsters" in url for url in urls)

    def test_centerfire_takes_only_its_surplus_sections(self):
        """Their biggest collections are 455 AR-15 rifles and 288 AR-15
        pistols, and their unscoped feed opens with hunting ammunition."""
        from app.scrapers.centerfire_systems import CenterfireSystemsScraper

        urls = [source["url"] for source in CenterfireSystemsScraper.sources]
        assert urls
        assert not any("ar-15" in url or "ak-" in url for url in urls)
        assert all("/collections/" in url for url in urls)

    def test_neither_needs_a_browser(self):
        from app.scrapers.centerfire_systems import CenterfireSystemsScraper
        from app.scrapers.ima_usa import ImaUsaScraper

        assert ImaUsaScraper.requires_browser is False
        assert CenterfireSystemsScraper.requires_browser is False
