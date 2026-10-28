"""The shops added on 2026-10-28: Silencer Shop and Bereli (suppressors);
Vance Outdoors, Impact Guns, Jim's Firearms and RCF Guns (used guns); Buffalo
Arms (black powder). Each is also replayed from its recording
(test_recorded_scrapers); these pin the parsing rules worth naming."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.scrapers import bereli, impact_guns, jims_firearms, rcf_guns, silencer_shop
from app.scrapers.buffalo_arms import BuffaloArmsScraper
from app.scrapers.vance_outdoors import VanceOutdoorsScraper


def test_silencer_shop_settings_are_escaped_twice():
    page = (
        "window.algoliaConfig = JSON.parse('{\\u0022applicationId\\u0022:\\u0022T6H\\u0022,"
        "\\u0022apiKey\\u0022:\\u0022K\\u003D\\u0022,\\u0022indexName\\u0022:"
        "\\u0022prd_magento2_default\\u0022}');"
    )
    assert silencer_shop.search_settings(page) == {
        "applicationId": "T6H",
        "apiKey": "K=",
        "indexName": "prd_magento2_default",
    }


def test_silencer_shop_backorder_is_for_sale_and_resale_is_used():
    hit = {
        "objectID": "1028",
        "name": "SilencerCo Sparrow 22",
        "url": "https://www.silencershop.com/silencerco-sparrow-22.html",
        "price": {"USD": {"default": 296}},
        "stock_data": {"stock_message": "Backorder", "stock_status": "in_stock"},
        "manufacturer": "SilencerCo",
        "caliber": ".22 LR",
        "is_resale": 1,
    }
    item = silencer_shop.item_from_hit(hit)
    assert not item.is_sold and item.is_new is False and item.category == "NFA Suppressors"
    gone = silencer_shop.item_from_hit({**hit, "stock_data": {"stock_status": "out_of_stock"}})
    assert gone.is_sold


def test_bereli_reads_its_key_from_the_bundle_and_leaves_parts_out():
    bundle = (
        'fetch("https://bereli-instantsearch.opt7dev.com/indexes/product_index/search",'
        '{method:"POST",headers:{Authorization:"Bearer ' + "a" * 64 + '"}})'
    )
    assert bereli.search_settings(bundle) == (
        "https://bereli-instantsearch.opt7dev.com",
        "product_index",
        "a" * 64,
    )
    can = {
        "bigcommerce_id": 541391,
        "product_name": "DEAD AIR NOMAD-LT TI SUPPRESSOR",
        "url": "/dead-air-nomad-lt/",
        "price": 1099,
        "sale_price": 0,
        "inventory_level": 10,
        "product_brand": "Dead Air Armament",
    }
    item = bereli.item_from_hit(can)
    assert item.external_key == "bc-541391" and item.price == 1099.0 and not item.is_sold
    assert bereli.item_from_hit({**can, "product_name": "Dead Air Key Mount"}) is None
    assert bereli.item_from_hit({**can, "inventory_level": 0}).is_sold


def test_vance_reads_stock_in_words():
    scraper = VanceOutdoorsScraper()
    card = BeautifulSoup('<div><span class="product-status">In Stock</span></div>', "html.parser")
    gone = BeautifulSoup(
        '<div><span class="product-status">Notify Me When Available</span></div>', "html.parser"
    )
    assert scraper.card_in_stock(card.div) and not scraper.card_in_stock(gone.div)


def test_impact_keeps_only_what_is_used():
    assert impact_guns.is_not_used("*Demo* Glock 19 Gen 5")
    assert impact_guns.is_not_used("Glock 17 Gen 3 Rebuilt")
    assert impact_guns.is_not_used("Factory Blemished Sig P320")
    assert not impact_guns.is_not_used("Star Firestar Plus M243 Used 9MM")


def test_jims_cards_and_product_page():
    page = (
        '<ul class="product-list-grid"><li class="product-item">'
        '<div class="product-wrapper" data-styleid="100061">'
        '<a class="product-link" href="https://www.jimsfirearms.net/rock-island/m1911-100061">x</a>'
        '<span class="brand">Rock Island</span><h5 class="product-name">Used M1911 A2 .45 ACP</h5>'
        '<span class="salePrice">$429.95</span>'
        '<img src="/prodimages/6138-DEFAULT-m.jpg"></div></li></ul>'
    )
    (item,) = jims_firearms.cards_on(page)
    assert item.external_key == "jims-100061" and item.price == 429.95
    assert item.manufacturer == "Rock Island" and item.is_new is False
    assert item.image_urls == ["https://www.jimsfirearms.net/prodimages/6138-DEFAULT-l.jpg"]
    description, for_sale, _photos = jims_firearms.detail_from(
        '<div class="tab-content">USED ROCK ISLAND Write a Review SUBMIT</div><b>IN STOCK</b>'
    )
    assert description == "USED ROCK ISLAND" and for_sale


def test_rcf_keys_a_tile_by_its_photograph():
    page = (
        '<div class="photoGalleryThumbs"><a data-image-url="https://irp.cdn-website.com/x/'
        'IMG_2306-e8d49ce8.jpeg"></a><div class="caption-title">189.99</div>'
        '<div class="caption-text"><p>Preowned Taurus G3C 9MM with 3 mags.</p></div></div>'
    )
    (item,) = rcf_guns.tiles_on(page, "https://www.rcfguns.com/used-guns", "Used Handguns")
    assert item.external_key == "rcf-img_2306-e8d49ce8"
    assert item.price == 189.99 and item.title == "Preowned Taurus G3C 9MM with 3 mags."
    assert item.url == "https://www.rcfguns.com/used-guns"


def test_buffalo_reads_one_page_a_section():
    assert BuffaloArmsScraper.max_pages_per_source == 1
    assert len(BuffaloArmsScraper.sources) == 11
