"""Wix Stores — the sixth platform base class.

Two claims are pinned here, because both are the opposite of what this project
believed for years:

1. **A Wix shop needs no browser.** The grid and the product page arrive as
   HTML with the store's data in them; what renders client-side is the
   interactivity. That is the fifth "needs a browser" reading to be wrong here.
2. **The original image is the URL with the transform cut off.** Wix never
   references it, and it is twenty times the size of what the page shows.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.surplus_defense import SurplusDefenseScraper
from app.scrapers.wix_stores import CARD, WixStoresScraper, full_size, gallery

#: The shape Wix emits: its own data-hooks, an out-of-stock card with no price
#: beside an in-stock card with one.
GRID = """
<div data-hook="product-list">
  <li data-hook="product-list-grid-item">
    <div data-hook="product-item-root">
      <a data-hook="product-item-product-details-link" href="/product-page/ibm-corp-m1-carbine-1943"></a>
      <h3 data-hook="product-item-name">IBM Corp. M1 Carbine 1943</h3>
      <span data-hook="product-item-price-to-pay">$1,700.00</span>
    </div>
  </li>
  <li data-hook="product-list-grid-item">
    <div data-hook="product-item-root">
      <a data-hook="product-item-product-details-link" href="/product-page/matching-russian-91-30-tula-1939"></a>
      <h3 data-hook="product-item-name">Matching Russian 91/30 Tula 1939</h3>
      <span data-hook="product-item-out-of-stock">Out of Stock</span>
    </div>
  </li>
</div>
"""


class TestItReadsWixsOwnFurniture:
    """These hooks are Wix's, not a theme's, so they survive a restyle — which
    is more than the CSS selectors the BigCommerce and WooCommerce classes had
    to start from."""

    def cards(self):
        return BeautifulSoup(GRID, "html.parser").select(CARD)

    def test_it_finds_the_cards(self):
        assert len(self.cards()) == 2

    def test_a_card_carries_its_link_name_and_price(self):
        card = self.cards()[0]
        assert (
            card.select_one('[data-hook="product-item-name"]')
            .get_text(strip=True)
            .startswith("IBM")
        )
        assert "$1,700.00" in card.select_one('[data-hook="product-item-price-to-pay"]').get_text()

    def test_out_of_stock_is_how_this_platform_says_sold(self):
        """And it takes the price with it: a card with no price here is gone,
        not "call for price"."""
        card = self.cards()[1]
        assert card.select_one('[data-hook="product-item-out-of-stock"]') is not None
        assert card.select_one('[data-hook="product-item-price-to-pay"]') is None


class TestTheKeyIsTheSlug:
    def build(self, ctx_factory, html=GRID):
        scraper = SurplusDefenseScraper()
        card = BeautifulSoup(html, "html.parser").select(CARD)[0]
        context = ctx_factory(needs_detail=lambda _key: False)
        return scraper._card(context, card, "https://www.surplusdefense.com/surplus-rifles", "R")

    def test_it_comes_from_the_product_page_slug(self, ctx_factory):
        """The slug is what the shop controls; a re-titled listing keeps it,
        and a re-titled listing is the same gun."""
        item = self.build(ctx_factory)
        assert item.external_key == "wix-ibm-corp-m1-carbine-1943"

    def test_the_url_is_absolute(self, ctx_factory):
        item = self.build(ctx_factory)
        assert item.url == "https://www.surplusdefense.com/product-page/ibm-corp-m1-carbine-1943"

    def test_the_price_is_read(self, ctx_factory):
        assert self.build(ctx_factory).price == 1700.0

    def test_a_card_without_a_link_is_skipped(self, ctx_factory):
        html = '<div data-hook="product-item-root"><h3 data-hook="product-item-name">x</h3></div>'
        assert self.build(ctx_factory, html) is None

    def test_and_so_is_one_whose_link_is_not_a_product(self, ctx_factory):
        html = (
            '<div data-hook="product-item-root">'
            '<a data-hook="product-item-product-details-link" href="/about"></a>'
            '<h3 data-hook="product-item-name">About us</h3></div>'
        )
        assert self.build(ctx_factory, html) is None


class TestTheOriginalImageIsTheOneWithoutTheTransform:
    """Wix serves everything through a resizing path and never references the
    original. Cutting from `/v1/` gives it: 1.7MB against 53KB for one M1
    carbine photograph. Hunter's Lodge taught this on the same CDN, where the
    difference was OCR that worked against OCR that returned nothing.
    """

    SIZED = (
        "https://static.wixstatic.com/media/beb2f8_046271e1bb8f4e3681135ba82782c45e~mv2.jpg"
        "/v1/fill/w_1000,h_750,al_c,q_85/file.jpg"
    )
    BARE = "https://static.wixstatic.com/media/beb2f8_046271e1bb8f4e3681135ba82782c45e~mv2.jpg"

    def test_the_transform_is_cut_off(self):
        assert full_size(self.SIZED) == self.BARE

    def test_a_url_without_one_is_left_alone(self):
        assert full_size(self.BARE) == self.BARE

    def test_the_gallery_is_de_duplicated(self):
        """Wix emits each photograph several times — a thumbnail, a main view,
        a zoom — and they all reduce to the same original."""
        markup = f'<img src="{self.SIZED}"><img src="{self.BARE}"><img src="{self.SIZED}">'
        assert gallery(markup) == [self.BARE]

    def test_it_keeps_the_order_the_page_gave(self):
        other = "https://static.wixstatic.com/media/beb2f8_07c2b5682e274c1f97c4b24e9b139bf6~mv2.jpg"
        markup = f'<img src="{self.BARE}"><img src="{other}/v1/fit/w_500,h_500/file.jpg">'
        assert gallery(markup) == [self.BARE, other]

    def test_a_page_with_no_media_yields_nothing(self):
        assert gallery("<html><body>no pictures here</body></html>") == []


class TestSurplusDefense:
    def test_it_is_registered(self):
        assert isinstance(get_scraper("surplus-defense"), SurplusDefenseScraper)
        assert SurplusDefenseScraper in SCRAPER_CLASSES

    def test_it_is_a_wix_shop(self):
        assert issubclass(SurplusDefenseScraper, WixStoresScraper)

    def test_no_browser_is_needed(self):
        """The claim this whole class exists to make."""
        assert SurplusDefenseScraper.requires_browser is False

    def test_the_three_sections_it_reads(self):
        assert {s["path"] for s in SurplusDefenseScraper.sources} == {
            "surplus-rifles",
            "surplus-handguns",
            "edged-weapons",
        }

    def test_edged_weapons_are_read_here_unlike_most_shops(self):
        """An SS dagger and a Type 98 sword are the collectible objects this
        catalog is about, not gear."""
        assert any(s["path"] == "edged-weapons" for s in SurplusDefenseScraper.sources)

    def test_but_they_currently_file_under_other(self):
        """Measured, not assumed, and recorded because it is a gap rather than
        a decision: the classifier has a bayonet bucket and these are not
        bayonets, so all five land with the accessories."""
        from app.services import classify

        for title in ("SS Dagger", "Japanese Imperial Type 98 Sword", "WW2 Kabar USN MK2"):
            derived = classify.enrich(title, None, 800.0, category="Edged Weapons")
            assert not derived["is_bayonet"], f"{title} now reads as a bayonet — update the note"
            assert not (derived["is_rifle"] or derived["is_pistol"])

    @pytest.mark.parametrize(
        "section", ["accessories", "ammunition", "field-gear", "flags-and-armbands"]
    )
    def test_the_gear_sections_are_not(self, section):
        assert not any(section in s["path"] for s in SurplusDefenseScraper.sources)

    def test_their_sold_items_page_is_not_read(self):
        """What it holds is already in the three sections above, marked out of
        stock; reading it too would file each sold rifle twice."""
        assert not any("sold" in s["path"] for s in SurplusDefenseScraper.sources)


class TestAWixShopMayNotUseTheStoreAppItHasInstalled:
    """The Mosin Crate, recorded so the next person does not repeat the
    mistake — mine included.

    Its `/shop-1` answers 200 with 625KB of Wix scaffolding and no product
    hooks, no `/product-page/` links and no prices, and Wix generates a
    `store-products-sitemap.xml` only for a store with stock. Every one of
    those observations is true, and "this shop has nothing to sell" does not
    follow from them: they sell in *prose*, beside group photographs of
    numbered items, in a format regular enough to parse —

        #1  - RIA 1903 12th Cav C&R 30.06 - G   - $1599**SOLD**
        #DC - SMKH Tungsten 15rd Box 8mm  - B   - $259

    41 of their 43 are sold and the two that are not are an AR lower and a box
    of ammunition, so it is refused on stock rather than on emptiness.

    Nothing here talks to the network. What is pinned is that a page with no
    cards yields nothing rather than raising, and stops rather than paging on:
    "no cards" and "the selector broke" must not look the same to the walk, and
    a shop with the app installed and no products in it must not cost thirty
    requests a scan.
    """

    def test_a_page_with_no_cards_yields_no_listings(self):
        soup = BeautifulSoup('<div data-hook="product-list"></div>', "html.parser")
        assert soup.select(CARD) == []

    def test_the_walk_stops_rather_than_paging_forever(self, ctx_factory, monkeypatch):
        scraper = SurplusDefenseScraper()
        pages: list[str] = []

        def fake_get_text(url, **_kwargs):
            pages.append(url)
            return "<html><body>no products here</body></html>"

        context = ctx_factory()
        monkeypatch.setattr(context, "get_text", fake_get_text)
        got = list(scraper._walk(context, {"category": "R", "path": "shop-1"}, set()))

        assert got == []
        assert len(pages) == 1
