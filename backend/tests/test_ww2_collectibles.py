"""WW2 Collectibles: collector rifles and pistols, without the reproductions.

Markup below is the shop's, trimmed, from September 2026.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers import get_scraper
from app.scrapers.ww2_collectibles import (
    SEMI_AUTO_MACHINE_GUNS,
    Ww2CollectiblesScraper,
    description_of,
    full_size,
    gallery,
    item_from_card,
    parse_cards,
    wanted,
)

PAGE = "https://ww2collectibles.com/products/products_list/rifles/"
THUMBS = "https://ww2collectibles.com/media/products/images/products/thumbnails/"


def card(product_id: str, name: str, price: str, *, sold: bool = False, image: str = "") -> str:
    link = (
        f'<a data-id="{product_id}" data-name="{name}" data-position="1" data-price="{price}" '
        f'href="https://ww2collectibles.com/products/products_detail/item_{product_id}/">'
    )
    badge = '<span class="sold-out">SOLD</span>' if sold else ""
    src = image or f"{THUMBS}{product_id}_6aa55b03f2d1f_proimg_500_450.png"
    shown = "SOLD" if sold else f"${price}"
    return (
        f'<div class="shop-product-item"><div class="shop-product-row">{link}'
        f'<img class="cat-thumbnail-container" src="{src}"/></a>'
        f'<span class="prducts-badges-overlay">{badge}<span class="new-product">NEW</span>'
        f'</span></div><div class="shop-product-row"><div class="shop-product-row-inner">'
        f'{link}<div class="shop-product-name">{name}</div><div class="shop-product-price">'
        f"<span>{shown}</span></div></a>{link}Buy Product</a></div></div></div>"
    )


class TestWhatIsRead:
    @pytest.mark.parametrize(
        "title",
        [
            "WW2 German MP38 Semi-Auto Machine Pistol By DK (Authentic Reproduction)",
            "WW2 German STG44 Semi-Auto Machine Gun 8mm kurz By DK (Reproduction)",
            "Kimar Lady K PPK Style Nickel Finish Blank-Firing 8mm PAK Pistol",
        ],
    )
    def test_reproductions_and_blank_firers_are_left_out(self, title):
        assert not wanted(title, "Pistols")

    def test_an_original_is_read(self):
        assert wanted("WW2 German Walther P.38 AC43 Caliber 9mm 1943 Pistol (Original)", "Pistols")

    def test_flare_pistols_stay_for_the_classifier(self):
        assert wanted(
            "WW2 German Erma-Erfurt 1937 LP34 Leuchtpistole Signal Flare Pistol", "Pistols"
        )

    def test_the_semi_auto_section_reads_only_the_guns(self):
        """The rest of it is magazines, loaders and a stock."""
        assert wanted(
            "WW2 Polish PPS43 Semi-Auto  Submachine Gun with 9mm Magazine (Original Kit)",
            SEMI_AUTO_MACHINE_GUNS,
        )
        assert not wanted(
            "WW2 US Thompson 30-Round Cal 45 ACP Stick Magazine by Crosby Co (Original)",
            SEMI_AUTO_MACHINE_GUNS,
        )


class TestTheCards:
    def test_each_card_is_read_once_despite_three_links(self):
        html = card("963", "Arisaka Type 44", "1,295.00") + card("964", "K98", "995.00")
        assert [product_id for product_id, _ in parse_cards(html)] == ["963", "964"]

    def test_a_card_is_a_whole_listing(self):
        [(product_id, tag)] = list(parse_cards(card("963", "Arisaka Type 44", "1,295.00")))
        item = item_from_card(product_id, tag, PAGE, "Rifles")
        assert item is not None
        assert item.external_key == "963"
        assert item.price == 1295.0
        assert not item.is_sold
        assert item.category == "Rifles"
        originals = "https://ww2collectibles.com/media/products/images/products/"
        assert item.image_urls == [f"{originals}963_6aa55b03f2d1f_proimg.png"]

    def test_a_sold_card_keeps_its_last_price(self):
        """The card shows SOLD where the price was; the attribute keeps it."""
        [(product_id, tag)] = list(parse_cards(card("522", "Type 99", "1,695.00", sold=True)))
        item = item_from_card(product_id, tag, PAGE, "Rifles")
        assert item is not None
        assert item.is_sold
        assert item.price == 1695.0

    def test_the_placeholder_is_not_a_photograph(self):
        html = card(
            "963",
            "Arisaka",
            "1,295.00",
            image="https://ww2collectibles.com/media/products/other/product-preview.png",
        )
        [(product_id, tag)] = list(parse_cards(html))
        item = item_from_card(product_id, tag, PAGE, "Rifles")
        assert item is not None
        assert item.image_urls == []

    def test_a_thumbnail_leads_to_its_original(self):
        assert full_size(f"{THUMBS}868_6a877b45bf3ae_proimg_500_450.png").endswith(
            "/images/products/868_6a877b45bf3ae_proimg.png"
        )


PRODUCT = """<html><body>
<img src="https://ww2collectibles.com/media/products/images/products/868_6a877b45bf3ae_proimg.png">
<img src="https://ww2collectibles.com/media/products/images/products/thumbnails/868_6a877b45bf3ae_proimg_100_100.png">
<a href="https://ww2collectibles.com/media/products/images/products/868_6a877b593dfb0_proimg.png">
<img src="https://ww2collectibles.com/media/products/images/products/868_6a877b45bf3ae_proimg.png">
<img src="https://ww2collectibles.com/media/products/images/products/thumbnails/901_6a9_proimg_500_450.png">
<div id="description"><h3>DESCRIPTION</h3><p>WW2 Original German Occupation CZ Model 27</p>
<p><strong>SKU:</strong></p><p>868</p><p><strong>Caliber:</strong></p><p>7.65mm (.32ACP)</p>
</div></body></html>"""


class TestTheProductPage:
    def test_the_gallery_is_this_listing_s_originals_in_order(self):
        assert gallery(PRODUCT, "868", "https://ww2collectibles.com/p/") == [
            "https://ww2collectibles.com/media/products/images/products/868_6a877b45bf3ae_proimg.png",
            "https://ww2collectibles.com/media/products/images/products/868_6a877b593dfb0_proimg.png",
        ]

    def test_the_description_keeps_each_label_with_its_value(self):
        text = description_of(BeautifulSoup(PRODUCT, "html.parser"))
        assert text is not None
        assert not text.startswith("DESCRIPTION")
        assert "Caliber: 7.65mm (.32ACP)" in text


def test_it_is_registered():
    scraper = get_scraper("ww2-collectibles")
    assert isinstance(scraper, Ww2CollectiblesScraper)
    assert scraper.newsletter_url is None and scraper.newsletter_note
