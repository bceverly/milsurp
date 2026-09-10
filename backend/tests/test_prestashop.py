"""PrestaShop: the fifth storefront platform, and the shop it was written for.

Atlantic Firearms is a class of one so far, which is worth saying because
"one platform, one shop" is exactly the arithmetic the BigCommerce group got
wrong. The class is small; the judgment about which of their nine sections to
read is the part that took measuring, and it lives in test_atlantic_firearms.py.
"""

from __future__ import annotations

import pytest
import responses
from bs4 import BeautifulSoup

from app.scrapers import ScrapeContext
from app.scrapers.prestashop import PrestaShopScraper, full_size

SHOP = "https://shop.test"


def card(
    product_id: int, title: str, price: str | None = "$399.00", href: str | None = None
) -> str:
    money = f'<span class="price">{price}</span>' if price is not None else ""
    link = href or f"/{title.lower().replace(' ', '-')}"
    return f"""
      <article class="product js-product" data-id-product="{product_id}">
        <a class="product-thumbnail" href="{SHOP}{link}">
          <img src="{SHOP}/img/{product_id}.jpg" />
        </a>
        <h2 class="product-title"><a href="{SHOP}{link}">{title}</a></h2>
        {money}
      </article>"""


def page(*cards: str) -> str:
    return f"<html><body><div id='js-product-list'>{''.join(cards)}</div></body></html>"


def product_page(title: str, description: str = "<p>An original rifle.</p>") -> str:
    return f"""
      <html><body>
        <h1 class="page-title">{title}</h1>
        <div class="product-cover"><img src="{SHOP}/img/big-1.jpg" /></div>
        <div id="main"><div class="images-container"><img src="{SHOP}/img/big-2.jpg" /></div></div>
        <div id="description"><div class="product-description">{description}</div></div>
      </body></html>"""


class Shop(PrestaShopScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    sources = ({"category": "Parts Kits", "url": f"{SHOP}/parts-kits"},)


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestTheCard:
    def test_the_shops_own_id_is_the_key(self):
        """A renamed product keeps its id; a URL-derived key would read the
        rename as one listing withdrawn and another appearing."""
        tag = BeautifulSoup(card(4211, "Yugo M72 Kit"), "html.parser").select_one("article")
        item = Shop().item_from_card(tag, f"{SHOP}/parts-kits", "Parts Kits")
        assert item.external_key == "ps-4211"

    def test_and_the_path_where_a_theme_writes_none(self):
        tag = BeautifulSoup(
            '<article class="product"><h2 class="product-title">'
            f'<a href="{SHOP}/yugo-m72-kit">Yugo M72 Kit</a></h2></article>',
            "html.parser",
        ).select_one("article")
        item = Shop().item_from_card(tag, f"{SHOP}/parts-kits", "Parts Kits")
        assert item.external_key == "path-yugo-m72-kit"

    def test_a_card_with_no_link_is_not_a_product(self):
        tag = BeautifulSoup(
            '<article class="product" data-id-product="1"><h2 class="product-title">x</h2></article>',
            "html.parser",
        ).select_one("article")
        assert Shop().item_from_card(tag, SHOP, "Parts Kits") is None


class TestThePriceIsOftenAbsent:
    """Not a parsing failure. PrestaShop hides the price of an out-of-stock
    product, and roughly half of Atlantic Firearms' catalog is out of stock at
    any moment — 24 of their 38 C&R guns show nothing at all.
    """

    def price(self, markup):
        tag = BeautifulSoup(markup, "html.parser").select_one("article")
        return Shop().item_from_card(tag, SHOP, "x").price

    def test_a_price_is_read(self):
        assert self.price(card(1, "Kit", "$399.00")) == 399.0

    def test_a_missing_one_is_none_rather_than_zero(self):
        """Zero would sort as the cheapest thing in the catalog and read as
        free; None is what "call for price" means."""
        assert self.price(card(1, "Kit", price=None)) is None

    def test_and_so_is_an_empty_price_element(self):
        assert self.price(card(1, "Kit", price="")) is None


class TestImageSizes:
    """PrestaShop names the size in the id segment of an image path, and the
    theme's own `data-image-large-src` points at the form with no size at all —
    which is what makes dropping the suffix the shop's own idea rather than a
    guess.
    """

    def test_a_thumbnail_is_asked_for_at_full_size(self):
        assert full_size(f"{SHOP}/470108-detail_product_thumbnail/vz-58.jpg") == (
            f"{SHOP}/470108/vz-58.jpg"
        )

    def test_and_so_is_the_main_view(self):
        assert full_size(f"{SHOP}/470108-product_main/vz-58.jpg") == f"{SHOP}/470108/vz-58.jpg"

    def test_an_original_is_left_alone(self):
        assert full_size(f"{SHOP}/470108/vz-58.jpg") == f"{SHOP}/470108/vz-58.jpg"

    def test_a_path_that_merely_looks_like_one_is_not_rewritten(self):
        """Anchored at the start of the path, because that is where PrestaShop
        puts these. `/img/2024-holiday/banner.jpg` is a folder, not an id and
        a size."""
        assert full_size(f"{SHOP}/img/2024-holiday/banner.jpg") == (
            f"{SHOP}/img/2024-holiday/banner.jpg"
        )

    def test_a_query_string_survives(self):
        assert full_size(f"{SHOP}/470108-product_main/vz-58.jpg?v=2") == (
            f"{SHOP}/470108/vz-58.jpg?v=2"
        )


class TestWalkingTheCatalog:
    @responses.activate
    def test_pagination_is_a_query_string(self, ctx):
        responses.add(responses.GET, f"{SHOP}/parts-kits", body=page(card(1, "One")))
        responses.add(responses.GET, f"{SHOP}/parts-kits?page=2", body=page(card(2, "Two")))
        responses.add(responses.GET, f"{SHOP}/one", body=product_page("One"))
        responses.add(responses.GET, f"{SHOP}/two", body=product_page("Two"))

        items = list(Shop().scrape(ctx))
        assert [item.external_key for item in items][:2] == ["ps-1", "ps-2"]

    @responses.activate
    def test_a_page_with_no_cards_ends_the_section(self, ctx):
        """PrestaShop answers 200 for a page past the last one, so there is no
        error to notice — only the absence of cards."""
        responses.add(responses.GET, f"{SHOP}/parts-kits", body=page(card(1, "One")))
        responses.add(responses.GET, f"{SHOP}/parts-kits?page=2", body=page())
        responses.add(responses.GET, f"{SHOP}/one", body=product_page("One"))

        assert len(list(Shop().scrape(ctx))) == 1

    @responses.activate
    def test_a_page_that_repeats_the_last_one_also_ends_it(self, ctx):
        """Some themes serve the final page again rather than an empty one,
        which would otherwise walk to the page cap for nothing."""
        responses.add(responses.GET, f"{SHOP}/parts-kits", body=page(card(1, "One")))
        responses.add(responses.GET, f"{SHOP}/parts-kits?page=2", body=page(card(1, "One")))
        responses.add(responses.GET, f"{SHOP}/one", body=product_page("One"))

        assert len(list(Shop().scrape(ctx))) == 1

    @responses.activate
    def test_the_product_page_supplies_the_gallery_and_the_prose(self, ctx):
        responses.add(responses.GET, f"{SHOP}/parts-kits", body=page(card(1, "One")))
        responses.add(responses.GET, f"{SHOP}/parts-kits?page=2", body=page())
        responses.add(responses.GET, f"{SHOP}/one", body=product_page("One"))

        item = next(iter(Shop().scrape(ctx)))
        assert item.description == "An original rifle."
        assert item.images_are_complete is True
        # The gallery strip, not the cover — see detail_gallery_selectors.
        assert item.image_urls == [f"{SHOP}/img/big-2.jpg"]

    @responses.activate
    def test_a_description_that_is_a_stylesheet_is_not_kept(self, ctx):
        """These blocks are vendor HTML and may carry a `<style>`, which
        `get_text()` would hand back as prose. See scrapers.base.flatten_html
        and the 85 Apex listings that arrived as one."""
        responses.add(responses.GET, f"{SHOP}/parts-kits", body=page(card(1, "One")))
        responses.add(responses.GET, f"{SHOP}/parts-kits?page=2", body=page())
        responses.add(
            responses.GET,
            f"{SHOP}/one",
            body=product_page("One", "<style>.a{color:red}</style><p>A kit.</p>"),
        )

        assert next(iter(Shop().scrape(ctx))).description == "A kit."


class TestWhenASectionIsRefused:
    @responses.activate
    def test_a_first_page_that_fails_is_a_failure(self, ctx):
        """Nothing is not a partial result — it is a failure, and it should be
        loud rather than de-listing a catalog."""
        from app.scrapers.base import ScrapeError

        responses.add(responses.GET, f"{SHOP}/parts-kits", status=500)
        with pytest.raises(ScrapeError):
            list(Shop().scrape(ctx))

    @responses.activate
    def test_a_later_page_that_fails_keeps_what_was_read(self, ctx):
        responses.add(responses.GET, f"{SHOP}/parts-kits", body=page(card(1, "One")))
        responses.add(responses.GET, f"{SHOP}/parts-kits?page=2", status=500)
        responses.add(responses.GET, f"{SHOP}/one", body=product_page("One"))

        items = list(Shop().scrape(ctx))
        assert len(items) == 1
        assert ctx.warnings
