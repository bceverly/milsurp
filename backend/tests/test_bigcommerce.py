"""The BigCommerce base class.

The pages are written rather than captured, for the reasons given in
test_woocommerce.py. What is asserted is the shape Stencil renders, plus the
two things that differ from WooCommerce and caused the work: the key, and
pagination by query string.
"""

from __future__ import annotations

import pytest
import responses
from bs4 import BeautifulSoup

from app.scrapers import ScrapeContext
from app.scrapers.base import ScrapeError
from app.scrapers.bigcommerce import BigCommerceScraper, full_size, price_now
from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper
from app.scrapers.storefront import image_sources

SHOP = "https://shop.test"
CDN = "https://cdn11.bigcommerce.com/s-abc/images/stencil"


def card(
    slug: str,
    title: str,
    price_html: str = '<div class="price--withoutTax">$600.00</div>',
    *,
    entity_id: str | None = None,
) -> str:
    attrs = f' data-entity-id="{entity_id}"' if entity_id else ""
    return f"""
    <article class="card"{attrs}>
      <figure class="card-figure">
        <a href="{SHOP}/{slug}/" class="card-figure__link">
          <img class="card-image lazyload"
               data-src="{CDN}/500x659/products/1/2/photo.jpg" alt="{title}"/>
        </a>
      </figure>
      <div class="card-body">
        <h4 class="card-title"><a href="{SHOP}/{slug}/">{title}</a></h4>
        <div class="card-text">{price_html}</div>
      </div>
    </article>
    """


def catalog(cards: str, next_href: str | None = None) -> str:
    nav = (
        f'<ul class="pagination-list"><li class="pagination-item--next">'
        f'<a href="{next_href}">Next</a></li></ul>'
        if next_href
        else ""
    )
    return f"<html><body><ul class='productGrid'>{cards}</ul>{nav}</body></html>"


def product_page(title: str, description: str, images: list[str]) -> str:
    gallery = "".join(f'<img class="productView-image-img" src="{u}"/>' for u in images)
    return f"""
    <html><body>
      <h1 class="productView-title">{title}</h1>
      <div class="productView-image">{gallery}</div>
      <div class="productView-description">{description}</div>
      <dd class="productView-info-value--sku">SKU: L-1</dd>
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


class Shop(BigCommerceScraper):
    slug = "shop-test"
    name = "Shop"
    base_url = f"{SHOP}/"
    description = "A test double."
    sources = ({"category": "Rifles", "url": f"{SHOP}/rifles/"},)


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    """These scrapers hold themselves to one request every five seconds."""
    monkeypatch.setattr("app.scrapers.base.time.sleep", lambda _seconds: None)


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestTheKey:
    """The thing that differs most from WooCommerce.

    WordPress puts a post id in every card. BigCommerce themes are not
    consistent about it, so the id is used where it exists and the product's
    URL path where it does not.
    """

    def parse(self, html: str):
        soup = BeautifulSoup(catalog(html), "html.parser")
        return Shop().item_from_card(soup.select_one("article.card"), f"{SHOP}/rifles/", "Rifles")

    def test_the_shops_own_id_is_preferred(self):
        assert (
            self.parse(card("m1-garand", "M1 Garand", entity_id="46335")).external_key == "bc-46335"
        )

    def test_and_the_url_path_when_there_is_none(self):
        assert self.parse(card("m1-garand", "M1 Garand")).external_key == "path-m1-garand"

    def test_why_the_id_is_preferred(self):
        """A rename changes the URL. On a path key that reads as one listing
        de-listed and another appearing; on the id it is the same listing."""
        before = self.parse(card("m1-garand", "M1 Garand", entity_id="46335"))
        after = self.parse(card("m1-garand-1955", "Correct 1955 M1 Garand", entity_id="46335"))
        assert before.external_key == after.external_key

    def test_a_card_with_no_link_is_not_a_product(self):
        soup = BeautifulSoup(
            '<article class="card"><h4 class="card-title">Sale!</h4></article>', "html.parser"
        )
        assert Shop().item_from_card(soup.select_one("article.card"), SHOP, "Rifles") is None


class TestPrice:
    def price_of(self, html: str):
        # The card itself, not the document: price_now() reads attributes off
        # the card, and Legacy Collectibles carries the number on that element.
        return price_now(BeautifulSoup(html, "html.parser").select_one("article"))

    def test_the_plain_case(self):
        assert (
            self.price_of('<article><div class="price--withoutTax">$1,250.00</div></article>')
            == 1250.00
        )

    def test_a_sale_reports_what_is_being_asked(self):
        """Stencil renders the old price as a struck-through .price--rrp beside
        the live one. Taking the first amount would hide the drop."""
        html = (
            '<article><div class="price--rrp">$800.00</div>'
            '<div class="price--withoutTax">$600.00</div></article>'
        )
        assert self.price_of(html) == 600.00

    def test_a_shop_that_does_not_show_prices(self):
        """Edelweiss Arms is a real example: cards and titles, no prices."""
        assert self.price_of('<article><div class="price-visibility"></div></article>') is None

    def test_a_price_carried_in_an_attribute(self):
        assert self.price_of('<article data-product-price="4495"></article>') == 4495.0


class TestAPhotographIsNeverAnSvg:
    """DuPage Trading's theme puts `.../img/loading.svg` in the `src` of every
    product image and the real photograph in `data-src`.

    Both came back from `image_sources`, so every listing queued a spinner
    beside its photograph and every scan finished PARTIAL: "23 of 46 photo(s)
    could not be fetched". Costless to refuse — the image store rejects an SVG
    on arrival anyway, so nothing that could have been stored is dropped, only
    the attempt and the warning.
    """

    def test_the_spinner_is_not_a_photograph(self):
        tag = BeautifulSoup(
            '<img src="https://cdn11.bigcommerce.com/s-x/stencil/a/e/b/img/loading.svg"'
            ' data-src="https://cdn11.bigcommerce.com/s-x/images/stencil/500x659/'
            'products/780/2857/bayonet.png" />',
            "html.parser",
        ).select_one("img")

        assert image_sources(tag) == [
            "https://cdn11.bigcommerce.com/s-x/images/stencil/500x659/products/780/2857/bayonet.png"
        ]

    def test_any_svg_is_refused_wherever_it_sits(self):
        tag = BeautifulSoup(
            '<img src="https://shop.test/rifle.svg?v=2" />', "html.parser"
        ).select_one("img")
        assert image_sources(tag) == []

    def test_but_a_filename_that_merely_contains_svg_is_a_photograph(self):
        tag = BeautifulSoup(
            '<img src="https://shop.test/svgrifle.jpg" />', "html.parser"
        ).select_one("img")
        assert image_sources(tag) == ["https://shop.test/svgrifle.jpg"]


class TestImages:
    def test_a_stencil_thumbnail_is_asked_for_at_full_size(self):
        assert full_size(f"{CDN}/500x659/products/1/2/photo.jpg") == (
            f"{CDN}/original/products/1/2/photo.jpg"
        )

    def test_a_width_only_size_too(self):
        assert "original" in full_size(f"{CDN}/1280w/products/1/2/photo.jpg")

    def test_a_url_that_is_not_a_stencil_path_is_untouched(self):
        assert full_size("https://example.test/photo.jpg") == "https://example.test/photo.jpg"

    def test_the_lazy_loaded_source_is_found(self):
        soup = BeautifulSoup(catalog(card("x", "Rifle")), "html.parser")
        item = Shop().item_from_card(soup.select_one("article.card"), f"{SHOP}/rifles/", "")
        assert item.image_urls == [f"{CDN}/original/products/1/2/photo.jpg"]


class TestWalkingTheCatalog:
    @responses.activate
    def test_pagination_is_a_query_string_here(self, ctx):
        """Unlike WooCommerce's /page/2/ path form."""
        responses.add(
            responses.GET,
            f"{SHOP}/rifles/",
            body=catalog(card("one", "Rifle One"), next_href=f"{SHOP}/rifles/?page=2"),
        )
        responses.add(responses.GET, f"{SHOP}/rifles/", body=catalog(card("two", "Rifle Two")))
        for slug, title in (("one", "Rifle One"), ("two", "Rifle Two")):
            responses.add(responses.GET, f"{SHOP}/{slug}/", body=product_page(title, "prose", []))

        items = list(Shop().scrape(ctx))

        assert [item.title for item in items] == ["Rifle One", "Rifle Two"]

    @responses.activate
    def test_a_shop_that_disallows_query_strings_stops_rather_than_fails(self, app_config):
        """Which is the rule that ruled out the WooCommerce Store API, and a
        shop is entitled to it."""
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
        responses.add(
            responses.GET,
            f"{SHOP}/rifles/",
            body=catalog(card("one", "Rifle One"), next_href=f"{SHOP}/rifles/?page=2"),
        )
        responses.add(responses.GET, f"{SHOP}/one/", body=product_page("Rifle One", "d", []))

        context = ScrapeContext(config)
        try:
            items = list(Shop().scrape(context))
        finally:
            context.close()

        assert len(items) == 1
        assert any("robots.txt disallows" in warning for warning in context.warnings)

    @responses.activate
    def test_the_product_page_supplies_the_gallery(self, ctx):
        responses.add(responses.GET, f"{SHOP}/rifles/", body=catalog(card("one", "Rifle")))
        responses.add(
            responses.GET,
            f"{SHOP}/one/",
            body=product_page(
                "WWII M1 Garand",
                "Serial number 1234567.",
                [f"{CDN}/500x659/products/1/2/a.jpg", f"{CDN}/1280w/products/1/2/b.jpg"],
            ),
        )

        item = next(iter(Shop().scrape(ctx)))

        assert item.title == "WWII M1 Garand"
        assert "Serial number" in item.description
        assert item.extra["sku"] == "L-1"
        assert item.image_urls == [
            f"{CDN}/original/products/1/2/a.jpg",
            f"{CDN}/original/products/1/2/b.jpg",
        ]
        assert item.images_are_complete is True

    @responses.activate
    def test_the_grid_never_claims_to_be_the_gallery(self, ctx_factory):
        responses.add(responses.GET, f"{SHOP}/rifles/", body=catalog(card("one", "Rifle")))
        context = ctx_factory(needs_detail=lambda _key: False)
        try:
            items = list(Shop().scrape(context))
        finally:
            context.close()

        assert items[0].images_are_complete is False


class TestTheShop:
    def test_legacy_collectibles_leaves_the_parts_section_alone(self):

        urls = [source["url"] for source in LegacyCollectiblesScraper.sources]
        assert not any("parts" in url for url in urls)

    def test_nor_does_it_take_their_modern_retail_stock(self):
        """Their "Modern" sections are Glocks, Sigs and FN SCARs — 43 of them
        on the first run and not one of them surplus. Same call as Arms
        Unlimited. Note these are much narrower sections than `/hand-guns` and
        `/rifles`, which are their collector catalog and *are* read."""
        from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper

        urls = [source["url"] for source in LegacyCollectiblesScraper.sources]
        assert not any("modern" in url for url in urls)

    def test_it_reads_their_catalog_rather_than_three_corners_of_it(self):
        """This list was `/new-firearms/` plus the two antique sections, and
        that was 127 of their 977 listings. `/hand-guns` and `/rifles` are 976
        of them, 860 of which nothing else here reaches."""
        from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper

        urls = [source["url"] for source in LegacyCollectiblesScraper.sources]
        assert any(url.endswith("/hand-guns/") for url in urls)
        assert any(url.endswith("/rifles/") for url in urls)

    def test_the_type_named_sections_come_first(self):
        """A listing is taken by the first source that offers it and that
        source's name becomes the category the classifier trusts over its own
        reading. "Hand Guns" says what "US Military" does not."""
        names = [source["category"] for source in LegacyCollectiblesScraper.sources]
        assert names[:2] == ["Hand Guns", "Long Guns"]
        assert names.index("US Military") > names.index("Hand Guns")

    def test_the_new_arrivals_feed_is_gone(self):
        """A rolling feed de-lists everything that ages off it. Reading it cost
        142 de-listings in one day, of which a sample of 24 found 5 genuinely
        sold — the rest still on sale under sections this now reads. With the
        catalog itself read, its only unique listing was one already sold."""
        from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper

        urls = [source["url"] for source in LegacyCollectiblesScraper.sources]
        assert not any("new-firearms" in url for url in urls)

    def test_their_gear_section_is_left_alone(self):
        """`/discounted-items` is 57 listings unreachable elsewhere and 55 are
        holsters, pouches, binoculars, a Luftwaffe overcoat and a book."""
        from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper

        urls = [source["url"] for source in LegacyCollectiblesScraper.sources]
        assert not any("discounted" in url for url in urls)

    def test_it_does_not_need_a_browser(self):
        from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper

        assert LegacyCollectiblesScraper.requires_browser is False

    def test_it_keeps_the_gentle_default_pace(self):
        from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper

        assert LegacyCollectiblesScraper.min_request_delay >= 5


class TestWhenProductPagesAreRefused:
    """Checkpoint Charlie's, which is why the fallback exists.

    Their category pages answer 200 and their /product/ pages answer 429 to
    every pace and every set of headers — a rule about the path, not about how
    fast we are asking. The scan used to spend an hour escalating its backoff
    and then throw the whole catalog read away.
    """

    def catalog_of(self, count: int) -> str:
        return catalog("".join(card(f"r{n}", f"Rifle {n}") for n in range(count)))

    def refuse_every_product(self, count: int) -> None:
        responses.add(responses.GET, f"{SHOP}/rifles/", body=self.catalog_of(count))
        for n in range(count):
            responses.add(responses.GET, f"{SHOP}/r{n}/", status=429)

    @responses.activate
    def test_the_catalog_entry_survives_a_refused_product_page(self, ctx):
        self.refuse_every_product(1)

        items = list(Shop().scrape(ctx))

        assert [item.title for item in items] == ["Rifle 0"]
        # The card carried these, so they are still worth having.
        assert items[0].price == 600.00
        assert items[0].image_urls == [f"{CDN}/original/products/1/2/photo.jpg"]
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
        asked = {
            call.request.url
            for call in responses.calls
            if f"{SHOP}/rifles/" not in call.request.url
        }
        assert len(asked) == wanted
        assert any("taking the rest of this scan from the catalog only" in w for w in ctx.warnings)

    @responses.activate
    def test_one_that_recovers_is_not_given_up_on(self, ctx, no_global_cooldown):
        """The count is failures *in a row*. A shop having a bad minute in the
        middle of a long catalog should not lose the rest of its galleries."""
        responses.add(responses.GET, f"{SHOP}/rifles/", body=self.catalog_of(4))
        responses.add(responses.GET, f"{SHOP}/r0/", status=429)
        responses.add(responses.GET, f"{SHOP}/r1/", status=429)
        for n in (2, 3):
            responses.add(
                responses.GET,
                f"{SHOP}/r{n}/",
                body=product_page(f"Rifle {n}", "prose", [f"{CDN}/500x659/products/1/2/a.jpg"]),
            )

        items = list(Shop().scrape(ctx))

        assert [item.images_are_complete for item in items] == [False, False, True, True]


class TestWhenACatalogPageIsRefused:
    """Page 3 failing should not throw away pages 1 and 2. See the WooCommerce
    suite for the run that paid for this rule."""

    @responses.activate
    def test_the_pages_already_read_are_kept(self, ctx):
        responses.add(
            responses.GET,
            f"{SHOP}/rifles/",
            body=catalog(card("one", "Rifle One"), next_href=f"{SHOP}/rifles/?page=2"),
        )
        responses.add(responses.GET, f"{SHOP}/rifles/", status=429)
        responses.add(responses.GET, f"{SHOP}/one/", body=product_page("A", "d", []))

        items = list(Shop().scrape(ctx))

        assert [item.title for item in items] == ["A"]
        assert any("Stopping this section at page 1" in w for w in ctx.warnings)

    @responses.activate
    def test_but_a_first_page_that_cannot_be_opened_is_a_failure(self, ctx):
        """Nothing is not a partial result."""
        responses.add(responses.GET, f"{SHOP}/rifles/", status=429)

        with pytest.raises(ScrapeError):
            list(Shop().scrape(ctx))
