"""The shared WooCommerce machinery.

The pages here are written rather than captured. A saved copy of a real shop's
markup would be someone else's page in the repository, it would be a megabyte,
and it would make these tests a report on what that shop looked like one
afternoon. What is asserted instead is the shape WooCommerce itself renders,
which is the thing the base class is written against.
"""

from __future__ import annotations

import pytest
import responses
from bs4 import BeautifulSoup

from app.scrapers import ScrapeContext
from app.scrapers.collectors_firearms import CollectorsFirearmsScraper
from app.scrapers.woocommerce import (
    WooCommerceScraper,
    full_size,
    price_now,
    same_photograph,
)

SHOP = "https://shop.test"
UPLOADS = f"{SHOP}/wp-content/uploads/2026/09"


def card(
    post_id: int,
    title: str,
    price_html: str = '<span class="woocommerce-Price-amount">$600.00</span>',
    *,
    extra_classes: str = "instock",
    image: str = f"{UPLOADS}/rifle-300x200.jpg",
) -> str:
    slug = title.lower().replace(" ", "-")
    return f"""
    <li class="product type-product post-{post_id} status-publish {extra_classes}
               product_cat-foreign-military-rifles has-post-thumbnail">
      <a href="{SHOP}/product/{slug}/" class="woocommerce-loop-product__link">
        <img src="data:image/svg+xml,placeholder" data-src="{image}" alt="{title}"/>
        <h2 class="woocommerce-loop-product__title">{title}</h2>
        <span class="price">{price_html}</span>
      </a>
      <a href="/product-category/rifles/?add-to-cart={post_id}" class="add_to_cart_button">Add</a>
    </li>
    """


def catalog(cards: str, next_href: str | None = None) -> str:
    nav = f'<a class="next page-numbers" href="{next_href}">→</a>' if next_href else ""
    return f"<html><body><ul class='products columns-4'>{cards}</ul>{nav}</body></html>"


def product_page(title: str, description: str, images: list[str], sku: str = "L-1") -> str:
    gallery = "".join(f'<img src="{url}" class="attachment-full"/>' for url in images)
    return f"""
    <html><body>
      <h1 class="product_title">{title}</h1>
      <div class="summary">
        <p class="price"><span class="woocommerce-Price-amount">$600.00</span></p>
        <div class="product-sku">Item Number: {sku}</div>
      </div>
      <div class="woocommerce-product-gallery">{gallery}</div>
      <div class="single-product-description">{description}</div>
    </body></html>
    """


class Shop(WooCommerceScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    sources = ({"category": "Rifles", "url": f"{SHOP}/product-category/rifles/"},)


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestImageUrls:
    def test_a_generated_size_is_stripped_back_to_the_upload(self):
        assert full_size(f"{UPLOADS}/rifle-1024x172.jpg") == f"{UPLOADS}/rifle.jpg"

    def test_a_filename_that_merely_contains_digits_is_left_alone(self):
        assert full_size(f"{UPLOADS}/m1903a3-rifle.jpg") == f"{UPLOADS}/m1903a3-rifle.jpg"

    def test_scaled_and_original_are_one_photograph(self):
        """WordPress stores a large upload twice and galleries link to both."""
        assert same_photograph(f"{UPLOADS}/a-scaled.jpg") == same_photograph(f"{UPLOADS}/a.jpg")

    def test_but_two_different_pictures_are_not(self):
        assert same_photograph(f"{UPLOADS}/a.jpg") != same_photograph(f"{UPLOADS}/b.jpg")


class TestPrice:
    def price_of(self, html: str) -> float | None:
        return price_now(BeautifulSoup(html, "html.parser"))

    def test_a_plain_price(self):
        assert self.price_of('<span class="woocommerce-Price-amount">$1,250.00</span>') == 1250.00

    def test_a_sale_reports_what_is_being_asked(self):
        """The old price first would hide the drop this application watches for."""
        html = (
            '<span class="price">'
            '<del><span class="woocommerce-Price-amount">$600.00</span></del> '
            '<ins><span class="woocommerce-Price-amount">$450.00</span></ins></span>'
        )
        assert self.price_of(html) == 450.00

    def test_a_listing_with_no_price(self):
        assert self.price_of('<span class="price">Call for pricing</span>') is None


class TestReadingACard:
    def parse(self, html: str):
        soup = BeautifulSoup(catalog(html), "html.parser")
        return Shop().item_from_card(
            soup.select_one(Shop.card_selector), f"{SHOP}/product-category/rifles/", "Rifles"
        )

    def test_the_post_id_is_the_key(self):
        """A slug can be edited; the shop's own primary key cannot."""
        assert self.parse(card(1398033, "Mosin Nagant")).external_key == "post-1398033"

    def test_the_title_price_and_link(self):
        item = self.parse(card(1, "Mosin Nagant"))
        assert item.title == "Mosin Nagant"
        assert item.price == 600.00
        assert item.url == f"{SHOP}/product/mosin-nagant/"

    def test_the_add_to_cart_link_is_not_the_product_link(self):
        assert "add-to-cart" not in self.parse(card(1, "Mosin Nagant")).url

    def test_a_lazy_loaded_thumbnail_is_found_behind_its_placeholder(self):
        item = self.parse(card(1, "Mosin Nagant"))
        assert item.image_urls == [f"{UPLOADS}/rifle.jpg"]

    def test_the_catalog_grid_never_claims_to_be_the_gallery(self):
        """Otherwise a re-scan would delete photographs a detail fetch found."""
        assert self.parse(card(1, "Mosin Nagant")).images_are_complete is False

    def test_out_of_stock_is_read_from_the_class_list(self):
        assert self.parse(card(1, "Sold Rifle", extra_classes="outofstock")).is_sold is True

    def test_a_promotional_tile_is_not_a_product(self):
        soup = BeautifulSoup("<li class='product banner'><h2>Sale!</h2></li>", "html.parser")
        assert Shop().item_from_card(soup.select_one("li"), SHOP, "Rifles") is None


class TestWalkingTheCatalog:
    @responses.activate
    def test_it_follows_the_next_link_the_shop_renders(self, ctx):
        """Not a computed page number: the catalog changes while it is read."""
        page_one = catalog(
            card(1, "Rifle One"), next_href=f"{SHOP}/product-category/rifles/page/2/"
        )
        responses.add(responses.GET, f"{SHOP}/product-category/rifles/", body=page_one)
        responses.add(
            responses.GET,
            f"{SHOP}/product-category/rifles/page/2/",
            body=catalog(card(2, "Rifle Two")),
        )
        for slug in ("rifle-one", "rifle-two"):
            responses.add(
                responses.GET,
                f"{SHOP}/product/{slug}/",
                body=product_page(slug, "prose", [f"{UPLOADS}/a.jpg"]),
            )

        items = list(Shop().scrape(ctx))

        assert [item.external_key for item in items] == ["post-1", "post-2"]

    @responses.activate
    def test_a_next_link_pointing_backwards_does_not_loop(self, ctx):
        here = f"{SHOP}/product-category/rifles/"
        responses.add(responses.GET, here, body=catalog(card(1, "Rifle"), next_href=here))
        responses.add(responses.GET, f"{SHOP}/product/rifle/", body=product_page("Rifle", "p", []))

        assert len(list(Shop().scrape(ctx))) == 1

    @responses.activate
    def test_a_listing_in_two_sections_is_yielded_once(self, ctx):
        class TwoSections(Shop):
            sources = (
                {"category": "Rifles", "url": f"{SHOP}/product-category/rifles/"},
                {"category": "Surplus", "url": f"{SHOP}/product-category/surplus/"},
            )

        body = catalog(card(1, "Rifle"))
        responses.add(responses.GET, f"{SHOP}/product-category/rifles/", body=body)
        responses.add(responses.GET, f"{SHOP}/product-category/surplus/", body=body)
        responses.add(responses.GET, f"{SHOP}/product/rifle/", body=product_page("Rifle", "p", []))

        assert len(list(TwoSections().scrape(ctx))) == 1


class TestTheProductPage:
    @responses.activate
    def test_it_supplies_the_description_and_the_gallery(self, ctx):
        responses.add(
            responses.GET, f"{SHOP}/product-category/rifles/", body=catalog(card(1, "Rifle"))
        )
        responses.add(
            responses.GET,
            f"{SHOP}/product/rifle/",
            body=product_page(
                "WWII Russian M91/30",
                "Serial no. 91303048. Bore is good.",
                [f"{UPLOADS}/a-scaled.jpg", f"{UPLOADS}/a.jpg", f"{UPLOADS}/b-1024x768.jpg"],
            ),
        )

        item = next(iter(Shop().scrape(ctx)))

        assert item.title == "WWII Russian M91/30"
        assert "Bore is good" in item.description
        assert item.extra["sku"] == "L-1"
        # Three URLs, two photographs: the scaled copy and the original are one.
        assert item.image_urls == [f"{UPLOADS}/a-scaled.jpg", f"{UPLOADS}/b.jpg"]
        assert item.images_are_complete is True

    @responses.activate
    def test_a_listing_already_held_costs_no_request(self, ctx_factory):
        """One request per listing is the expensive half of a scan."""
        responses.add(
            responses.GET, f"{SHOP}/product-category/rifles/", body=catalog(card(1, "Rifle"))
        )
        context = ctx_factory(needs_detail=lambda _key: False)
        try:
            items = list(Shop().scrape(context))
        finally:
            context.close()

        assert len(items) == 1
        assert items[0].images_are_complete is False
        assert [call.request.url for call in responses.calls] == [
            f"{SHOP}/product-category/rifles/"
        ]


class TestCollectorsFirearms:
    def test_it_reads_only_the_military_rifle_sections(self):
        """They are a general dealer with 207,000 products."""
        urls = [source["url"] for source in CollectorsFirearmsScraper.sources]
        assert all("military-rifles" in url for url in urls)

    def test_it_keeps_the_stock_selectors_behind_its_own(self):
        """If the theme reverts, the WooCommerce defaults still answer."""
        selectors = CollectorsFirearmsScraper.detail_description_selectors
        assert selectors[0] == "div.single-product-description"
        assert set(WooCommerceScraper.detail_description_selectors) <= set(selectors)

    def test_their_sku_label_is_trimmed(self):
        soup = BeautifulSoup(product_page("R", "d", [], sku="L2026-10918"), "html.parser")
        assert CollectorsFirearmsScraper()._sku(soup) == "L2026-10918"

    def test_it_does_not_need_a_browser(self):
        assert CollectorsFirearmsScraper.requires_browser is False


class TestAMeasuredPace:
    """Some shops refuse traffic their own robots.txt says is acceptable."""

    class Slow(Shop):
        min_request_delay = 20.0

    @pytest.fixture(autouse=True)
    def _no_real_waiting(self, monkeypatch):
        """The pace is the thing under test, not this suite's patience."""
        monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)

    @responses.activate
    def test_the_floor_is_applied_before_the_first_request(self, ctx):
        responses.add(
            responses.GET, f"{SHOP}/product-category/rifles/", body=catalog(card(1, "Rifle"))
        )
        responses.add(responses.GET, f"{SHOP}/product/rifle/", body=product_page("R", "d", []))

        list(self.Slow().scrape(ctx))

        assert ctx._delay_for(f"{SHOP}/anything") >= 20

    @responses.activate
    def test_a_shop_without_one_is_left_at_its_stated_pace(self, ctx):
        responses.add(
            responses.GET, f"{SHOP}/product-category/rifles/", body=catalog(card(1, "Rifle"))
        )
        responses.add(responses.GET, f"{SHOP}/product/rifle/", body=product_page("R", "d", []))

        list(Shop().scrape(ctx))

        assert ctx._delay_for(f"{SHOP}/anything") == ctx.scraping.request_delay

    def test_collectors_firearms_carries_the_measurement(self):
        """Their robots asks for ten; ten was measured to be refused."""
        assert CollectorsFirearmsScraper.min_request_delay > 10
