"""Sportsman's Outdoor Superstore: in-stock listings only, and sales noticed.

The markup below is theirs, trimmed, from September 2026. Their two sections
list 1,895 products of which about 20 can be bought; the rest are "No Longer
Available" pages kept up with an undated last price. So a card is read when it
says In Stock, or when it is a listing we already hold (then it has sold).
"""

from __future__ import annotations

import json

import pytest

from app.scrapers import get_scraper
from app.scrapers.base import ScrapeError
from app.scrapers.sportsmans_outdoor import (
    CATEGORY_BASE,
    POLICE_IN_USED,
    SITE_BASE,
    SportsmansOutdoorScraper,
)
from app.services import classify

GLOCKS = f"{CATEGORY_BASE}police-trade-in-glocks"
USED = f"{CATEGORY_BASE}used-firearms"


def card(product_id, title, price, *, in_stock, suggested=None, brand="Glock"):
    stock = (
        '<div class="prd-in-stk-ctn"><span class="glyphicon glyphicon-ok"></span> In Stock</div>'
        if in_stock
        else ""
    )
    sugg = f'<span class="sugg-price"> {suggested} </span>' if suggested else ""
    url = f"{SITE_BASE}products2.cfm/ID/{product_id}/sku/{title.lower().replace(' ', '-')}"
    return f"""
    <div itemscope itemtype="http://schema.org/Product" class="prd-ctn">
      <div class="prd-ctn-img"><a href="{url}">
        <img class="img-responsive" itemprop="image" src="/prodimages/{product_id}-DEFAULT-m.jpg">
      </a></div>
      <div class="prd-info">
        <h2><a href="{url}"><span itemprop="name"> {title} </span></a></h2>
        <div itemprop="offers" itemscope itemtype="http://schema.org/Offer" class="prd-det-ctn">
          <ul class="list-unstyled"><li>{sugg}
            <span class="price" itemprop="price"> {price} </span></li></ul>
          {stock}
        </div>
        <div class="prd-det-ctn"><ul><li>Brand:
          <a itemprop="brand" itemscope itemtype="http://schema.org/Brand" href="#">
            <span itemprop="name"> {brand} </span></a></li></ul></div>
      </div>
    </div>"""


def page(*cards, next_page=None):
    nav = f'<a href="{next_page}">Next</a>' if next_page else ""
    return f"<html><body>{''.join(cards)}{nav}</body></html>"


def product_page(availability="InStock", *, alt_images=("a.jpg", "b.jpg")):
    node = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "image": f"{SITE_BASE}prodimages/1-DEFAULT-l.jpg",
        "description": "These photos represent the overall condition of these Glock 17s.",
        "offers": {"@type": "Offer", "availability": f"https://schema.org/{availability}"},
    }
    alts = "".join(f'<img src="/prodimages/alt_images/{name}">' for name in alt_images)
    # And a "you may also like" thumbnail that is not this product's.
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head>'
        f'<body><img src="/prodimages/1-DEFAULT-l.jpg">{alts}'
        f'<img src="/prodimages/999-DEFAULT-M.jpg"></body></html>'
    )


@pytest.fixture
def shop(ctx_factory):
    """A context over a fixed set of pages, holding the given listing ids."""

    def build(pages, *, held=()):
        context = ctx_factory(needs_detail=lambda key: key not in held)

        def fetch(url, **_kwargs):
            if url in pages:
                return pages[url]
            if "/products2.cfm/" in url:
                return product_page()
            raise ScrapeError(f"404 {url}")

        context.get_text = fetch  # type: ignore[method-assign]
        return context

    return build


def scrape(context):
    return {item.external_key: item for item in SportsmansOutdoorScraper().scrape(context)}


class TestWhatIsRead:
    def test_an_in_stock_card_is_read_and_an_archived_one_is_not(self, shop):
        items = scrape(
            shop(
                {
                    GLOCKS: page(
                        card(
                            "1",
                            "Glock 17 Gen4 9mm Police Trade-in Pistol",
                            "$359.99",
                            in_stock=True,
                        ),
                        card(
                            "2", "Glock 22 40 S&W Police Trades (Gen4)", "$392.67", in_stock=False
                        ),
                    ),
                    USED: page(),
                }
            )
        )
        assert list(items) == ["1"]
        assert items["1"].is_sold is False

    def test_a_listing_we_hold_that_goes_silent_has_sold(self, shop):
        """Left out, it would read as de-listed; the shop still shows it, as
        no longer available."""
        items = scrape(
            shop(
                {
                    GLOCKS: page(card("2", "Glock 22 Police Trades", "$392.67", in_stock=False)),
                    USED: page(),
                },
                held={"2"},
            )
        )
        assert items["2"].is_sold is True

    def test_the_asking_price_not_the_suggested_one(self, shop):
        items = scrape(
            shop(
                {
                    GLOCKS: page(
                        card(
                            "1",
                            "Glock 17 Police Trade-in",
                            "$359.99",
                            suggested="$399.99",
                            in_stock=True,
                        )
                    ),
                    USED: page(),
                }
            )
        )
        assert items["1"].price == 359.99

    def test_pages_are_followed_until_there_is_no_next(self, shop):
        items = scrape(
            shop(
                {
                    GLOCKS: page(
                        card("1", "Glock 17 Police Trade-in", "$359.99", in_stock=True),
                        next_page=f"{GLOCKS}/currentpage/2",
                    ),
                    f"{GLOCKS}/currentpage/2": page(
                        card("3", "Glock 19 Police Trade-in", "$399.99", in_stock=True)
                    ),
                    USED: page(),
                }
            )
        )
        assert sorted(items) == ["1", "3"]

    def test_a_listing_in_both_sections_is_read_once_under_the_glock_one(self, shop):
        glock = card("1", "Glock 17 Police Trade-in", "$359.99", in_stock=True)
        items = scrape(shop({GLOCKS: page(glock), USED: page(glock)}))
        assert items["1"].category == "Police Trade-In Glocks"

    def test_an_empty_catalog_is_an_error_not_a_clearance(self, shop):
        with pytest.raises(ScrapeError):
            scrape(shop({GLOCKS: page(), USED: page()}))


class TestPoliceSurplus:
    @pytest.mark.parametrize(
        ("title", "category"),
        [
            ("Remington 870 Police Magnum 12GA Police Trade-In Shotgun", POLICE_IN_USED),
            ("Glock MODEL 23 40 S&W POLICE TRADES (GEN3)", POLICE_IN_USED),
            ("Bulgaria Makarov 9x18mm Makarov Surplus Pistols", "Used Firearms"),
        ],
    )
    def test_used_guns_are_filed_by_what_their_title_says(self, shop, title, category):
        items = scrape(
            shop({GLOCKS: page(), USED: page(card("5", title, "$499.99", in_stock=True))})
        )
        assert items["5"].category == category

    @pytest.mark.parametrize("category", ["Police Trade-In Glocks", POLICE_IN_USED])
    def test_both_names_carry_the_flag(self, category):
        assert classify._is_police_surplus(category, is_firearm=True)

    def test_and_the_plain_used_section_does_not(self):
        assert not classify._is_police_surplus("Used Firearms", is_firearm=True)


class TestTheProductPage:
    def test_it_adds_the_description_and_this_listing_s_own_photos(self, shop):
        items = scrape(
            shop(
                {
                    GLOCKS: page(card("1", "Glock 17 Police Trade-in", "$359.99", in_stock=True)),
                    USED: page(),
                }
            )
        )
        item = items["1"]
        assert "overall condition" in (item.description or "")
        assert item.image_urls == [
            f"{SITE_BASE}prodimages/1-DEFAULT-l.jpg",
            f"{SITE_BASE}prodimages/alt_images/a.jpg",
            f"{SITE_BASE}prodimages/alt_images/b.jpg",
        ]
        assert item.images_are_complete is True

    def test_a_listing_already_held_is_not_fetched_again(self, shop):
        fetched = []
        context = shop(
            {
                GLOCKS: page(card("1", "Glock 17 Police Trade-in", "$359.99", in_stock=True)),
                USED: page(),
            },
            held={"1"},
        )
        inner = context.get_text

        def counting(url, **kwargs):
            fetched.append(url)
            return inner(url, **kwargs)

        context.get_text = counting  # type: ignore[method-assign]
        scrape(context)
        assert not any("/products2.cfm/" in url for url in fetched)

    def test_a_product_page_that_will_not_load_keeps_the_card(self, shop):
        context = shop(
            {
                GLOCKS: page(card("1", "Glock 17 Police Trade-in", "$359.99", in_stock=True)),
                USED: page(),
            }
        )
        inner = context.get_text

        def refuse_products(url, **kwargs):
            if "/products2.cfm/" in url:
                raise ScrapeError("503")
            return inner(url, **kwargs)

        context.get_text = refuse_products  # type: ignore[method-assign]
        items = scrape(context)
        assert items["1"].image_urls == [f"{SITE_BASE}prodimages/1-DEFAULT-l.jpg"]
        assert items["1"].images_are_complete is False


def test_it_is_registered():
    assert isinstance(get_scraper("sportsmans-outdoor"), SportsmansOutdoorScraper)
