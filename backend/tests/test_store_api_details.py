"""Reading descriptions and galleries from WooCommerce's Store API.

A WooCommerce card already carries the product id — it is the `post-N` class
the external key is built from — so a whole page of listings can be filled in
with one `?include=` request instead of one product page each.

Measured against Checkpoint Charlie's, one section, the same twelve listings:

| | requests | time | median description | images |
| --- | --- | --- | --- | --- |
| product pages | 13 | 89.9s | 143 | 152 |
| Store API | 2 | 7.9s | 399 | 152 |

The description difference is the surprising part and the reason this is worth
more than a speed-up. The prose a shop writes lives in WooCommerce's *short*
description, and the themes render only part of it above the fold — so scraping
the page has been quietly losing most of the text.

**The old path is not an error path.** Anything the batch cannot answer for is
asked for the old way, one product page at a time, which is also what every
shop without the flag does for all of them.
"""

from __future__ import annotations

import json

import pytest

from app.scrapers.base import ScrapeError


class FakeContext:
    """Records every URL asked for, and answers from a canned map."""

    def __init__(self, pages: dict[str, str], needs: bool = True):
        self._pages = pages
        self._needs = needs
        self.requested: list[str] = []
        self.warnings: list[str] = []
        self.logs: list[str] = []
        self.scraping = type("S", (), {"max_pages": 10})()

    def check_stop(self) -> None: ...

    def log(self, message: str) -> None:
        self.logs.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def not_read(self, _category: str | None) -> None: ...

    def keep_at_least(self, *_args) -> None: ...

    def allowed(self, _url: str) -> bool:
        return True

    def needs_detail(self, _key: str) -> bool:
        return self._needs

    def get_text(self, url: str) -> str:
        self.requested.append(url)
        if url not in self._pages:
            raise ScrapeError(f"GET {url}: 500")
        return self._pages[url]


CARD = (
    '<li class="post-{n} product type-product">'
    '<a class="woocommerce-loop-product__link" href="https://shop.test/product/p{n}/">'
    '<h2 class="woocommerce-loop-product__title">Card title {n}</h2></a>'
    '<span class="price"><bdi>$100</bdi></span></li>'
)

CATALOG = "https://shop.test/c/guns/"


def catalog_page(*numbers: int) -> str:
    return "<ul>" + "".join(CARD.format(n=n) for n in numbers) + "</ul>"


def record(n: int, **overrides):
    row = {
        "id": n,
        "name": f"API title {n}",
        "sku": f"SKU-{n}",
        "short_description": f"<p>{'the prose a shop writes ' * 5}</p>",
        "description": "<p>**FFL TRANSFER REQUIRED**</p>",
        "images": [
            {"src": f"https://shop.test/wp-content/uploads/{n}-a.jpg"},
            {"src": f"https://shop.test/wp-content/uploads/{n}-b.jpg"},
        ],
    }
    row.update(overrides)
    return row


@pytest.fixture
def shop():
    from app.scrapers.woocommerce import WooCommerceScraper

    class Shop(WooCommerceScraper):
        slug = "shop"
        name = "Shop"
        base_url = "https://shop.test/"
        sources = ({"category": "Guns", "url": CATALOG},)
        store_api_details = True

    return Shop()


def api_url(*numbers: int) -> str:
    ids = ",".join(str(n) for n in numbers)
    return f"https://shop.test/wp-json/wc/store/v1/products?include={ids}&per_page={len(numbers)}"


class TestOneRequestForAPage:
    def test_a_page_of_cards_costs_one_extra_request(self, shop):
        ctx = FakeContext(
            {
                CATALOG: catalog_page(1, 2, 3),
                api_url(1, 2, 3): json.dumps([record(1), record(2), record(3)]),
            }
        )
        items = list(shop.scrape(ctx))

        assert len(items) == 3
        # The catalog page, and the batch. Not one request per listing.
        assert len(ctx.requested) == 2

    def test_nothing_is_asked_for_when_no_detail_is_needed(self, shop):
        """Detail is fetched once per listing ever, so a steady-state scan of a
        catalog it already knows should make no extra request at all."""
        ctx = FakeContext({CATALOG: catalog_page(1, 2)}, needs=False)
        list(shop.scrape(ctx))
        assert ctx.requested == [CATALOG]


class TestWhatItFillsIn:
    @pytest.fixture
    def item(self, shop):
        ctx = FakeContext({CATALOG: catalog_page(7), api_url(7): json.dumps([record(7)])})
        return next(iter(shop.scrape(ctx)))

    def test_the_description_is_the_prose_not_the_boilerplate(self, item):
        """The long `description` on these shops is almost always "FFL TRANSFER
        REQUIRED" and nothing else; the writing is in the short one."""
        assert "the prose a shop writes" in item.description
        assert "FFL TRANSFER" not in item.description

    def test_the_longer_field_wins_rather_than_a_fixed_choice(self, shop):
        """A shop that puts real text in the other field should not be punished
        for it."""
        ctx = FakeContext(
            {
                CATALOG: catalog_page(8),
                api_url(8): json.dumps(
                    [
                        record(
                            8,
                            short_description="<p>short</p>",
                            description="<p>" + "long " * 40 + "</p>",
                        )
                    ]
                ),
            }
        )
        assert "long" in next(iter(shop.scrape(ctx))).description

    def test_the_gallery_comes_across(self, item):
        assert len(item.image_urls) == 2
        assert item.images_are_complete is True

    def test_and_the_sku(self, item):
        assert item.extra["sku"] == "SKU-7"

    def test_the_api_title_beats_the_card_title(self, item):
        """The card truncates; the API does not."""
        assert item.title == "API title 7"

    def test_html_in_the_description_is_rendered_to_text(self, item):
        assert "<p>" not in item.description


class TestFallingBack:
    def test_an_unavailable_api_reads_product_pages_instead(self, shop):
        """Not an error path. The listing still gets its description, from
        where it always came from."""
        ctx = FakeContext(
            {
                CATALOG: catalog_page(1),
                "https://shop.test/product/p1/": (
                    '<h1 class="product_title">Page title</h1>'
                    '<div class="woocommerce-product-details__short-description">'
                    "<p>from the page</p></div>"
                ),
            }
        )
        items = list(shop.scrape(ctx))

        assert items[0].description == "from the page"
        assert "https://shop.test/product/p1/" in ctx.requested

    def test_and_says_so_quietly(self, shop):
        """Logged rather than warned: falling back is a slower way of getting
        the same answer, not a degraded scan."""
        ctx = FakeContext({CATALOG: catalog_page(1), "https://shop.test/product/p1/": "<h1>x</h1>"})
        list(shop.scrape(ctx))
        assert any("Store API unavailable" in line for line in ctx.logs)
        assert ctx.warnings == []

    def test_a_listing_the_batch_skipped_falls_back_on_its_own(self, shop):
        """A partial answer is normal — a product can be deleted between the
        catalog page and the batch — and the rest must not be dragged down."""
        ctx = FakeContext(
            {
                CATALOG: catalog_page(1, 2),
                api_url(1, 2): json.dumps([record(1)]),
                "https://shop.test/product/p2/": (
                    '<div class="woocommerce-product-details__short-description">'
                    "<p>page two</p></div>"
                ),
            }
        )
        items = {item.external_key: item for item in shop.scrape(ctx)}

        assert "the prose a shop writes" in items["post-1"].description
        assert items["post-2"].description == "page two"

    def test_nonsense_from_the_endpoint_does_not_crash_the_scan(self, shop):
        ctx = FakeContext(
            {
                CATALOG: catalog_page(1),
                api_url(1): "not json at all",
                "https://shop.test/product/p1/": "<h1>x</h1>",
            }
        )
        assert len(list(shop.scrape(ctx))) == 1

    def test_a_shop_without_the_flag_never_calls_it(self, shop):
        shop.store_api_details = False
        ctx = FakeContext({CATALOG: catalog_page(1), "https://shop.test/product/p1/": "<h1>x</h1>"})
        list(shop.scrape(ctx))
        assert not any("wp-json" in url for url in ctx.requested)


class TestBatching:
    def test_more_than_a_batch_is_split(self, shop):
        shop.STORE_API_BATCH = 2
        numbers = (1, 2, 3)
        ctx = FakeContext(
            {
                CATALOG: catalog_page(*numbers),
                api_url(1, 2): json.dumps([record(1), record(2)]),
                api_url(3): json.dumps([record(3)]),
            }
        )
        items = list(shop.scrape(ctx))

        assert len(items) == 3
        assert sum("wp-json" in url for url in ctx.requested) == 2
