"""The Magento base class.

Two shops on this platform share almost no CSS class, so the pages here are
written to both shapes: the stock ``li.product-item`` grid Century Arms uses
and the custom ``.products-grid .item`` grid Classic Firearms uses. What they
do share is ``?p=N`` pagination, the ``/media/catalog/product/cache/`` image
path and — on the product page — schema.org Product JSON-LD, which is where
the interesting behavior is.
"""

from __future__ import annotations

import json

import pytest
import responses
from bs4 import BeautifulSoup

from app.scrapers import ScrapeContext
from app.scrapers.base import ScrapeError
from app.scrapers.magento import MagentoScraper, _amount, full_size, price_now, product_data

SHOP = "https://shop.test"
MEDIA = f"{SHOP}/media/catalog/product"


def stock_card(product_id: int, title: str, price_html: str = '<span class="price">$600.00</span>'):
    """Stock Magento, the way Century Arms renders it."""
    return f"""
    <li class="item product product-item">
      <div class="product-item-info" id="product-item-info_{product_id}">
        <a class="product photo product-item-photo" href="{SHOP}/{title.lower().replace(' ', '-')}.html">
          <img class="product-image-photo"
               src="{MEDIA}/cache/9493bba7014963d5e8c856350db77708/h/g/photo.jpg" alt="{title}"/>
        </a>
        <strong class="product name product-item-name">
          <a class="product-item-link" href="{SHOP}/{title.lower().replace(' ', '-')}.html">{title}</a>
        </strong>
        <div class="product-price-wrapper">{price_html}</div>
      </div>
    </li>
    """


def themed_card(slug: str, title: str, price_html: str = ""):
    """A custom theme with no product id anywhere, the way Classic Firearms
    renders it: the name lives in the photograph's alt text."""
    return f"""
    <div class="mb-2 product-card item">
      <a href="{SHOP}/{slug}/"><img src="{MEDIA}/cache/1/small_image/270x170/9df78eab33525d08d6e5fb8d27136e95/2/0/x.png" alt="{title}"/></a>
      {price_html}
    </div>
    """


def catalog(cards: str, next_href: str | None = None) -> str:
    nav = f'<li class="pages-item-next"><a href="{next_href}">Next</a></li>' if next_href else ""
    return (
        f"<html><body><ol class='products'>{cards}</ol><div class='pages'>{nav}</div></body></html>"
    )


def product_page(name: str, *, price="1599.99", availability="InStock", images=2, sku="SKU-1"):
    node = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "sku": sku,
        "description": "<p>An <strong>original</strong> rifle.</p>",
        "image": [f"{MEDIA}/b/m/photo{n}.jpg" for n in range(images)],
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "USD",
            "availability": f"https://schema.org/{availability}",
        },
    }
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head>'
        f"<body><h1>{name}</h1></body></html>"
    )


class Shop(MagentoScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    sources = ({"category": "Surplus", "url": f"{SHOP}/surplus"},)


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestImages:
    def test_a_magento_2_cache_path_is_stripped(self):
        assert full_size(f"{MEDIA}/cache/9493bba7014963d5e8c856350db77708/h/g/x.jpg") == (
            f"{MEDIA}/h/g/x.jpg"
        )

    def test_and_a_magento_1_one_with_a_size_in_it(self):
        assert (
            full_size(
                f"{MEDIA}/cache/1/small_image/270x170/9df78eab33525d08d6e5fb8d27136e95/2/0/x.png"
            )
            == f"{MEDIA}/2/0/x.png"
        )

    def test_an_original_url_is_untouched(self):
        assert full_size(f"{MEDIA}/b/m/x.jpg") == f"{MEDIA}/b/m/x.jpg"


class TestPrice:
    def parse(self, html):
        return price_now(BeautifulSoup(html, "html.parser").div)

    def test_the_plain_case(self):
        assert self.parse('<div><span class="price">$149.95</span></div>') == 149.95

    def test_cents_in_their_own_element(self):
        """Classic Firearms renders "$1599<span class="decimal">99</span>",
        whose text is "$1599 99". Read as one number that is $1599.00 — and the
        product page then says 1599.99, so every re-scan that skipped the
        detail fetch reported a price change that had not happened."""
        assert (
            self.parse('<div><span class="price">$1599<span class="decimal">99</span></span></div>')
            == 1599.99
        )

    def test_and_the_dollars_are_not_mangled_finding_them(self):
        """Removing the cents by *text* turns "$1599 99" into "$15 9"."""
        assert (
            _amount(
                BeautifulSoup(
                    '<span class="price">$1299<span class="decimal">50</span></span>', "html.parser"
                ).span
            )
            == 1299.50
        )

    def test_a_data_attribute_wins_when_there_is_one(self):
        """Where Magento actually puts it, on a descendant span."""
        assert (
            self.parse(
                '<div><span class="price-wrapper" data-price-amount="42.50">$42.50</span></div>'
            )
            == 42.50
        )

    def test_and_is_found_when_a_theme_puts_it_on_the_card(self):
        assert self.parse('<div data-price-amount="42.50"><span class="price">$1</span></div>') == (
            42.50
        )

    def test_a_listing_with_no_price(self):
        """Out of stock, or a minimum-advertised-price rule that shows the
        number only in the cart. Both mean nothing to watch."""
        assert self.parse('<div><span class="price">TOO LOW TO SHOW</span></div>') is None


class TestTheKey:
    def parse(self, html):
        soup = BeautifulSoup(catalog(html), "html.parser")
        return Shop().item_from_card(soup.select_one(Shop.card_selector), SHOP, "Surplus")

    def test_the_shops_own_id_is_used_where_the_theme_writes_one(self):
        assert self.parse(stock_card(41142, "Swiss 1889")).external_key == "magento-41142"

    def test_and_the_url_path_where_it_does_not(self):
        item = Shop().item_from_card(
            BeautifulSoup(catalog(themed_card("bm-59", "BM-59")), "html.parser").select_one(
                ".products-grid .item, .product-card"
            ),
            SHOP,
            "",
        )
        assert item.external_key == "path-bm-59"

    def test_only_magentos_own_wrapper_counts_as_an_id(self):
        """Any data-product-id looked more generous and was worse: on one of
        these shops the only element carrying one is a financing widget shown on
        in-stock products and not on sold-out ones, so a rifle selling out would
        change key and read as a de-listing plus a new arrival."""
        card = f"""
        <li class="item product product-item">
          <a class="product-item-link" href="{SHOP}/rifle/">Rifle</a>
          <div class="credova-financing-offer" data-product-id="1615"></div>
        </li>
        """
        assert self.parse(card).external_key == "path-rifle"


class TestTheThemedGrid:
    def test_the_name_is_read_from_the_photographs_alt_text(self):
        """Which is where a themed grid can leave it: the link text is
        whitespace."""
        soup = BeautifulSoup(catalog(themed_card("m96", "M96 Swedish Mauser")), "html.parser")
        item = Shop().item_from_card(soup.select_one(".product-card"), SHOP, "")
        assert item.title == "M96 Swedish Mauser"

    def test_a_card_with_no_link_is_not_a_product(self):
        soup = BeautifulSoup('<li class="product-item"><span>Sale!</span></li>', "html.parser")
        assert Shop().item_from_card(soup.select_one("li"), SHOP, "") is None


class TestTheProductPage:
    @responses.activate
    def test_structured_data_supplies_everything(self, ctx):
        responses.add(responses.GET, f"{SHOP}/surplus", body=catalog(stock_card(7, "Rifle")))
        responses.add(responses.GET, f"{SHOP}/rifle.html", body=product_page("M39 Finnish Rifle"))

        item = next(iter(Shop().scrape(ctx)))

        assert item.title == "M39 Finnish Rifle"
        assert item.price == 1599.99
        assert item.extra["sku"] == "SKU-1"
        assert item.description == "An original rifle."
        assert item.images_are_complete is True
        assert item.image_urls == [f"{MEDIA}/b/m/photo0.jpg", f"{MEDIA}/b/m/photo1.jpg"]

    @responses.activate
    def test_out_of_stock_is_read_from_the_offer(self, ctx):
        responses.add(responses.GET, f"{SHOP}/surplus", body=catalog(stock_card(7, "Rifle")))
        responses.add(
            responses.GET,
            f"{SHOP}/rifle.html",
            body=product_page("K98", availability="OutOfStock"),
        )

        assert next(iter(Shop().scrape(ctx))).is_sold is True

    @responses.activate
    def test_a_page_without_structured_data_falls_back_to_the_markup(self, ctx):
        responses.add(responses.GET, f"{SHOP}/surplus", body=catalog(stock_card(7, "Rifle")))
        responses.add(
            responses.GET,
            f"{SHOP}/rifle.html",
            body=(
                '<html><body><h1 class="page-title">SKS Type 56</h1>'
                '<div class="product attribute description">Turn-in condition.</div>'
                f'<div class="product media"><img src="{MEDIA}/s/k/sks.jpg"/></div>'
                "</body></html>"
            ),
        )

        item = next(iter(Shop().scrape(ctx)))

        assert item.title == "SKS Type 56"
        assert item.description == "Turn-in condition."
        assert item.image_urls == [f"{MEDIA}/s/k/sks.jpg"]

    def test_malformed_structured_data_is_not_a_failure(self):
        soup = BeautifulSoup('<script type="application/ld+json">{not json</script>', "html.parser")
        assert product_data(soup) is None

    def test_a_non_product_block_is_ignored(self):
        soup = BeautifulSoup(
            '<script type="application/ld+json">{"@type": "Organization"}</script>', "html.parser"
        )
        assert product_data(soup) is None


class TestWalkingTheCatalog:
    @responses.activate
    def test_pagination_follows_the_shops_own_next_link(self, ctx):
        responses.add(
            responses.GET,
            f"{SHOP}/surplus",
            body=catalog(stock_card(1, "One"), next_href=f"{SHOP}/surplus?p=2"),
        )
        responses.add(responses.GET, f"{SHOP}/surplus", body=catalog(stock_card(2, "Two")))
        for slug in ("one", "two"):
            responses.add(responses.GET, f"{SHOP}/{slug}.html", body=product_page(slug.title()))

        assert len(list(Shop().scrape(ctx))) == 2

    @responses.activate
    def test_a_shop_that_disallows_its_own_pagination_stops_at_page_one(self, app_config):
        """Classic Firearms really does: `Disallow: /*?p=` with an Allow only
        for /news. Page one is still a page of listings, so this is reported
        rather than failed."""
        import dataclasses

        config = dataclasses.replace(
            app_config, scraping=dataclasses.replace(app_config.scraping, obey_robots=True)
        )
        responses.add(
            responses.GET,
            f"{SHOP}/robots.txt",
            body="User-agent: *\nDisallow: /*?p=",
            content_type="text/plain",
        )
        responses.add(
            responses.GET,
            f"{SHOP}/surplus",
            body=catalog(stock_card(1, "One"), next_href=f"{SHOP}/surplus?p=2"),
        )
        responses.add(responses.GET, f"{SHOP}/one.html", body=product_page("One"))

        context = ScrapeContext(config)
        try:
            items = list(Shop().scrape(context))
        finally:
            context.close()

        assert len(items) == 1
        assert any("robots.txt disallows" in warning for warning in context.warnings)

    @responses.activate
    def test_a_first_page_that_fails_is_a_failure(self, ctx):
        responses.add(responses.GET, f"{SHOP}/surplus", status=500)

        with pytest.raises(ScrapeError):
            list(Shop().scrape(ctx))


class TestTheShops:
    def test_classic_firearms_reads_its_real_categories(self):
        """Two invented ones 404ed: /firearms/curio-relic/ and
        /firearms/handguns/surplus-handguns/ are the obvious names for these
        sections and neither exists."""
        from app.scrapers.classic_firearms import ClassicFirearmsScraper

        urls = [source["url"] for source in ClassicFirearmsScraper.sources]
        assert any("rifles/military-surplus" in url for url in urls)
        assert any("handguns/military-surplus" in url for url in urls)
        assert any("c-and-r-eligible" in url for url in urls)
        assert not any("curio-relic" in url or "surplus-handguns" in url for url in urls)

    def test_century_arms_is_not_registered(self):
        """Their prices are dealer-only, so there is nothing here to watch.

        Kept as a test rather than a comment because the reason is a fact about
        the vendor, and the next person to notice they are Magento and think
        "that is nearly free" should find out why before writing it again.
        """
        from app.scrapers import SCRAPER_CLASSES

        assert not any(cls.slug == "century-arms" for cls in SCRAPER_CLASSES)

    def test_classic_firearms_does_not_need_a_browser(self):
        from app.scrapers.classic_firearms import ClassicFirearmsScraper

        assert ClassicFirearmsScraper.requires_browser is False


def facet_nav(groups: dict[str, list[tuple[str, int]]]) -> str:
    """Magento's layered navigation: a <dt> label and a <dd> list per group."""
    blocks = []
    for label, values in groups.items():
        links = "".join(
            f'<li><a href="{SHOP}/surplus/{slug}/">{slug} ({count})</a></li>'
            for slug, count in values
        )
        blocks.append(f"<dt>{label}</dt><dd><ol class='single-choice'>{links}</ol></dd>")
    return f"<dl id='narrow-by-list'>{''.join(blocks)}</dl>"


class TestWalkingTheFacetsInstead:
    """For a shop that disallows its own pagination.

    Magento's layered navigation is a set of facet groups, each of which
    partitions the category, and each facet value is a plain path. So where
    `?p=2` is off limits the same products are still reachable one facet at a
    time, entirely within the rules — which is the difference between 24
    listings from a section and all 122 of them.
    """

    def choose(self, groups, page_size=24):
        soup = BeautifulSoup(f"<html><body>{facet_nav(groups)}</body></html>", "html.parser")
        return MagentoScraper()._best_facet(soup, f"{SHOP}/surplus/", page_size)

    def test_the_group_that_fits_in_a_page_is_chosen(self):
        chosen = self.choose(
            {
                "Action": [("bolt", 60), ("semi", 62)],  # 60 > 24, cannot be walked
                "Caliber": [("30_06", 19), ("8mm", 18), ("7.62x54r", 12)],
            }
        )
        assert chosen == [
            f"{SHOP}/surplus/30_06/",
            f"{SHOP}/surplus/8mm/",
            f"{SHOP}/surplus/7.62x54r/",
        ]

    def test_and_the_cheapest_of_the_ones_that_fit(self):
        """Caliber and Manufacturer both cover the category and both fit; the
        one with fewer values costs fewer requests to walk."""
        chosen = self.choose(
            {
                "Manufacturer": [(f"m{n}", 2) for n in range(20)],
                "Caliber": [("a", 20), ("b", 20)],
            }
        )
        assert len(chosen) == 2

    def test_coverage_beats_cheapness(self):
        """A group of two values covering half the catalog is not better than
        one of four covering all of it."""
        chosen = self.choose(
            {"Half": [("a", 10), ("b", 10)], "All": [("w", 10), ("x", 10), ("y", 10), ("z", 10)]}
        )
        assert len(chosen) == 4

    def test_a_group_with_no_counts_is_not_a_partition(self):
        """The Category facet lists sibling sections with no counts at all;
        walking it would be guessing at coverage."""
        assert self.choose({"Category": [("rifles", 0), ("handguns", 0)]}) == []

    def test_a_facet_rendered_as_a_query_string_is_no_use(self):
        """It is the thing that was disallowed in the first place."""
        soup = BeautifulSoup(
            "<html><body><dl id='narrow-by-list'><dt>Price</dt><dd>"
            f"<a href='{SHOP}/surplus?price=0-500'>0-500 (5)</a>"
            "</dd></dl></body></html>",
            "html.parser",
        )
        assert MagentoScraper()._best_facet(soup, f"{SHOP}/surplus/", 24) == []

    @responses.activate
    def test_a_section_is_read_facet_by_facet(self, ctx):
        class Faceted(Shop):
            follow_facets = True
            facet_page_size = 2

        nav = facet_nav({"Caliber": [("30_06", 2), ("8mm", 1)]})
        responses.add(
            responses.GET,
            f"{SHOP}/surplus",
            # A next link, because facets are only walked when there is more.
            body=catalog(stock_card(1, "One"), next_href=f"{SHOP}/surplus?p=2").replace(
                "</body>", f"{nav}</body>"
            ),
        )
        responses.add(
            responses.GET,
            f"{SHOP}/surplus/30_06/",
            body=catalog(stock_card(1, "One") + stock_card(2, "Two")),
        )
        responses.add(responses.GET, f"{SHOP}/surplus/8mm/", body=catalog(stock_card(3, "Three")))
        for slug in ("one", "two", "three"):
            responses.add(responses.GET, f"{SHOP}/{slug}.html", body=product_page(slug.title()))

        items = list(Faceted().scrape(ctx))

        # The first page's listing plus everything the facets added, once each.
        assert sorted(item.external_key for item in items) == [
            "magento-1",
            "magento-2",
            "magento-3",
        ]

    @responses.activate
    def test_a_facet_that_will_not_load_costs_only_its_own_share(self, ctx):
        class Faceted(Shop):
            follow_facets = True
            facet_page_size = 2

        nav = facet_nav({"Caliber": [("30_06", 1), ("8mm", 1)]})
        responses.add(
            responses.GET,
            f"{SHOP}/surplus",
            body=catalog("", next_href=f"{SHOP}/surplus?p=2").replace("</body>", f"{nav}</body>"),
        )
        responses.add(responses.GET, f"{SHOP}/surplus/30_06/", status=500)
        responses.add(responses.GET, f"{SHOP}/surplus/8mm/", body=catalog(stock_card(3, "Three")))
        responses.add(responses.GET, f"{SHOP}/three.html", body=product_page("Three"))

        items = list(Faceted().scrape(ctx))

        assert [item.external_key for item in items] == ["magento-3"]
        assert any("Skipping that facet" in warning for warning in ctx.warnings)

    @responses.activate
    def test_a_section_with_no_walkable_facet_says_so(self, ctx):
        class Faceted(Shop):
            follow_facets = True
            facet_page_size = 24

        nav = facet_nav({"Action": [("bolt", 60)]})
        responses.add(
            responses.GET,
            f"{SHOP}/surplus",
            body=catalog(stock_card(1, "One"), next_href=f"{SHOP}/surplus?p=2").replace(
                "</body>", f"{nav}</body>"
            ),
        )
        responses.add(responses.GET, f"{SHOP}/one.html", body=product_page("One"))

        items = list(Faceted().scrape(ctx))

        assert len(items) == 1
        assert any("No facet small enough" in warning for warning in ctx.warnings)

    @responses.activate
    def test_a_section_that_fits_on_one_page_pays_for_no_facets(self, ctx):
        """There is no second page to be barred from, so walking the facets
        would only re-fetch what has already been read."""

        class Faceted(Shop):
            follow_facets = True
            facet_page_size = 2

        nav = facet_nav({"Caliber": [("30_06", 1)]})
        responses.add(
            responses.GET,
            f"{SHOP}/surplus",
            body=catalog(stock_card(1, "One")).replace("</body>", f"{nav}</body>"),
        )
        responses.add(responses.GET, f"{SHOP}/one.html", body=product_page("One"))

        items = list(Faceted().scrape(ctx))

        assert [item.external_key for item in items] == ["magento-1"]
        assert not any("30_06" in call.request.url for call in responses.calls)

    def test_classic_firearms_walks_them_and_the_base_class_does_not(self):
        from app.scrapers.classic_firearms import ClassicFirearmsScraper

        assert ClassicFirearmsScraper.follow_facets is True
        # Off by default: a shop that can page normally should not pay for it.
        assert MagentoScraper.follow_facets is False
