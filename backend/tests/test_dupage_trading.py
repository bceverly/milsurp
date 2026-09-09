"""DuPage Trading — the shop's own settings.

The walk belongs to BigCommerce and is covered by test_bigcommerce.py. What is
pinned here is the per-shop judgment a live measurement established and that
nothing in the code would notice going stale.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.bigcommerce import BigCommerceScraper
from app.scrapers.dupage_trading import SITE_BASE, DupageTradingScraper


class TestItIsRegistered:
    def test_the_registry_knows_it(self):
        assert isinstance(get_scraper("dupage-trading"), DupageTradingScraper)

    def test_and_lists_it(self):
        assert DupageTradingScraper in SCRAPER_CLASSES

    def test_it_is_a_bigcommerce_shop(self):
        assert issubclass(DupageTradingScraper, BigCommerceScraper)

    def test_no_browser_is_needed(self):
        assert DupageTradingScraper.requires_browser is False


class TestTheDoubledGrid:
    """Their theme renders each product twice, and the base class's selector
    takes both copies: every `li.product` holds two `article` elements, so 20
    listings arrive as 40.

    The `seen` set would collapse them by key and nothing would be stored
    twice — but the scan log would report double what the shop sells, and a
    count that is wrong in the logs is a count somebody will later trust.
    """

    GRID = """
      <ul class="productGrid">
        <li class="product">
          <article class="card" data-entity-id="780">
            <h4 class="card-title"><a href="/m1-bayonet/">M1 Bayonet</a></h4>
            <div class="price--withoutTax">$85.00</div>
          </article>
          <article class="quickview-shim"><a href="/m1-bayonet/">M1 Bayonet</a></article>
        </li>
      </ul>
    """

    def cards(self, selector):
        return BeautifulSoup(self.GRID, "html.parser").select(selector)

    def test_the_stock_selector_sees_it_twice(self):
        assert len(self.cards(BigCommerceScraper.card_selector)) == 2

    def test_and_this_shops_selector_sees_it_once(self):
        assert len(self.cards(DupageTradingScraper.card_selector)) == 1

    def test_the_card_still_reads(self):
        card = self.cards(DupageTradingScraper.card_selector)[0]
        item = DupageTradingScraper().item_from_card(card, SITE_BASE, "Bayonets")
        assert item is not None
        assert item.title == "M1 Bayonet"
        assert item.price == 85.0
        # The shop's own id, so a rename does not read as a new listing.
        assert item.external_key == "bc-780"


class TestWhatIsRead:
    def test_the_two_sections(self):
        assert [source["category"] for source in DupageTradingScraper.sources] == [
            "Bayonets",
            "Firearms",
        ]

    def test_the_parts_business_is_left_alone(self):
        """Most of the shop. `/parts/` is the barrel, receiver, stock and
        trigger groups of an M1 Garand and an M14; `/rifle-stocks/` is USGI and
        reproduction stocks; `/militaria/` is gear. There is no parts-*kit*
        section, so the rule that admits kits costs nothing here."""
        urls = " ".join(source["url"] for source in DupageTradingScraper.sources)
        for out in ("/parts/", "rifle-stocks", "militaria", "usgi-stocks", "handguards"):
            assert out not in urls

    def test_the_firearms_sub_category_is_not_a_second_source(self):
        """`/firearms/us-military-firearms/` is the same three guns and sits
        under `/firearms/`, so reading both would be one request for nothing."""
        urls = [source["url"] for source in DupageTradingScraper.sources]
        assert f"{SITE_BASE}firearms/" in urls
        assert not any("us-military-firearms" in url for url in urls)


class TestWhatTheirStockClassifiesAs:
    """Titles taken verbatim from the live catalog. Twenty bayonets nearly
    doubles that bucket, which held 24 across the whole catalog before them.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "M1 Bayonet, AFH Marked, Parkerized, *Fair*",
            "M1 Bayonet, ENS Marked, Parkerized, *Very Good*",
            'M1905 Bayonet With M3 Scabbard, 16" *Very Good*',
        ],
    )
    def test_a_bayonet_is_a_bayonet(self, title):
        from app.services import classify

        assert classify.enrich(title, None, 100.0, category="Bayonets")["is_bayonet"] is True

    @pytest.mark.parametrize(
        "title",
        [
            "Springfield Armory M1 Garand, WWII Production, 30-06",
            "Winchester M1 Garand, WWII Production, 30-06",
            "M14 Rifle, 7.62x51 NATO, Criterion Barrel, USGI Parts",
        ],
    )
    def test_and_a_rifle_is_a_rifle(self, title):
        from app.services import classify

        assert classify.enrich(title, None, 1500.0, category="Firearms")["is_rifle"] is True

    @pytest.mark.parametrize(
        "title",
        ["NORWEGIAN M8A1 SCABBARD", "VIETNAM ERA M8A1 SCABBARDS"],
    )
    def test_a_scabbard_alone_is_not_one_on_its_title(self, title):
        """A scabbard is only a bayonet if the listing says so, which is the
        rule `classify._is_a_bayonet` was written around. The section heading
        does not make it one."""
        from app.services import classify

        assert classify.enrich(title, None, 40.0, category="Bayonets")["is_bayonet"] is False

    def test_but_its_description_settles_it(self):
        """Which is why 19 of their 20 are filed as bayonets and not 17: the
        detail fetch supplies the word, and the corroboration rule is doing
        what it is for rather than being worked around."""
        from app.services import classify

        found = classify.enrich(
            "NORWEGIAN M8A1 SCABBARD",
            "Norwegian M8A1 scabbard for the M4 and M5 bayonet, fiberglass body.",
            40.0,
            category="Bayonets",
        )
        assert found["is_bayonet"] is True

    def test_a_fighting_knife_stays_out(self):
        """The one of their twenty that is not a bayonet, and rightly."""
        from app.services import classify

        assert (
            classify.enrich("USMC K-BAR KNIFE", None, 108.0, category="Bayonets")["is_bayonet"]
            is False
        )
