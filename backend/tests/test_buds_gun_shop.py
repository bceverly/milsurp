"""Bud's Gun Shop's used section (app.scrapers.buds_gun_shop), added
2026-10-27 to catch the used pocket pistols that only sell secondhand. Also
replayed from its recording (test_recorded_scrapers)."""

from __future__ import annotations

from app.scrapers.buds_gun_shop import cards_on, detail_from, page_url


def _card(product_id, name, price_cents, *, section="Pistols", in_stock=True):
    button = "<button>Add to Cart</button>" if in_stock else "<span>Out of Stock</span>"
    return (
        f'<div data-product-id="{product_id}" data-product-name="{name}" '
        f'data-product-category="{section}" data-product-price="{price_cents}">'
        f'<a href="https://www.budsgunshop.com/products/pistols/x-{product_id}">x</a>'
        f"{button}</div>"
    )


def test_the_cards_say_nearly_everything():
    page = (
        _card("752021273", "Used Bersa Thunder .380 ACP, 1 Magazine, No Box", 17999)
        + _card("752021273", "Used Bersa Thunder .380 ACP, 1 Magazine, No Box", 17999)
        + _card("752000001", "Used Raven Arms MP-25 .25 ACP", 12999, in_stock=False)
    )
    items = cards_on(page)
    assert [item.external_key for item in items] == ["buds-752021273", "buds-752000001"]
    bersa, raven = items
    assert bersa.price == 179.99 and bersa.category == "Used Pistols"
    assert bersa.is_new is False and not bersa.is_sold
    assert raven.is_sold
    assert bersa.image_urls == ["https://legacy-images.b-cdn.net/images/752021273_1.jpg"]


def test_the_product_page_adds_the_description_and_maker():
    page = (
        '<div class="syncle-product-specifications">Specifications Caliber 380 ACP '
        "WARNING: This product can expose you to chemicals</div>"
        '<div class="syncle-product-description"><h2>Description</h2>'
        "<p>Used Bersa Thunder</p><p>Rated at 80-90%.&amp;nbsp;</p></div>"
        '<div id="syncle-product-brand">Bersa</div><div id="syncle-stock-status">instock</div>'
        '<img src="https://legacy-images.b-cdn.net/images/752021273_1.jpg">'
        '<img src="https://legacy-images.b-cdn.net/images/752021273_2.jpg">'
    )
    description, maker, sold, photos = detail_from(page, "752021273")
    assert description.startswith("Used Bersa Thunder") and "WARNING" not in description
    assert maker == "Bersa" and sold is False and len(photos) == 2


def test_paging():
    assert page_url(1) == "https://www.budsgunshop.com/categories/firearms/used"
    assert page_url(3).endswith("?page=3")
