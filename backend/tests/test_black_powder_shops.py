"""The black powder shops added on 2026-10-24: October Country, Antique Weapon
Store, Cimarron, Veteran Arms, and Collectors Firearms' black powder sections.

October Country, Antique Weapon Store and Cimarron are also replayed from
their recordings (test_recorded_scrapers); Veteran Arms needs a browser, so
its parsers are tested here against a card as Ecwid draws it.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers.antique_weapon_store import AntiqueWeaponStoreScraper, is_not_a_gun
from app.scrapers.base import normalize_whitespace
from app.scrapers.collectors_firearms import CollectorsFirearmsScraper
from app.scrapers.october_country import OctoberCountryScraper
from app.scrapers.veteran_arms import detail_from, ecwid_price, grid_items


def test_a_byte_order_mark_is_not_part_of_a_title():
    assert normalize_whitespace("\ufeffBritish Flintlock Carbine, ca. 1800 ") == (
        "British Flintlock Carbine, ca. 1800"
    )
    assert normalize_whitespace("Brown\u200bBess") == "BrownBess"


# -- Antique Weapon Store ------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "not_a_gun"),
    [
        ("Spanish or Portuguese Breech Loading Bronze Cannon Barrel, 16th C", True),
        ("Wheellock Spanner/Combination Tool", True),
        ("WWII Era British Shermuly Line-Throwing Pistol", True),
        ("British India Pattern \u201cBrown Bess\u201d Musket, Early 19th C", False),
        ("Exquisite Saxon Wheellock Rifle, ca. 1730", False),
        ("Stocking & Company Single Action Pepperbox Pistol. ca. 1850", False),
        ("Wheellock Pistol Holster, German, ca. 1630", True),
        ("Scarce US Model 1863 Lindsay Double Rifle Musket, with Bayonet", False),
        ("US M1861 Rifled Musket by Providence Tool Co.", False),
    ],
)
def test_what_the_firearms_category_files_beside_the_guns(title, not_a_gun):
    assert is_not_a_gun(title) is not_a_gun


def _woo(name, *, in_stock=True, price="99500"):
    return {
        "id": 7,
        "permalink": "https://www.antiqueweaponstore.com/product/x/",
        "name": name,
        "prices": {"price": price, "currency_minor_unit": 2},
        "is_in_stock": in_stock,
    }


def test_an_antique_weapon_store_gun_and_a_tool():
    scraper = AntiqueWeaponStoreScraper()
    item = scraper.item_from_product(_woo("\ufeffBritish Flintlock Carbine, ca. 1800"), "Antique")
    assert item is not None
    assert item.title == "British Flintlock Carbine, ca. 1800"
    assert item.price == 995.0
    assert scraper.item_from_product(_woo("Wheellock Spanner/Combination Tool"), "Antique") is None
    sold = scraper.item_from_product(_woo("US M1816 Flintlock Musket", in_stock=False), "Antique")
    assert sold is not None and sold.is_sold


# -- October Country -----------------------------------------------------------


def _card(title):
    html = (
        '<article class="card" data-entity-id="321">'
        '<figure><a class="card-figure__link" href="https://www.octobercountry.com/x/"></a></figure>'
        f'<h4 class="card-title"><a href="https://www.octobercountry.com/x/">{title}</a></h4>'
        '<span class="price price--withoutTax">$445.00</span></article>'
    )
    return BeautifulSoup(html, "html.parser").select_one("article")


def test_october_country_leaves_out_an_inline_and_marks_the_used_section():
    scraper = OctoberCountryScraper()
    page = "https://www.octobercountry.com/categories/Revolvers/"
    rifle = scraper.item_from_card(
        _card("Traditions Deerhunter Hardwood .50 Cal."), page, "Muzzleloading Rifles"
    )
    assert rifle is not None and rifle.is_new is True
    assert (
        scraper.item_from_card(
            _card("Buckstalker\u2122 XT Northwest Magnum .50 Cal Musket"),
            page,
            "Muzzleloading Rifles",
        )
        is None
    )
    assert (
        scraper.item_from_card(
            _card("Traditions Loading Stand Revolver .44 cal"), page, "Percussion Revolvers"
        )
        is None
    )
    used = scraper.item_from_card(
        _card("Harrington &amp; Richardson Huntsman Musket .58 cal"),
        page,
        "Used Black Powder Guns",
    )
    assert used is not None and used.is_new is False


def test_october_country_reads_the_used_section_first():
    # A gun in both sections keeps the first category it was read under.
    assert OctoberCountryScraper.sources[0]["category"] == "Used Black Powder Guns"


# -- Collectors Firearms -------------------------------------------------------


def test_collectors_firearms_reads_its_black_powder_sections():
    urls = {source["url"] for source in CollectorsFirearmsScraper.sources}
    for path in (
        "antique-long-guns/flintlock-percussion-antique-long-guns/",
        "antique-handguns/flintlock-pistols/",
        "antique-handguns/percussion-pistols/",
        "antique-handguns/percussion-revolvers/",
        "antique-handguns/derringers-pepperboxes/",
        "colt-guns/colt-modern-blackpowder-replicas/",
    ):
        assert f"https://collectorsfirearms.com/product-category/{path}" in urls
    assert len(urls) == len(CollectorsFirearmsScraper.sources)


# -- Veteran Arms --------------------------------------------------------------


def _ecwid_card(product_id, title, price, *, sold=False, labels=()):
    cell = " ec-store-productsGrid-cell-outOfStock" if sold else ""
    badges = "".join(
        f'<div class="ec-label"><div class="label__text">{label}</div></div>' for label in labels
    )
    href = f"/shop/muskets/{title.replace(' ', '-')}-p{product_id}"
    return (
        f'<div class="grid-product grid-product--id-{product_id}{cell}">'
        f'<div class="grid-product__wrap" data-product-id="{product_id}">'
        f'<a class="grid-product__image" data-product-id="{product_id}" href="{href}">'
        f'<div class="grid-product__label">{badges}</div>'
        f'<img class="grid-product__picture" src="https://d2j6dbq0eux0bg.cloudfront.net/'
        f'images/30046368/products/{product_id}/1.jpg"></a>'
        f'<a class="grid-product__title" href="{href}">'
        f'<div class="grid-product__title-inner">{title}</div></a>'
        f'<div class="grid-product__price"><div class="grid-product__price-value '
        f'ec-price-item">{price}</div></div></div></div>'
    )


def test_ecwid_prices_grouped_by_a_space():
    assert ecwid_price("$5&nbsp;950.00".replace("&nbsp;", "\xa0")) == 5950.0
    assert ecwid_price("$5 950.00") == 5950.0
    assert ecwid_price("$959.00") == 959.0
    assert ecwid_price(None) is None


def test_veteran_arms_reads_the_grid_ecwid_draws():
    page = (
        "<div class='grid'>"
        + _ecwid_card(
            207413996, "Early Matchlock Arquebus", "$920.00", sold=True, labels=["Sold out"]
        )
        + _ecwid_card(207442763, "1768 Charleville", "$959.00", labels=["Back in Stock"])
        + _ecwid_card(
            207450001,
            "Original Late 18th Century French Flintlock Pistol",
            "$2\xa0900.00",
            labels=["Consignment"],
        )
        + "</div>"
    )
    items = grid_items(page, "Muskets")
    assert [item.external_key for item in items] == [
        "ecwid-207413996",
        "ecwid-207442763",
        "ecwid-207450001",
    ]
    arquebus, charleville, original = items
    assert arquebus.is_sold and not charleville.is_sold and not original.is_sold
    assert charleville.url == "https://veteranarms.com/shop/muskets/1768-Charleville-p207442763"
    assert charleville.price == 959.0 and original.price == 2900.0
    assert charleville.is_new is True and original.is_new is False
    assert charleville.image_urls and not charleville.images_are_complete


def test_veteran_arms_product_page():
    page = (
        '<div class="product-details"><div class="product-details__description">'
        "1768 Charleville Store / Muskets Product Details History Following the close "
        "of the French &amp; Indian War, France adopted the 1763 Charleville.</div>"
        '<img class="details-gallery__picture" src="https://d2j6dbq0eux0bg.cloudfront.net/a.jpg">'
        "</div>"
    )
    description, photos = detail_from(page)
    assert description is not None and description.startswith("History Following the close")
    assert photos == ["https://d2j6dbq0eux0bg.cloudfront.net/a.jpg"]
