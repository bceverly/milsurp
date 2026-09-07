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
from app.scrapers.base import ScrapeError
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


@pytest.fixture
def no_global_cooldown(monkeypatch):
    """Neutralize the shared "leave this host alone" register.

    These tests drive a host to its refusal ceiling on purpose, to exercise the
    escalation *inside* one context. Reaching that ceiling is also what
    publishes a cooldown every other process obeys — correct behavior, and a
    different subject. Tested separately in test_cooldown.py.
    """
    monkeypatch.setattr("app.scrapers.base.cooldown.paused_for", lambda _url: 0.0)
    monkeypatch.setattr("app.scrapers.base.cooldown.refused", lambda *_a, **_k: 0.0)


class Shop(WooCommerceScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    sources = ({"category": "Rifles", "url": f"{SHOP}/product-category/rifles/"},)


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    """These scrapers hold themselves to one request every five seconds.

    That is the right pace against a real shop and the wrong one in a test
    suite: without this the file takes forty seconds to assert things that
    have nothing to do with waiting.
    """
    monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)


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

    @responses.activate
    def test_the_floor_is_applied_before_the_first_request(self, ctx):
        responses.add(
            responses.GET, f"{SHOP}/product-category/rifles/", body=catalog(card(1, "Rifle"))
        )
        responses.add(responses.GET, f"{SHOP}/product/rifle/", body=product_page("R", "d", []))

        list(self.Slow().scrape(ctx))

        assert ctx._delay_for(f"{SHOP}/anything") >= 20

    @responses.activate
    def test_the_default_is_gentler_than_the_application_wide_one(self, ctx):
        """These are small dealers on shared hosting. One request a second is
        enough to be refused, and two of them did refuse it."""
        responses.add(
            responses.GET, f"{SHOP}/product-category/rifles/", body=catalog(card(1, "Rifle"))
        )
        responses.add(responses.GET, f"{SHOP}/product/rifle/", body=product_page("R", "d", []))

        list(Shop().scrape(ctx))

        assert ctx._delay_for(f"{SHOP}/anything") > ctx.scraping.request_delay
        assert WooCommerceScraper.min_request_delay >= 5

    def test_collectors_firearms_carries_the_measurement(self):
        """Their robots asks for ten; ten was measured to be refused."""
        assert CollectorsFirearmsScraper.min_request_delay > 10


class TestAPriceIsNotInventedFromCardText:
    """A card with no price element has no price.

    MCT Defense's firearms page is a page of *category* tiles, not products,
    and reading a number out of the card's text made "AK Style Shotguns In 12
    Gauge" into a twelve-dollar listing.
    """

    def price_of(self, html: str):
        return price_now(BeautifulSoup(html, "html.parser"))

    def test_a_category_tile_has_none(self):
        assert (
            self.price_of("<li class='product'><h3>AK Style Shotguns In 12 Gauge</h3></li>") is None
        )

    def test_a_title_full_of_numbers_has_none(self):
        assert self.price_of("<li class='product'><h3>Model 1903 Mark 1, 30-06</h3></li>") is None

    def test_but_a_real_price_block_still_reads(self):
        html = '<li class="product"><h3>Rifle 7.62x54R</h3><span class="price">$600.00</span></li>'
        assert self.price_of(html) == 600.00

    def test_and_so_does_a_bare_amount_element(self):
        html = (
            '<li class="product"><h3>Rifle</h3>'
            '<span class="woocommerce-Price-amount">$450.00</span></li>'
        )
        assert self.price_of(html) == 450.00


class TestTheOtherWooCommerceShops:
    """What each shop's theme needed, so a change to it is visible as a change.

    Every one of these was found by reading the shop's real markup, and each is
    a single selector in front of the stock ones — the defaults stay behind
    them, so a theme reverting does not break the scraper.
    """

    def test_ancestry_guns_reads_the_h3(self):
        """Their h2 is a "Share on:" widget, so every listing was titled that."""
        from app.scrapers.ancestry_guns import AncestryGunsScraper

        assert AncestryGunsScraper.title_selectors[0] == "h3.upper"
        assert set(WooCommerceScraper.title_selectors) <= set(AncestryGunsScraper.title_selectors)

    def test_axis_arms_reads_the_h1(self):
        """An Elementor loop: the h1 is the name and the h2 is the price, so
        reading headings in the usual order titled every rifle "$ 2,449.99"."""
        from app.scrapers.axis_arms import AxisArmsScraper

        assert AxisArmsScraper.title_selectors[0] == "h1.elementor-heading-title"

    def test_axis_arms_reads_both_of_its_sections(self):
        from app.scrapers.axis_arms import AxisArmsScraper

        assert {source["category"] for source in AxisArmsScraper.sources} == {
            "Rifles",
            "Handguns",
        }

    def test_co_gun_sales_starts_at_page_one(self):
        """The roadmap recorded page 6, which is where somebody happened to be
        browsing. Pagination follows the shop's own "next" link."""
        from app.scrapers.co_gun_sales import CoGunSalesScraper

        assert all("/page/" not in source["url"] for source in CoGunSalesScraper.sources)

    def test_checkpoint_charlies_reads_a_tag_not_a_category(self):
        """A tag archive renders the same loop; the URL just looks wrong."""
        from app.scrapers.checkpoint_charlies import CheckpointCharliesScraper

        assert "/product-tag/" in CheckpointCharliesScraper.sources[0]["url"]

    def test_none_of_them_need_a_browser(self):
        from app.scrapers.ancestry_guns import AncestryGunsScraper
        from app.scrapers.axis_arms import AxisArmsScraper
        from app.scrapers.checkpoint_charlies import CheckpointCharliesScraper
        from app.scrapers.co_gun_sales import CoGunSalesScraper

        for scraper in (
            AncestryGunsScraper,
            AxisArmsScraper,
            CoGunSalesScraper,
            CheckpointCharliesScraper,
        ):
            assert scraper.requires_browser is False

    @responses.activate
    def test_a_card_repeated_by_a_theme_is_yielded_once(self, ctx):
        """Axis Arms' Elementor markup carries the product classes on both the
        outer article and an inner div, so every card matches twice."""
        doubled = (
            f'<li class="product post-1"><a href="{SHOP}/product/x/">'
            f'<div class="product type-product post-1">'
            f'<h2 class="woocommerce-loop-product__title">Rifle</h2>'
            f'<span class="price"><span class="woocommerce-Price-amount">$9.00</span></span>'
            f"</div></a></li>"
        )
        responses.add(responses.GET, f"{SHOP}/product-category/rifles/", body=catalog(doubled))
        responses.add(responses.GET, f"{SHOP}/product/x/", body=product_page("Rifle", "d", []))

        assert len(list(Shop().scrape(ctx))) == 1


class TestWhenProductPagesAreRefused:
    """Checkpoint Charlie's, which is why the fallback exists.

    Their category pages answer 200 and their /product/ pages answer 429 to
    every pace and every set of headers — a rule about the path, not about how
    fast we are asking. The scan used to spend an hour escalating its backoff
    and then throw the whole catalog read away.
    """

    def catalog_of(self, count: int) -> str:
        return catalog("".join(card(n, f"Rifle {n}") for n in range(count)))

    def refuse_every_product(self, count: int) -> None:
        responses.add(
            responses.GET, f"{SHOP}/product-category/rifles/", body=self.catalog_of(count)
        )
        for n in range(count):
            responses.add(responses.GET, f"{SHOP}/product/rifle-{n}/", status=429)

    @responses.activate
    def test_the_catalog_entry_survives_a_refused_product_page(self, ctx):
        self.refuse_every_product(1)

        items = list(Shop().scrape(ctx))

        assert [item.title for item in items] == ["Rifle 0"]
        # The card carried these, so they are still worth having.
        assert items[0].price == 600.00
        assert items[0].image_urls == [f"{UPLOADS}/rifle.jpg"]
        # But the gallery was never read, so nothing claims it was.
        assert items[0].images_are_complete is False

    @responses.activate
    def test_and_the_run_says_so(self, ctx):
        self.refuse_every_product(1)

        list(Shop().scrape(ctx))

        assert any("Keeping the catalog entry only" in w for w in ctx.warnings)

    @responses.activate
    def test_a_shop_that_refuses_all_of_them_stops_asking(self, ctx, no_global_cooldown):
        """Otherwise the whole catalog is walked one pointless request at a
        time, each one paying the full retry-and-backoff bill."""
        wanted = Shop.MAX_DETAIL_FAILURES
        self.refuse_every_product(wanted + 4)

        items = list(Shop().scrape(ctx))

        assert len(items) == wanted + 4
        asked = {call.request.url for call in responses.calls if "/product/" in call.request.url}
        assert len(asked) == wanted
        assert any("taking the rest of this scan from the catalog only" in w for w in ctx.warnings)

    @responses.activate
    def test_one_that_recovers_is_not_given_up_on(self, ctx, no_global_cooldown):
        """The count is failures *in a row*. A shop having a bad minute in the
        middle of a long catalog should not lose the rest of its galleries."""
        responses.add(responses.GET, f"{SHOP}/product-category/rifles/", body=self.catalog_of(4))
        responses.add(responses.GET, f"{SHOP}/product/rifle-0/", status=429)
        responses.add(responses.GET, f"{SHOP}/product/rifle-1/", status=429)
        for n in (2, 3):
            responses.add(
                responses.GET,
                f"{SHOP}/product/rifle-{n}/",
                body=product_page(f"Rifle {n}", "prose", [f"{UPLOADS}/a.jpg"]),
            )

        items = list(Shop().scrape(ctx))

        assert [item.images_are_complete for item in items] == [False, False, True, True]


class TestWhenACatalogPageIsRefused:
    """Page 3 failing should not throw away pages 1 and 2.

    Checkpoint Charlie's cost 56 minutes, walked 24 listings, saved 5, and then
    reported a failed run with nothing found — because the third page of the
    tag answered 429 and the exception came out through the whole scan.
    """

    @responses.activate
    def test_the_pages_already_read_are_kept(self, ctx):
        responses.add(
            responses.GET,
            f"{SHOP}/product-category/rifles/",
            body=catalog(card(1, "Rifle One"), next_href=f"{SHOP}/product-category/rifles/page/2/"),
        )
        responses.add(responses.GET, f"{SHOP}/product-category/rifles/page/2/", status=429)
        responses.add(responses.GET, f"{SHOP}/product/rifle-one/", body=product_page("A", "d", []))

        items = list(Shop().scrape(ctx))

        assert [item.title for item in items] == ["A"]
        assert any("Stopping this section at page 1" in w for w in ctx.warnings)

    @responses.activate
    def test_but_a_first_page_that_cannot_be_opened_is_a_failure(self, ctx):
        """Nothing is not a partial result."""
        responses.add(responses.GET, f"{SHOP}/product-category/rifles/", status=429)

        with pytest.raises(ScrapeError):
            list(Shop().scrape(ctx))


class TestAPhotographThatIsNotAnImgTag:
    """CO Gun Sales, whose 116 listings all arrived with no photograph.

    Their theme is a page builder and their gallery is a plugin, and between
    them the product markup contains no <img> at all: the card's picture is a
    CSS background on a link, and the nine photographs on the product page are
    JSON in an attribute on the gallery div.
    """

    CDN = "https://i0.wp.com/cogunsales.test/wp-content/uploads/2026/01"
    ORIGIN = "https://cogunsales.test/wp-content/uploads/2026/01"

    def card_with_a_css_background(self) -> str:
        return f"""
        <div class="product type-product post-42 instock">
          <a class="thumb" href="{SHOP}/product/luger/"
             style="background-image:url({self.CDN}/IMG_1.png?fit=1024%2C1024&amp;ssl=1);
                    background-size: contain;"></a>
          <h2 class="woocommerce-loop-product__title">1918 DWM Luger</h2>
          <span class="price"><span class="woocommerce-Price-amount">$3,200.00</span></span>
        </div>
        """

    def test_the_card_picture_is_read_off_the_style(self):
        soup = BeautifulSoup(catalog(self.card_with_a_css_background()), "html.parser")
        item = Shop().item_from_card(soup.select_one(".product"), SHOP, "C&R")

        assert item.title == "1918 DWM Luger"
        assert item.image_urls == [f"{self.CDN}/IMG_1.png?fit=1024%2C1024&ssl=1"]

    def test_an_img_still_wins_when_there_is_one(self):
        """The background is a fallback, not a second source. A theme that has
        both should not have the decorative one preferred."""
        html = f"""
        <li class="product post-7 instock" style="background-image:url({self.CDN}/frame.png)">
          <a href="{SHOP}/product/x/"><img src="{UPLOADS}/real-300x200.jpg"/>
          <h2 class="woocommerce-loop-product__title">Rifle</h2>
          <span class="price"><span class="woocommerce-Price-amount">$9.00</span></span></a>
        </li>
        """
        soup = BeautifulSoup(catalog(html), "html.parser")
        item = Shop().item_from_card(soup.select_one("li.product"), SHOP, "")

        assert item.image_urls == [f"{UPLOADS}/real.jpg"]

    def gallery_as_json(self, count: int) -> str:
        entries = ", ".join(
            f'{{"large_image": "{self.ORIGIN}/IMG_{n}.png", '
            f'"src": "{self.CDN}/IMG_{n}.png?fit=1600%2C1600&amp;amp;ssl=1"}}'
            for n in range(count)
        )
        return (
            '<html><body><div class="woocommerce-product-gallery images" '
            f'data-wcsvi=\'{{"slugs":[],"images":[{entries}]}}\'></div>'
            '<h1 class="product_title">1918 DWM Luger</h1></body></html>'
        )

    def test_the_gallery_is_read_out_of_the_json(self):
        soup = BeautifulSoup(self.gallery_as_json(3), "html.parser")
        photos = Shop().gallery(soup, f"{SHOP}/product/luger/")

        assert photos == [f"{self.ORIGIN}/IMG_{n}.png" for n in range(3)]

    def test_the_original_is_preferred_to_the_cdn_copy(self):
        """large_image is the upload itself; src is the same photograph behind
        an image CDN with the resize in a query string."""
        soup = BeautifulSoup(self.gallery_as_json(1), "html.parser")

        assert "i0.wp.com" not in Shop().gallery(soup, SHOP)[0]

    def test_img_tags_still_win_when_the_theme_renders_them(self):
        soup = BeautifulSoup(product_page("Rifle", "d", [f"{UPLOADS}/a.jpg"]), "html.parser")

        assert Shop().gallery(soup, SHOP) == [f"{UPLOADS}/a.jpg"]

    def test_an_attribute_that_is_not_json_is_not_a_failure(self):
        soup = BeautifulSoup(
            '<div class="woocommerce-product-gallery" data-wcsvi="not json"></div>',
            "html.parser",
        )

        assert Shop().gallery(soup, SHOP) == []
