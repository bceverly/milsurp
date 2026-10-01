"""A WooCommerce shop's catalog read through its Store API.

Checkpoint Charlie's CDN refused its category pages most days, even at one
request every five minutes, and in a month 72 of its roughly 430 listings
reached the catalog. Its C&R tag of 158 listings is two Store API requests.
The listings keep the ``post-N`` keys the page walk gave them, so moving a
shop over neither de-lists nor duplicates anything.
"""

from __future__ import annotations

import json

import pytest

from app.scrapers.base import HostResting, ScrapeError

API = "https://shop.test/wp-json/wc/store/v1/products"


class Response:
    def __init__(self, text: str, pages: int | None = None):
        self.text = text
        self.headers = {} if pages is None else {"X-WP-TotalPages": str(pages)}


class FakeContext:
    def __init__(self, answers: dict[str, object], *, allowed: bool = True):
        self._answers = answers
        self._allowed = allowed
        self.requested: list[str] = []
        self.warnings: list[str] = []
        self.logs: list[str] = []
        self.unread: list[str | None] = []
        self.scraping = type("S", (), {"max_pages": 10})()

    def check_stop(self) -> None: ...

    def log(self, message: str) -> None:
        self.logs.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def not_read(self, category: str | None) -> None:
        self.unread.append(category)

    def keep_at_least(self, *_args) -> None: ...

    def allowed(self, url: str) -> bool:
        return self._allowed or "wp-json" not in url

    def needs_detail(self, _key: str) -> bool:
        return True

    def _answer(self, url: str):
        self.requested.append(url)
        found = self._answers.get(url)
        if isinstance(found, Exception):
            raise found
        if found is None:
            raise ScrapeError(f"GET {url}: 500")
        return found

    def get(self, url: str):
        found = self._answer(url)
        return found if isinstance(found, Response) else Response(str(found))

    def get_text(self, url: str) -> str:
        found = self._answer(url)
        return found.text if isinstance(found, Response) else str(found)


def product(n: int, **overrides):
    row = {
        "id": n,
        "name": f"ENFIELD NO2 .38 S&#038;W #{n}",
        "permalink": f"https://shop.test/product/p{n}/",
        "prices": {"price": "79500", "currency_minor_unit": 2},
        "is_in_stock": True,
        "short_description": f"<p>{'the prose a shop writes ' * 4}</p>",
        "description": "<p>FFL REQUIRED</p>",
        "sku": f"S-{n}",
        "images": [{"src": f"https://shop.test/wp-content/uploads/{n}.jpg"}],
    }
    row.update(overrides)
    return row


def page(*numbers: int, pages: int | None = None, **overrides) -> Response:
    return Response(json.dumps([product(n, **overrides) for n in numbers]), pages)


def api(query: str, number: int = 1) -> str:
    return f"{API}?{query}&per_page=100&page={number}"


@pytest.fixture
def shop():
    from app.scrapers.woocommerce import WooCommerceScraper

    class Shop(WooCommerceScraper):
        slug = "shop"
        name = "Shop"
        base_url = "https://shop.test/"
        sources = (
            {"category": "Curio & Relic", "url": "https://shop.test/product-tag/cr/"},
            {
                "category": "Antique Handguns",
                "url": "https://shop.test/product-category/guns/handguns/antique-handguns/",
            },
        )
        store_api_details = True
        store_api_catalog = True

    return Shop()


class TestTheWalk:
    def test_a_tag_and_a_category_are_one_request_each(self, shop):
        ctx = FakeContext({api("tag=cr"): page(1, 2), api("category=antique-handguns"): page(3)})
        items = list(shop.scrape(ctx))
        assert [item.external_key for item in items] == ["post-1", "post-2", "post-3"]
        assert len(ctx.requested) == 2
        assert [item.category for item in items] == [
            "Curio & Relic",
            "Curio & Relic",
            "Antique Handguns",
        ]

    def test_the_listing_is_complete(self, shop):
        ctx = FakeContext({api("tag=cr"): page(1), api("category=antique-handguns"): page()})
        [item] = list(shop.scrape(ctx))
        assert item.title == "ENFIELD NO2 .38 S&W #1"
        assert (item.price, item.is_sold) == (795.0, False)
        assert item.url == "https://shop.test/product/p1/"
        assert item.description.startswith("the prose a shop writes")
        assert item.image_urls == ["https://shop.test/wp-content/uploads/1.jpg"]
        assert item.images_are_complete

    def test_a_variant_product_is_priced_from_its_range_and_zero_is_none(self, shop):
        ranged = {
            "price": "0",
            "currency_minor_unit": 2,
            "price_range": {"min_amount": "450000", "max_amount": "650000"},
        }
        ctx = FakeContext(
            {
                api("tag=cr"): Response(
                    json.dumps(
                        [
                            product(1, prices=ranged),
                            product(2, prices={"price": "0", "currency_minor_unit": 2}),
                            product(3, prices=None),
                            product(4, prices={"price": "0", "price_range": {"min_amount": "0"}}),
                        ]
                    )
                ),
                api("category=antique-handguns"): page(),
            }
        )
        assert [item.price for item in shop.scrape(ctx)] == [4500.0, None, None, None]

    def test_out_of_stock_is_sold_and_a_backorder_is_not(self, shop):
        ctx = FakeContext(
            {
                api("tag=cr"): Response(
                    json.dumps(
                        [
                            product(1, is_in_stock=False),
                            product(2, is_in_stock=False, is_on_backorder=True),
                        ]
                    )
                ),
                api("category=antique-handguns"): page(),
            }
        )
        assert [item.is_sold for item in shop.scrape(ctx)] == [True, False]

    def test_a_full_page_asks_for_the_next(self, shop):
        full = list(range(1, 101))
        ctx = FakeContext(
            {
                api("tag=cr"): page(*full),
                api("tag=cr", 2): page(101, 102),
                api("category=antique-handguns"): page(),
            }
        )
        assert len(list(shop.scrape(ctx))) == 102
        assert api("tag=cr", 3) not in ctx.requested

    def test_a_section_of_exactly_a_hundred_costs_one_empty_request(self, shop):
        ctx = FakeContext(
            {
                api("tag=cr"): page(*range(1, 101)),
                api("tag=cr", 2): page(),
                api("category=antique-handguns"): page(),
            }
        )
        assert len(list(shop.scrape(ctx))) == 100

    def test_it_goes_through_get_text_which_the_recordings_replay(self, shop):
        """The recordings replace get_text and nothing else. A path that used
        another door reached the live shop from the test suite."""
        ctx = FakeContext({api("tag=cr"): page(1), api("category=antique-handguns"): page()})
        ctx.get = None  # type: ignore[assignment]
        assert len(list(shop.scrape(ctx))) == 1

    def test_one_listing_in_two_sections_is_read_once(self, shop):
        ctx = FakeContext({api("tag=cr"): page(1), api("category=antique-handguns"): page(1)})
        assert len(list(shop.scrape(ctx))) == 1

    def test_unusable_rows_are_skipped(self, shop):
        ctx = FakeContext(
            {
                api("tag=cr"): Response(json.dumps([product(1, name=""), "nonsense", product(2)])),
                api("category=antique-handguns"): page(),
            }
        )
        assert [item.external_key for item in shop.scrape(ctx)] == ["post-2"]


class TestWhenItGoesWrong:
    def test_a_first_page_refused_fails_the_scan(self, shop):
        ctx = FakeContext({api("tag=cr"): ScrapeError("429")})
        with pytest.raises(ScrapeError):
            list(shop.scrape(ctx))

    def test_a_later_page_refused_keeps_what_was_read(self, shop):
        ctx = FakeContext(
            {
                api("tag=cr"): page(*range(1, 101)),
                api("tag=cr", 2): ScrapeError("429"),
                api("category=antique-handguns"): page(500),
            }
        )
        assert len(list(shop.scrape(ctx))) == 101
        assert any("Stopping this section at page 1" in w for w in ctx.warnings)

    def test_a_resting_host_is_a_gap(self, shop):
        resting = HostResting(api("tag=cr"), 60)
        ctx = FakeContext({api("tag=cr"): resting, api("category=antique-handguns"): page(3)})
        assert [item.external_key for item in shop.scrape(ctx)] == ["post-3"]
        assert ctx.unread == ["Curio & Relic"]

    def test_every_section_resting_is_reported_as_resting(self, shop):
        ctx = FakeContext(
            {
                api("tag=cr"): HostResting(api("tag=cr"), 60),
                api("category=antique-handguns"): HostResting(api("tag=cr"), 60),
            }
        )
        with pytest.raises(HostResting):
            list(shop.scrape(ctx))

    def test_no_json_falls_back_to_the_pages(self, shop):
        card = (
            '<li class="post-9 product type-product">'
            '<a class="woocommerce-loop-product__link" href="https://shop.test/product/p9/">'
            '<h2 class="woocommerce-loop-product__title">Card 9</h2></a></li>'
        )
        ctx = FakeContext(
            {
                api("tag=cr"): "<html>not here</html>",
                "https://shop.test/product-tag/cr/": f"<ul>{card}</ul>",
                f"{API}?include=9&per_page=1": json.dumps([product(9)]),
                api("category=antique-handguns"): page(),
            }
        )
        assert [item.external_key for item in shop.scrape(ctx)] == ["post-9"]
        assert any("as pages" in line for line in ctx.logs)

    def test_no_json_on_a_later_page_stops_the_section(self, shop):
        ctx = FakeContext(
            {
                api("tag=cr"): page(*range(1, 101)),
                api("tag=cr", 2): "<html>",
                api("category=antique-handguns"): page(),
            }
        )
        assert len(list(shop.scrape(ctx))) == 100

    def test_an_object_instead_of_a_list(self, shop):
        ctx = FakeContext({api("tag=cr"): json.dumps({"code": "rest_no_route"})})
        with pytest.raises(ScrapeError):
            list(shop.scrape(ctx))
        later = FakeContext(
            {
                api("tag=cr"): page(*range(1, 101)),
                api("tag=cr", 2): json.dumps({"code": "oops"}),
                api("category=antique-handguns"): page(),
            }
        )
        assert len(list(shop.scrape(later))) == 100

    def test_robots_refusing_the_query_reads_pages(self, shop):
        ctx = FakeContext(
            {
                "https://shop.test/product-tag/cr/": "<ul></ul>",
                "https://shop.test/product-category/guns/handguns/antique-handguns/": "<ul></ul>",
            },
            allowed=False,
        )
        assert list(shop.scrape(ctx)) == []
        assert not any("wp-json" in url for url in ctx.requested)


class TestWhichSectionsCan:
    def test_a_url_without_a_category_or_tag_is_walked_as_pages(self, shop):
        assert shop._api_query({"url": "https://shop.test/shop/"}) is None
        assert shop._api_query({"url": "https://shop.test/product-tag/cr/"}) == "tag=cr"
        assert (
            shop._api_query({"url": "https://shop.test/product-category/guns/x-y/"})
            == "category=x-y"
        )

    def test_checkpoint_charlies_reads_its_catalog_through_the_api(self):
        from app.scrapers.checkpoint_charlies import CheckpointCharliesScraper

        scraper = CheckpointCharliesScraper()
        assert scraper.store_api_catalog
        assert all(scraper._api_query(source) for source in scraper.sources)
