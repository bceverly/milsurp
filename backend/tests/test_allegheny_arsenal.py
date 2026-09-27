"""Allegheny Arsenal: a mixed gun shelf, read only where the titles say military.

Titles and markup below are the shop's, from September 2026.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers import get_scraper
from app.scrapers.allegheny_arsenal import AlleghenyArsenalScraper, is_military

CARD = """<article class="card">
<figure class="card-figure">
<div class="stock-badge"><span class="stock-message">Only 1 left in stock</span></div>
<a class="card-figure__link" href="https://mg34.com/product/{slug}/">
<div class="card-img-container"><img class="card-image lazyload"
data-src="https://cdn11.bigcommerce.com/s-vqp74y7o85/images/stencil/300x300/products/{id}/1/a.jpg?c=1"
src="https://cdn11.bigcommerce.com/s-vqp74y7o85/stencil/x/img/loading.svg"/></div></a>
<figcaption class="card-figcaption"><div class="card-figcaption-body">
<a class="button quickview" data-product-id="{id}">Quick view</a>
<a class="button" href="https://mg34.com/cart.php?action=add&amp;product_id={id}">Add to Cart</a>
</div></figcaption></figure>
<div class="card-body"><h4 class="card-title">
<a href="https://mg34.com/product/{slug}/">{title}</a></h4>
<div class="card-text" data-test-info-type="price"><div class="price-section">
<span class="price price--withoutTax">{price}</span></div></div></div>
</article>"""


def card(title: str, *, product_id: str = "3402", price: str = "$795.00"):
    html = CARD.format(slug="a-listing", id=product_id, title=title, price=price)
    return BeautifulSoup(html, "html.parser").select_one("article.card")


class TestWhatIsRead:
    @pytest.mark.parametrize(
        "title",
        [
            "Russian 91/30 Mosin Nagant WWII Surplus 7.62X54",
            "GERMAN P08 30 7.65 Luger DWM Semi Auto Pistol Shooter Grade PRI C&R 3627",
            "British Enfield SMLE No 4 Mk1 (T) 4T Sniper Rifle 303 WWII BSA M47 C&R 3605",
            "Ice House HUNGARIAN M84 PKM Semi Auto 7.62X54 LMG Belt Fed",
            "GERMAN MG34 8MM Pre-May Belt Fed MG Dealer Sample Full Auto Pre-86 Keeper",
            "TRANSFERABLE Full Auto THOMPSON M1A1 45 ACP SMG RLC E-File USGI 1928 Barrel",
            "Antique US Sharps New Model 1863 52 Saddle Ring Carbine Civil War Era #22",
            "GLOCK 17T TRAINER SIMUNITION 9MM FX Police Trade In LE Blue Semi Auto SIM",
            "RARE Portugal FN 38 Belt Fed 8MM Mauser Browning 1919 Semi Auto R.P. FN 30",
        ],
    )
    def test_surplus_and_military_models(self, title):
        assert is_military(title)

    @pytest.mark.parametrize(
        "title",
        [
            "NEW Closeout Remington 700 308 Win Barreled Action 20” Carbine Custom BDL",
            "New Nighthawk Custom DELEGATE 1911 9MM Commander Rail Two Tone Double Stack 2011",
            "Vigilance Rifles M18 WINDRUNNER US 50 BMG Bolt Action Classic Fixed Barrel",
            "Belgian FN SCAR 16S RCH Reciprocating Charging Handle 5.56 NATO 16 BLK 3276",
            'Blaser Tactical LRT UIT 308 Win 24" Straight Pull SIG Import R93 Sniper',
        ],
    )
    def test_not_the_new_retail_stock_beside_them(self, title):
        assert not is_military(title)

    def test_9mm_luger_is_a_caliber_not_a_p08(self):
        assert not is_military('Kriss USA KV90CAP20 Vector CRB 9mm Luger 16" 40 Round')

    @pytest.mark.parametrize(
        "title",
        [
            "NEW Russian Bramit Suppressor Mosin Nagant 91/30 WWII NFA In Stock Ready To Ship",
            "Winchester 1897 Trench Gun Conversion Service WWII (On Your 1897 Shotgun)",
            (
                "COMING SOON. WATCH FOR DETAILS.  NOT AVAILABLE FOR SALE (YET)!!!    NEW Modern "
                "German Mauser K98 98 L27 7.92 8x57 Suppressor WWII NFA"
            ),
        ],
    )
    def test_nor_what_names_a_war_without_being_a_gun_for_sale(self, title):
        assert not is_military(title)


class TestTheCard:
    def test_a_military_listing_is_read_by_its_id(self):
        item = AlleghenyArsenalScraper().item_from_card(
            card("Russian 91/30 Mosin Nagant WWII Surplus 7.62X54", product_id="3551"),
            "https://mg34.com/product-category/guns-for-sale",
            "Guns for Sale",
        )
        assert item is not None
        assert item.external_key == "bc-3551"
        assert item.price == 795.0
        assert item.category == "Guns for Sale"
        assert item.image_urls
        assert "/products/3551/" in item.image_urls[0]
        assert "300x300" not in item.image_urls[0]

    def test_a_modern_one_is_not(self):
        item = AlleghenyArsenalScraper().item_from_card(
            card("NEW Closeout Remington 700 308 Win Barreled Action 20” Carbine"),
            "https://mg34.com/product-category/guns-for-sale",
            "Guns for Sale",
        )
        assert item is None


def test_it_is_registered():
    scraper = get_scraper("allegheny-arsenal")
    assert isinstance(scraper, AlleghenyArsenalScraper)
    assert scraper.newsletter_url and scraper.newsletter_note
