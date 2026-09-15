"""Reading one listing's price without scanning its shop.

The watchlist poller re-reads a watched listing every couple of hours where its
catalog is scanned daily, and this is the method that does it. Two generic
layers on the base class, because whether a shop publishes structured data
turns out to depend on its *theme* and not its platform: six BigCommerce shops
publish schema.org and a seventh publishes only an Open Graph meta tag.

Measured against a live product page from all twenty-eight shops. Every price
these layers returned matched what the scan had stored, exactly.
"""

from __future__ import annotations

import json

import pytest

from app.scrapers.base import PriceCheck, ScrapeContext, SiteScraper


class _Shop(SiteScraper):
    slug = "shop"
    name = "Shop"
    base_url = "https://shop.test/"

    def scrape(self, ctx):  # pragma: no cover - not what these tests exercise
        return []


@pytest.fixture
def serving(app_config, monkeypatch):
    """A product page with whatever markup the test wants."""

    def serve(html: str):
        ctx = ScrapeContext(app_config)
        monkeypatch.setattr(ctx, "get_text", lambda _url, **_kw: html)
        return ctx

    return serve


def _ld(**offer) -> str:
    node = {"@type": "Product", "name": "A rifle", "offers": offer}
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head></html>'
    )


class TestTheSchemaOrgLayer:
    def test_a_published_offer_is_the_answer(self, serving):
        ctx = serving(_ld(price="849.99", availability="https://schema.org/InStock"))
        assert _Shop().check_price(ctx, "https://shop.test/x") == PriceCheck(849.99, False)

    def test_and_it_carries_availability(self, serving):
        """The one layer that does, which is why it goes first: a watched rifle
        selling is the thing its watcher most needs to hear."""
        ctx = serving(_ld(price="849.99", availability="https://schema.org/SoldOut"))
        found = _Shop().check_price(ctx, "https://shop.test/x")
        assert found.sold_out is True

    def test_a_numeric_price_reads_the_same_as_a_string(self, serving):
        ctx = serving(_ld(price=849.99))
        assert _Shop().check_price(ctx, "https://shop.test/x").price == 849.99


class TestTheMetaTagLayer:
    @pytest.mark.parametrize(
        "tag",
        [
            '<meta property="product:price:amount" content="1899.99">',
            '<meta property="og:price:amount" content="1899.99">',
            '<meta itemprop="price" content="1899.99">',
        ],
    )
    def test_each_spelling_a_shop_here_actually_uses(self, serving, tag):
        ctx = serving(f"<html><head>{tag}</head></html>")
        assert _Shop().check_price(ctx, "https://shop.test/x").price == 1899.99

    def test_it_never_claims_a_listing_is_sold(self, serving):
        """These tags carry a number and nothing else. False rather than
        unknown is the safe way round: a listing wrongly marked sold is retired
        from the poller and from its watcher's attention, where a missed sale is
        caught by the next catalog scan."""
        ctx = serving('<html><head><meta property="og:price:amount" content="10"></head></html>')
        assert _Shop().check_price(ctx, "https://shop.test/x").sold_out is False

    def test_schema_org_wins_when_a_page_has_both(self, serving):
        """It says more — the availability — so the looser source is the
        fallback rather than an equal."""
        page = _ld(price="849.99", availability="https://schema.org/SoldOut").replace(
            "</head>", '<meta property="og:price:amount" content="1"></head>'
        )
        found = _Shop().check_price(serving(page), "https://shop.test/x")
        assert found == PriceCheck(849.99, True)

    def test_a_page_whose_schema_org_omits_the_price_still_falls_through(self, serving):
        """A Product node with availability and no price is not an answer, and
        must not stop the meta tag being read."""
        page = _ld(availability="https://schema.org/InStock").replace(
            "</head>", '<meta property="og:price:amount" content="42"></head>'
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").price == 42


class TestTheWooCommerceLayer:
    """Two shops publish neither of the above and render WooCommerce markup.

    One of them is Royal Tiger, which is not registered as a WooCommerce shop
    at all: its catalog needs a headless browser and its product pages are
    ordinary server-rendered WooCommerce. Being able to read those without
    starting Chrome is the difference between polling that shop and not.
    """

    def _page(self, body: str) -> str:
        return f"<html><body>{body}</body></html>"

    def test_a_plain_price(self, serving):
        page = self._page(
            '<span class="woocommerce-Price-amount"><bdi>'
            '<span class="woocommerce-Price-currencySymbol">$</span>4,250.00</bdi></span>'
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").price == 4250.0

    def test_a_sale_reports_what_the_shop_is_charging(self, serving):
        """The whole of the care in this layer. A discounted product renders
        the old price in <del> and the new in <ins>, both in spans of the same
        class -- so taking the first match reports the price the shop is *not*
        charging, which for somebody waiting on a number is the one mistake
        that matters."""
        page = self._page(
            '<del><span class="woocommerce-Price-amount">$999.00</span></del>'
            '<ins><span class="woocommerce-Price-amount">$799.00</span></ins>'
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").price == 799.0

    def test_and_never_the_struck_through_one(self, serving):
        """Even with no <ins> beside it, which is a shape a theme may render."""
        page = self._page(
            '<del><span class="woocommerce-Price-amount">$999.00</span></del>'
            '<span class="woocommerce-Price-amount">$799.00</span>'
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").price == 799.0

    def test_the_stock_notice_is_read(self, serving):
        page = self._page(
            '<span class="woocommerce-Price-amount">$799.00</span>'
            '<p class="stock out-of-stock">Out of stock</p>'
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").sold_out is True

    def test_but_only_from_the_stock_element(self, serving):
        """ "Out of stock" occurs in a shop's own prose often enough -- a
        shipping notice, a related-products heading -- that searching the whole
        document would retire live listings."""
        page = self._page(
            '<span class="woocommerce-Price-amount">$799.00</span>'
            "<p>Sorry, some sizes are out of stock this week.</p>"
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").sold_out is False

    def test_a_mini_cart_in_the_header_is_not_the_price(self, serving):
        """Caught live, and it is the failure this whole design exists to
        prevent. A WooCommerce theme renders its header cart with the very same
        class, and an empty one reads "$0.00" -- which is what Royal Tiger
        returned the first time this ran against it. A zero would have looked
        like the largest price drop in the catalog and been mailed to every
        watcher of that rifle.
        """
        page = self._page(
            '<div class="header-cart">'
            '<span class="woocommerce-Price-amount">$0.00</span></div>'
            '<div class="summary entry-summary">'
            '<span class="woocommerce-Price-amount">$599.99</span></div>'
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").price == 599.99

    def test_and_a_zero_is_never_an_answer_even_unscoped(self, serving):
        """Belt as well as braces: nothing here is free, so a zero is a cart
        total, a placeholder, or a variable product before a variant is
        chosen."""
        page = self._page('<span class="woocommerce-Price-amount">$0.00</span>')
        assert _Shop().check_price(serving(page), "https://shop.test/x") is None

    def test_schema_org_still_wins(self, serving):
        page = _ld(price="849.99").replace(
            "</head>",
            '</head><body><span class="woocommerce-Price-amount">$1.00</span></body>',
        )
        assert _Shop().check_price(serving(page), "https://shop.test/x").price == 849.99


class TestWhenAPageSaysNothing:
    def test_none_rather_than_a_guess(self, serving):
        """Fourteen shops publish neither layer. Reading a price out of theme
        markup would eventually mail somebody about a rifle that is not on
        offer, which is worse than telling them a few hours late — so the
        poller skips these and they keep their scan's freshness."""
        ctx = serving("<html><body><p>$349.95</p></body></html>")
        assert _Shop().check_price(ctx, "https://shop.test/x") is None

    def test_malformed_structured_data_is_somebody_else_s_problem(self, serving):
        ctx = serving(
            '<html><head><script type="application/ld+json">{oh no</script></head></html>'
        )
        assert _Shop().check_price(ctx, "https://shop.test/x") is None

    def test_a_meta_tag_with_no_number_in_it(self, serving):
        ctx = serving('<html><head><meta property="og:price:amount" content="POA"></head></html>')
        assert _Shop().check_price(ctx, "https://shop.test/x") is None
