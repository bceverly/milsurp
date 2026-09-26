"""Target Sports USA: every product page read, only what can be bought kept.

Markup below is theirs, trimmed, from September 2026, when all seventeen police
trade-ins were sold out.
"""

from __future__ import annotations

import pytest

from app.scrapers import get_scraper
from app.scrapers.base import ScrapeError
from app.scrapers.target_sports_usa import (
    POLICE,
    SECTION,
    SITE_BASE,
    USED,
    TargetSportsUsaScraper,
    parse_product,
)


def card(product_id, title):
    return (
        f'<li><a href="/{title.lower().replace(" ", "-")}-p-{product_id}.aspx"><span></span>'
        f'<h2>{title}</h2><div class="product-listing-price"></div>'
        '<button class="add-to-cart" type="button">Add To Cart</button></a></li>'
    )


def section(*cards):
    return f'<html><body><ul class="product-list">{"".join(cards)}</ul></body></html>'


def product(name, price, availability="InStock", maker="Glock"):
    return f"""<html><body>
    <div class="product-images"><img itemprop="image"
      src="https://d3gxe0jmvtuxbc.cloudfront.net/images/Product/optimizedimages/1/g.jpg"></div>
    <h1 itemprop="name">{name}</h1>
    <span itemprop="Manufacturer">{maker}</span>
    <div itemprop="offers">
      <span style="display: none;" itemprop="priceCurrency">USD</span>
      <span style="display: none;" itemprop="price">{price}</span>
      <link style="display: none;" itemprop="availability" href="http://schema.org/{availability}">
    </div>
    <div itemprop="description">Used, holster wear.</div>
    </body></html>"""


@pytest.fixture
def shop(ctx_factory):
    def build(pages, *, held=()):
        context = ctx_factory(needs_detail=lambda key: key not in held)

        def fetch(url, **_kwargs):
            if url in pages:
                return pages[url]
            raise ScrapeError(f"404 {url}")

        context.get_text = fetch  # type: ignore[method-assign]
        return context

    return build


def url(product_id, title):
    return f"{SITE_BASE}{title.lower().replace(' ', '-')}-p-{product_id}.aspx"


G22 = "Glock 22 3rd Gen USED Handgun 40 S&W 15 Rounds Black *Police Trade-In"
P229 = "Sig Sauer P229 USED Handgun 40 S&W 12 Rounds DA/SA *Police Trade In"


def scrape(context):
    return {item.external_key: item for item in TargetSportsUsaScraper().scrape(context)}


class TestTheProductPage:
    def test_its_microdata(self):
        found = parse_product(product(G22, "345.00", "SoldOut"))
        assert found["price"] == 345.0
        assert found["available"] is False
        assert found["availability"] == "SoldOut"
        assert found["maker"] == "Glock"
        assert str(found["image"]).endswith("/g.jpg")

    def test_in_stock_is_buyable(self):
        assert parse_product(product(G22, "345.00"))["available"] is True


class TestWhatIsRead:
    def test_only_what_can_be_bought(self, shop):
        items = scrape(
            shop(
                {
                    SECTION: section(card("4410", G22), card("110066", P229)),
                    url("4410", G22): product(G22, "345.00", "InStock"),
                    url("110066", P229): product(P229, "379.99", "SoldOut", "Sig Sauer"),
                }
            )
        )
        assert list(items) == ["4410"]
        item = items["4410"]
        assert (item.price, item.is_sold, item.category) == (345.0, False, POLICE)

    def test_a_listing_we_hold_that_sells_out_is_reported_sold(self, shop):
        items = scrape(
            shop(
                {
                    SECTION: section(card("110066", P229)),
                    url("110066", P229): product(P229, "379.99", "SoldOut", "Sig Sauer"),
                },
                held={"110066"},
            )
        )
        assert items["110066"].is_sold is True

    def test_an_all_sold_out_section_reads_nothing_and_says_why(self, shop):
        lines = []
        context = shop(
            {
                SECTION: section(card("4410", G22)),
                url("4410", G22): product(G22, "345.00", "SoldOut"),
            }
        )
        context.log = lines.append  # type: ignore[method-assign]
        assert scrape(context) == {}
        assert not context.warnings
        assert any("1 sold-out archive" in line for line in lines)

    def test_a_used_gun_that_is_not_a_trade_in_stays_used(self, shop):
        title = "Ruger LCP 380 ACP USED Handgun"
        items = scrape(
            shop({SECTION: section(card("7", title)), url("7", title): product(title, "199.00")})
        )
        assert items["7"].category == USED

    def test_a_full_page_warns_that_there_may_be_more(self, shop):
        cards = [card(str(n), f"Glock {n} Police Trade-In") for n in range(20)]
        pages = {SECTION: section(*cards)}
        pages.update(
            {url(str(n), f"Glock {n} Police Trade-In"): product("G", "300") for n in range(20)}
        )
        context = shop(pages)
        scrape(context)
        assert any("a full page" in warning for warning in context.warnings)

    def test_an_empty_section_is_an_error_not_a_clearance(self, shop):
        with pytest.raises(ScrapeError):
            scrape(shop({SECTION: section()}))

    def test_a_product_page_that_will_not_load_is_skipped(self, shop):
        items = scrape(
            shop(
                {
                    SECTION: section(card("4410", G22), card("110066", P229)),
                    url("110066", P229): product(P229, "379.99", "InStock", "Sig Sauer"),
                }
            )
        )
        assert list(items) == ["110066"]


def test_it_is_registered():
    assert isinstance(get_scraper("target-sports-usa"), TargetSportsUsaScraper)
