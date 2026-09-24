"""Algolia InstantSearch -- the catalog a widget draws, read the way it reads it.

Botach is the first shop here on it. What is pinned is what was measured
against their index: a hidden record is not a listing, ``in_stock`` is how the
shop says sold, the price is the one after any sale, and a trade-in shelf that
also holds used civilian guns is labeled listing by listing.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.algolia import AlgoliaScraper, price_now
from app.scrapers.botach import BotachScraper
from app.scrapers.planned import PLANNED

CDN = "https://cdn11.bigcommerce.com/s-9j9zreeu/products"


def hit(
    product_id: int,
    name: str = "Lee–Enfield 303 Bolt Action Rifle, Police Trade",  # noqa: RUF001 - theirs
    *,
    price: float = 449.98,
    in_stock: bool = True,
    is_visible: bool = True,
) -> dict:
    return {
        "product_id": product_id,
        "name": name,
        "url": f"/product-{product_id}/",
        "calculated_prices": {"USD": price},
        "prices": {"USD": price},
        "sales_prices": {"USD": 0},
        "in_stock": in_stock,
        "is_visible": is_visible,
        "sku": f"SKU-{product_id}",
        "image_url": f"{CDN}/{product_id}/images/1/main__1.1280.1280.jpg?c=2",
        "product_images": [
            {
                "is_thumbnail": False,
                "url_thumbnail": f"{CDN}/{product_id}/images/2/b__2.200.200.jpg?c=2",
            },
            {
                "is_thumbnail": True,
                "url_thumbnail": f"{CDN}/{product_id}/images/1/main__1.200.200.jpg?c=2",
            },
        ],
    }


def parse(raw: dict, label: str = "Used Guns"):
    return BotachScraper().item_from_hit(raw, label)


class TestItIsRegistered:
    def test_the_registry_knows_it(self):
        assert BotachScraper in SCRAPER_CLASSES
        assert isinstance(get_scraper("botach"), BotachScraper)

    def test_it_is_an_algolia_shop_and_needs_no_browser(self):
        assert issubclass(BotachScraper, AlgoliaScraper)
        assert BotachScraper.requires_browser is False

    def test_it_is_no_longer_coming_soon(self):
        assert "botach" not in {site.slug for site in PLANNED}


class TestTheEndpoint:
    def _query(self, page: int = 0):
        url = BotachScraper().endpoint(page, "categories.lvl1:Firearms > Trade-In / Used Guns")
        parsed = urlparse(url)
        return parsed, {k: v[0] for k, v in parse_qs(parsed.query).items()}

    def test_it_is_a_get_to_the_shops_own_application(self):
        parsed, _ = self._query()
        assert parsed.netloc == "N6QOFUMLJZ-dsn.algolia.net"
        assert parsed.path == "/1/indexes/Botach-Main"

    def test_carrying_the_search_only_key(self):
        _, query = self._query()
        assert query["x-algolia-application-id"] == "N6QOFUMLJZ"
        assert query["x-algolia-api-key"] == BotachScraper.api_key

    def test_one_listing_per_product_not_per_variant(self):
        assert self._query()[1]["distinct"] == "true"

    def test_it_asks_for_the_section_and_only_published_products(self):
        facets = json.loads(self._query()[1]["facetFilters"])
        assert facets == ["categories.lvl1:Firearms > Trade-In / Used Guns", "is_visible:true"]

    def test_paging_is_zero_based(self):
        assert self._query(2)[1]["page"] == "2"


class TestOneRecord:
    def test_the_key_is_the_bigcommerce_one(self):
        assert parse(hit(86720)).external_key == "bc-86720"

    def test_the_url_is_absolute_on_the_shop(self):
        assert parse(hit(86720)).url == "https://botach.com/product-86720/"

    def test_a_hidden_record_is_not_a_listing(self):
        """Eight of Botach's hidden trade-ins sit at exactly $1,000 and 404."""
        assert parse(hit(90113, price=1000, is_visible=False)) is None

    def test_out_of_stock_is_sold(self):
        assert parse(hit(1, in_stock=False)).is_sold is True
        assert parse(hit(1, in_stock=True)).is_sold is False

    def test_the_main_photo_comes_first_and_every_one_is_full_size(self):
        images = parse(hit(5)).image_urls
        assert images[0].endswith("main__1.1280.1280.jpg?c=2")
        assert all(".200.200." not in url for url in images)
        assert len(images) == 2  # the thumbnail is the main photo, de-duplicated

    def test_the_sku_is_kept(self):
        assert parse(hit(7)).extra == {"sku": "SKU-7"}

    @pytest.mark.parametrize("missing", ["product_id", "url", "name"])
    def test_a_record_missing_its_identity_is_skipped(self, missing):
        raw = hit(9)
        raw[missing] = None
        assert parse(raw) is None


class TestMoney:
    def test_the_price_after_any_sale(self):
        raw = hit(1)
        raw["calculated_prices"] = {"USD": 7.98}
        raw["prices"] = {"USD": 9.98}
        assert price_now(raw) == 7.98

    @pytest.mark.parametrize("value", [0, None, "nonsense"])
    def test_no_price_is_none_rather_than_free(self, value):
        raw = hit(1)
        raw["calculated_prices"] = {"USD": value}
        assert price_now(raw) is None


class TestTheShelfIsNotAllPolice:
    """Their "Trade-In / Used Guns" shelf also holds used civilian pistols and an open-box
    Black Rain, so the police-surplus label comes from each listing's title."""

    @pytest.mark.parametrize(
        "name",
        [
            "Remington 870 EXPRESS MAGNUM 20Ga , Police Trade",
            "HK VP9A1F 9mm Pistol w/ 2 17-Round Magazines & Soft Case, Police Demo",
            "SIG Sauer P320 9mm Pistol w/ 2 Magazines & Hard Case, Never Issued, Police Trade-In",
            "Beretta Model 70 European Police Trade-In – .32 ACP Threaded Barrel",  # noqa: RUF001
        ],
    )
    def test_a_police_title_is_filed_as_a_trade_in(self, name):
        assert parse(hit(1, name)).category == "Police Trade-Ins"

    @pytest.mark.parametrize(
        "name",
        [
            "Tanfoglio Defiant Force Plus 9mm Pistol, Used",
            "Black Rain Fallout 15 5.56 Cold War Gray Cerakote Pistol, Brand New, Open Box",
        ],
    )
    def test_anything_else_keeps_the_shelf_name(self, name):
        assert parse(hit(1, name)).category == "Used Guns"


class TestTheWalk:
    def _run(self, ctx_factory, monkeypatch, pages: list[dict], detail: str | None = None):
        scraper = BotachScraper()
        asked: list[str] = []

        def fake_get_text(url, **_kwargs):
            asked.append(url)
            parsed = urlparse(url)
            # The parsed host, not a substring of the URL: CodeQL rightly
            # points out that "algolia.net" in url also matches a query string.
            if (parsed.hostname or "").endswith(".algolia.net"):
                page = int(parse_qs(parsed.query)["page"][0])
                return json.dumps(pages[page])
            return detail or "<html></html>"

        context = ctx_factory()
        monkeypatch.setattr(context, "get_text", fake_get_text)
        monkeypatch.setattr(context, "needs_detail", lambda _key: detail is not None)
        return list(scraper.scrape(context)), asked, context

    def test_it_follows_nb_pages_and_stops(self, ctx_factory, monkeypatch):
        pages = [
            {"hits": [hit(1), hit(2)], "nbPages": 2},
            {"hits": [hit(3)], "nbPages": 2},
        ]
        items, asked, _ = self._run(ctx_factory, monkeypatch, pages)
        assert [i.external_key for i in items] == ["bc-1", "bc-2", "bc-3"]
        assert len(asked) == 2

    def test_the_description_comes_from_the_product_page(self, ctx_factory, monkeypatch):
        page = (
            '<div id="tab-description"><h4>Description</h4>'
            "<p>UNTESTED, UNCHECKED. Import-marked No. 4 Mk I.</p></div>"
        )
        items, _, _ = self._run(
            ctx_factory, monkeypatch, [{"hits": [hit(1)], "nbPages": 1}], detail=page
        )
        assert items[0].description == "UNTESTED, UNCHECKED. Import-marked No. 4 Mk I."

    def test_an_empty_first_page_says_so(self, ctx_factory, monkeypatch):
        items, _, context = self._run(ctx_factory, monkeypatch, [{"hits": [], "nbPages": 0}])
        assert items == []
        assert any("matched nothing" in w for w in context.warnings)
