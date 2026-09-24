"""What A Country: thirty parts kits on an older ASP.NET storefront.

What is pinned is what was measured on the live shop: the sale price wins over
the list price, "Starting at" is a price, the stock line on the product page is
the only place a sold kit says so, and the gallery is the product's own photos
rather than the related products shown beneath it.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.what_a_country import WhatACountryScraper, card_price, gallery

CATEGORY = """
<div class="product-list-item">
  <a href="/colt-m16a1-parts-kit.aspx"><img class="product-list-img"
     src="/images/products/thumb/ColtM16A1PartsKit.jpg" /></a>
  <div class="product-list-options">
    <h5><a href="/colt-m16a1-parts-kit.aspx">Colt M16A1 Parts Kit</a></h5>
    <div class="product-list-price">
      <div class="product-list-cost"><span class="product-list-cost-label">Price:</span>
        <span class="product-list-cost-value">$949.95</span></div>
    </div>
  </div>
</div>
<div class="product-list-item">
  <a href="/amd-65-parts-kit.aspx"><img class="product-list-img" src="/images/products/thumb/amd.jpg" /></a>
  <div class="product-list-options">
    <h5><a href="/amd-65-parts-kit.aspx">AMD 65 Parts Kit</a></h5>
    <div class="product-list-price">
      <div class="product-list-cost"><span class="product-list-cost-value">$729.95</span></div>
      <div class="product-list-sale"><span class="product-list-sale-value">$679.95</span></div>
    </div>
  </div>
</div>
<div class="product-list-item">
  <a href="/m1-carbine-parts-kit.aspx"></a>
  <div class="product-list-options">
    <h5><a href="/m1-carbine-parts-kit.aspx">M1 Carbine Parts Kit</a></h5>
    <div class="product-list-cost"><span class="product-list-cost-value">Starting at $579.95</span></div>
  </div>
</div>
"""

PRODUCT = """
<div class="product-detail">
  <div class="prod-detail-stock">{stock}</div>
  <div class="prod-detail-desc">Original Colt M16A1 Parts Kit. Surplus, used, serviceable.</div>
  <img src="/images/products/detail/ColtM16A1PartsKit.JPG" />
  <a href="/images/products/detail/ColtM16A1PartsKit2.JPG">zoom</a>
  <img src="/images/products/detail/ColtM16A1PartsKit.JPG" />
</div>
<div class="product-list-item">
  <img src="/images/products/thumb/AN_PVS_2.jpg" />
  <span class="product-list-cost-value">$476.00</span>
</div>
"""


def cards():
    return BeautifulSoup(CATEGORY, "html.parser").select("div.product-list-item")


class TestItIsRegistered:
    def test_the_registry_knows_it(self):
        assert WhatACountryScraper in SCRAPER_CLASSES
        assert isinstance(get_scraper("what-a-country"), WhatACountryScraper)

    def test_it_reads_only_the_parts_kits(self):
        assert [s["path"] for s in WhatACountryScraper.sources] == ["parts-kits.aspx"]

    def test_it_states_no_facts(self):
        """No caliber, country or maker from the shop -- see states_facts."""
        assert WhatACountryScraper.states_facts is False


class TestTheCategoryCard:
    def parse(self, index):
        return WhatACountryScraper()._card(
            cards()[index], "https://whatacountry.com/parts-kits.aspx", "Parts Kits"
        )

    def test_the_key_is_the_path(self):
        assert self.parse(0).external_key == "wac-colt-m16a1-parts-kit"

    def test_the_url_is_absolute(self):
        assert self.parse(0).url == "https://whatacountry.com/colt-m16a1-parts-kit.aspx"

    def test_the_list_price(self):
        assert self.parse(0).price == 949.95

    def test_a_sale_price_wins(self):
        assert card_price(cards()[1]) == 679.95

    def test_starting_at_is_a_price(self):
        assert card_price(cards()[2]) == 579.95

    def test_the_thumbnail_is_a_preview_only(self):
        item = self.parse(0)
        assert item.image_urls == [
            "https://whatacountry.com/images/products/thumb/ColtM16A1PartsKit.jpg"
        ]
        assert item.images_are_complete is False


class TestTheProductPage:
    def run(self, ctx_factory, monkeypatch, stock):
        scraper = WhatACountryScraper()
        item = scraper._card(cards()[0], "https://whatacountry.com/parts-kits.aspx", "Parts Kits")
        context = ctx_factory()
        monkeypatch.setattr(context, "get_text", lambda _url, **_kw: PRODUCT.format(stock=stock))
        return scraper._detailed(context, item)

    def test_in_stock_is_for_sale(self, ctx_factory, monkeypatch):
        assert self.run(ctx_factory, monkeypatch, "In stock").is_sold is False

    def test_out_of_stock_is_sold(self, ctx_factory, monkeypatch):
        item = self.run(ctx_factory, monkeypatch, "Out of stock — this one just sold.")
        assert item.is_sold is True

    def test_the_description(self, ctx_factory, monkeypatch):
        item = self.run(ctx_factory, monkeypatch, "In stock")
        assert item.description.startswith("Original Colt M16A1 Parts Kit")

    def test_the_gallery_is_its_own_photographs_only(self, ctx_factory, monkeypatch):
        item = self.run(ctx_factory, monkeypatch, "In stock")
        assert item.image_urls == [
            "https://whatacountry.com/images/products/detail/ColtM16A1PartsKit.JPG",
            "https://whatacountry.com/images/products/detail/ColtM16A1PartsKit2.JPG",
        ]
        assert item.images_are_complete is True


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ('<img src="/images/products/detail/a.JPG">', ["a.JPG"]),
        ('<img src="/images/products/thumb/a.JPG">', []),
    ],
)
def test_the_gallery_reads_only_the_detail_folder(markup, expected):
    assert [url.rsplit("/", 1)[1] for url in gallery(markup)] == expected
