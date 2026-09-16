"""Royal Tiger Imports: five places a title hides, two prices per tile.

**Written because this scraper had no tests at all** -- 527 lines feeding 210
live listings, the largest parser here without one, and the only shop whose
catalog renders in JavaScript so the recorded HTTP fixtures cannot reach it.

Its own module docstring is a list of hazards: WooCommerce behind Elementor and
JetEngine, three pagination mechanisms, titles in any of five elements and
prices in two. Every one of those is a pure function over markup, so all of it
is pinned here without a browser and without asking the shop -- which matters
more here than elsewhere, because this site is fragile and there is no reason
to fetch from it to find out how a regex behaves.

The markup below is the shape of theirs, trimmed to the element under test.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers.royal_tiger import (
    MIN_PRICE,
    Section,
    _extract_image,
    _extract_price,
    _extract_title,
    _find_products,
    _full_size,
    _is_product_image,
    _photo_identity,
    extract_gallery,
    parse_products,
)

UPLOADS = "https://royaltigerimports.com/wp-content/uploads/2024/01"


def tile_of(markup: str):
    """One product tile, as the parser receives it."""
    soup = BeautifulSoup(f"<div class='product'>{markup}</div>", "html.parser")
    return soup.find("div", class_="product")


def link_in(tile):
    import re

    return tile.find("a", href=re.compile(r"/shop/"))


class TestTheFiveDifferentPlacesATitleLives:
    """Which one answers depends on the template, and the order matters:
    the same Elementor heading class is reused for the price on some of them."""

    def test_the_links_own_title_attribute_wins(self):
        tile = tile_of(
            "<a href='/shop/k11/' title='Swiss K11 Carbine'></a>"
            "<h2 class='elementor-heading-title'>Something Else</h2>"
        )
        assert _extract_title(tile, link_in(tile)) == "Swiss K11 Carbine"

    @pytest.mark.parametrize("tag", ["h1", "h2"])
    def test_then_an_elementor_heading(self, tag):
        tile = tile_of(f"<{tag} class='elementor-heading-title'>Mosin M91/30</{tag}>")
        assert _extract_title(tile, None) == "Mosin M91/30"

    def test_a_heading_holding_the_price_is_not_the_title(self):
        """The same class is reused for the price on some templates, and
        "$599.99" as a product name would reach the browse page."""
        tile = tile_of(
            "<h2 class='elementor-heading-title'>$599.99</h2>"
            "<h2 class='woocommerce-loop-product__title'>Swedish M96</h2>"
        )
        assert _extract_title(tile, None) == "Swedish M96"

    def test_then_the_stock_woocommerce_loop_title(self):
        tile = tile_of("<h2 class='woocommerce-loop-product__title'>Carcano M91</h2>")
        assert _extract_title(tile, None) == "Carcano M91"

    def test_then_the_image_alt_text(self):
        tile = tile_of(f"<img src='{UPLOADS}/x.jpg' alt='Lee Enfield No4 Mk1'>")
        assert _extract_title(tile, None) == "Lee Enfield No4 Mk1"

    def test_and_last_any_heading_long_enough_to_be_a_name(self):
        tile = tile_of("<h3>Yugoslavian M48 Mauser Rifle</h3>")
        assert _extract_title(tile, None) == "Yugoslavian M48 Mauser Rifle"

    def test_a_short_heading_is_a_badge_not_a_name(self):
        tile = tile_of("<h3>SALE</h3>")
        assert _extract_title(tile, None) is None

    def test_nothing_at_all_is_none_rather_than_a_guess(self):
        assert _extract_title(tile_of("<span>no title here</span>"), None) is None


class TestTheSalePriceMustWin:
    """A sale puts the live price in <ins> and the old one in <del>.

    Taking the first amount on the tile records the struck-through price, and
    the next scan then reports a price *drop* that never happened -- straight
    into the watchlist alerts.
    """

    def test_the_ins_price_beats_the_struck_through_one(self):
        tile = tile_of(
            "<del><span class='woocommerce-Price-amount'>$899.99</span></del>"
            "<ins><span class='woocommerce-Price-amount'>$599.99</span></ins>"
        )
        assert _extract_price(tile) == 599.99

    def test_even_when_the_del_comes_second(self):
        tile = tile_of(
            "<ins><span class='woocommerce-Price-amount'>$599.99</span></ins>"
            "<del><span class='woocommerce-Price-amount'>$899.99</span></del>"
        )
        assert _extract_price(tile) == 599.99

    def test_a_plain_price_is_read_normally(self):
        tile = tile_of("<span class='woocommerce-Price-amount'>$1,295.00</span>")
        assert _extract_price(tile) == 1295.0

    def test_a_lone_struck_through_price_is_not_taken(self):
        """Nothing is being asked for it, so there is no price to report."""
        tile = tile_of("<del><span class='woocommerce-Price-amount'>$899.99</span></del>")
        assert _extract_price(tile) is None

    def test_no_price_at_all(self):
        assert _extract_price(tile_of("<span>Call for price</span>")) is None


class TestTheImageMayBeLazyLoaded:
    def test_data_src_is_preferred_over_a_placeholder(self):
        tile = tile_of(f"<img src='data:image/gif;base64,R0lGOD' data-src='{UPLOADS}/real.jpg'>")
        assert _extract_image(tile) == f"{UPLOADS}/real.jpg"

    def test_and_data_lazy_src(self):
        tile = tile_of(f"<img data-lazy-src='{UPLOADS}/real.jpg'>")
        assert _extract_image(tile) == f"{UPLOADS}/real.jpg"

    def test_a_relative_src_is_made_absolute(self):
        tile = tile_of("<img src='/wp-content/uploads/2024/01/x.jpg'>")
        assert (
            _extract_image(tile) == "https://royaltigerimports.com/wp-content/uploads/2024/01/x.jpg"
        )

    def test_an_inline_placeholder_alone_is_no_image(self):
        assert _extract_image(tile_of("<img src='data:image/gif;base64,R0lGOD'>")) is None


class TestOnePhotographReachedTwoWays:
    """WordPress serves every upload at several sizes and renames big ones,
    so the same picture arrives under several URLs and would be stored twice."""

    def test_a_size_suffix_is_stripped(self):
        assert _full_size(f"{UPLOADS}/IMG_2619-1024x346.jpeg") == f"{UPLOADS}/IMG_2619.jpeg"

    def test_a_scaled_upload_is_the_same_photograph(self):
        assert _photo_identity(f"{UPLOADS}/breda-no-mag-scaled.jpg") == _photo_identity(
            f"{UPLOADS}/breda-no-mag.jpg"
        )

    def test_and_so_is_a_resized_one(self):
        assert _photo_identity(f"{UPLOADS}/breda-no-mag-768x512.jpg") == _photo_identity(
            f"{UPLOADS}/breda-no-mag.jpg"
        )

    @pytest.mark.parametrize("name", ["rti-logo.png", "banner.jpg", "placeholder.png", "icon.svg"])
    def test_site_chrome_in_the_uploads_directory_is_not_a_product_photo(self, name):
        assert not _is_product_image(f"{UPLOADS}/{name}")

    def test_a_product_photo_is(self):
        assert _is_product_image(f"{UPLOADS}/swiss-k11-carbine.jpg")

    def test_anything_outside_uploads_is_not(self):
        assert not _is_product_image("https://royaltigerimports.com/theme/hero.jpg")


class TestTheGalleryIsElementorsNotWooCommerces:
    def test_the_full_size_href_is_taken_over_the_thumbnail(self):
        soup = BeautifulSoup(
            f"<a class='e-gallery-item' href='{UPLOADS}/k11-a.jpg'>"
            f"<div><img src='{UPLOADS}/k11-a-300x300.jpg'></div></a>",
            "html.parser",
        )
        gallery = extract_gallery(soup)
        assert f"{UPLOADS}/k11-a.jpg" in gallery
        assert f"{UPLOADS}/k11-a-300x300.jpg" not in gallery

    def test_one_photograph_appears_once(self):
        soup = BeautifulSoup(
            f"<a class='e-gallery-item' href='{UPLOADS}/k11-a.jpg'></a>"
            f"<a class='e-gallery-item' href='{UPLOADS}/k11-a-scaled.jpg'></a>",
            "html.parser",
        )
        assert len(extract_gallery(soup)) == 1


class TestReadingAWholeTile:
    SECTION = Section("Antiques", "https://royaltigerimports.com/shop/", "scroll")

    def _page(self, tiles: str) -> str:
        return f"<html><body>{tiles}</body></html>"

    TILE = (
        "<div class='product'>"
        "<a href='/shop/swiss-k11/' title='Swiss K11 Carbine'></a>"
        "<span class='woocommerce-Price-amount'>$599.99</span>"
        f"<img src='{UPLOADS}/k11.jpg'>"
        "</div>"
    )

    def test_a_tile_becomes_a_listing_keyed_by_its_url(self):
        found = parse_products(self._page(self.TILE), self.SECTION)
        assert list(found) == ["https://royaltigerimports.com/shop/swiss-k11/"]
        item = found["https://royaltigerimports.com/shop/swiss-k11/"]
        assert item.title == "Swiss K11 Carbine"
        assert item.price == 599.99
        assert item.external_key == item.url

    def test_a_tile_with_no_shop_link_is_not_a_product(self):
        assert (
            parse_products(self._page("<div class='product'><h2>Filter</h2></div>"), self.SECTION)
            == {}
        )

    def test_site_furniture_is_skipped_by_title(self):
        tile = (
            "<div class='product'>"
            "<a href='/shop/coa/' title='Certificate of Authenticity'></a>"
            "<span class='woocommerce-Price-amount'>$150.00</span></div>"
        )
        assert parse_products(self._page(tile), self.SECTION) == {}

    def test_consumables_below_the_floor_are_skipped(self):
        cheap = self.TILE.replace("$599.99", f"${MIN_PRICE - 1:.2f}")
        assert parse_products(self._page(cheap), self.SECTION) == {}

    def test_a_section_filter_keeps_only_what_it_names(self):
        section = Section("M1 Carbines", "https://x/", "paged", title_filter="carbine")
        assert parse_products(self._page(self.TILE), section)
        other = self.TILE.replace("Swiss K11 Carbine", "Mosin M91/30")
        assert parse_products(self._page(other), section) == {}

    @pytest.mark.parametrize(
        "container",
        ["div class='jet-listing-grid__item'", "div class='e-loop-item'", "li class='product'"],
    )
    def test_every_container_class_this_site_uses_is_found(self, container):
        tag = container.split()[0]
        inner = self.TILE.replace("<div class='product'>", f"<{container}>").replace(
            "</div>", f"</{tag}>", 1
        )
        soup = BeautifulSoup(self._page(inner), "html.parser")
        assert _find_products(soup), container


def rendered_page() -> str:
    """The captured page, out of the fixture directory."""
    import gzip
    import json
    from pathlib import Path

    directory = Path(__file__).resolve().parent / "fixtures" / "royal-tiger"
    manifest = json.loads((directory / "manifest.json").read_text())
    name = manifest["pages"][0]["file"]
    return gzip.decompress((directory / name).read_bytes()).decode("utf-8")


@pytest.fixture(scope="module")
def parsed():
    """Parsed once: the page is 589 KB and every test below reads the same one."""
    section = Section("Antique", "https://royaltigerimports.com/antiques/", "scroll")
    return parse_products(rendered_page(), section)


class TestAgainstTheRenderedPage:
    """The one thing crafted markup cannot prove: that these selectors still
    match what the shop actually serves.

    The fixture is a page the browser built, captured once. It is not an HTTP
    recording and cannot be one -- this catalog is drawn by JavaScript, so no
    server response contains it. `test_recorded_scrapers.py` skips it for that
    reason and would otherwise open Chrome and go to the shop, which is not
    something a test suite may do.
    """

    def test_the_selectors_still_find_listings(self, parsed):
        """The regression that is silent in production: a theme update moves a
        class, the scan reports success, and the catalog quietly empties."""
        assert parsed, "no tiles matched any of the container selectors"

    def test_every_listing_has_what_the_database_needs(self, parsed):
        for url, item in parsed.items():
            assert item.external_key == url
            assert item.url.startswith("https://royaltigerimports.com/shop/")
            assert item.title and not item.title.startswith("$")

    def test_prices_are_real_amounts(self, parsed):
        for item in parsed.values():
            assert item.price is not None
            assert item.price >= MIN_PRICE

    def test_a_photograph_came_with_each(self, parsed):
        """Their tiles lazy-load, so this is really a test that the
        data-src fallback still matches."""
        assert any(item.image_urls for item in parsed.values())
