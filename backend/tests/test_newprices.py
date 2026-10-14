"""What a variant costs new, from gun.deals (app.services.newprices).

The pages are recorded from gun.deals on 2026-10-10: the price table for a
black 4" Tracker .44 (UPC 725327351238, part 2-440041TKR), the table for the
"Tracker M44C" whose two offers were both out of stock, and the product
search for "taurus tracker 44 magnum". The search for Walther's part 2842475,
which lands on the PDP Full Size's own page, was recorded on 2026-10-13.
"""

from __future__ import annotations

import gzip
from datetime import timedelta
from pathlib import Path

from app.models import ArmoryStatus, FirearmModel, Item, ModelVariant, Site, utcnow
from app.services import newprices

PAGES = Path(__file__).parent / "fixtures" / "gundeals"


def page(name):
    return gzip.decompress((PAGES / name).read_bytes()).decode("utf-8")


class TestReadingAPriceTable:
    def test_the_lowest_in_stock_offer_and_how_many(self):
        found = newprices.offers(
            page("tracker-2-440041TKR.html.gz"), "https://gun.deals/x", "725327351238"
        )
        assert found.low == 462.23
        assert found.stores > 50

    def test_offers_all_out_of_stock_are_no_price(self):
        found = newprices.offers(
            page("m44c-all-out-of-stock.html.gz"), "https://gun.deals/y", "151550022865"
        )
        assert (found.low, found.stores) == (None, 0)

    def test_a_page_with_no_table_says_nothing(self):
        assert newprices.offers("<html></html>", "https://gun.deals/z") is None


class TestFindingAUpcByPartNumber:
    def test_only_the_product_with_exactly_that_part(self):
        html = page("search-tracker-44.html.gz")
        assert newprices._upc_for_part(html, "Z2440041TKR") == "151550022865"
        # The blemished second's part is a different part.
        assert newprices._upc_for_part(html, "2-440041TKR-BLEM") == "000010482716"
        assert newprices._upc_for_part(html, "NOT-A-PART") is None


class TestAPartSearchThatLandsOnTheProduct:
    """Walther's parts, 2026-10-13: the search for "2842475" is the PDP Full
    Size's own page, with no tiles, and all 12 PDP variants went unpriced."""

    def test_its_upc_and_table_are_read(self):
        html = page("walther-pdp-2842475.html.gz")
        assert newprices._upc_for_part(html, "2842475") is None
        assert newprices._product_upc(html, "2842475") == "723364216954"

    def test_a_different_part_is_not_this_product(self):
        assert newprices._product_upc(page("walther-pdp-2842475.html.gz"), "2851229") is None

    def test_the_title_is_what_says_so(self):
        """2844176's page has no mpn markup, and one store's row carries a
        mistyped UPC (13 digits) -- left out of the price, not of the answer."""
        html = (
            "<html><head><title>2844176 - Walther PDP Compact 9mm 723364216176 | gun.deals"
            "</title></head><body><table class='price-compare-table'>"
            "<tr data-price='520.00' data-upc='723364216176'></tr>"
            "<tr data-price='480.00' data-upc='7233642161761'></tr>"
            "<tr data-price='530.00' data-upc=''></tr></table></body></html>"
        )
        assert newprices._product_upc(html, "2844176") == "723364216176"
        assert newprices._product_upc(html, "2844001") is None
        found = newprices.offers(html, "https://gun.deals/p", "723364216176")
        assert (found.low, found.stores) == (520.0, 2)

    def test_a_variant_with_only_a_part_is_priced_from_it(self):
        class Site:
            asked = []

            def get_text(self, url, **_kwargs):
                self.asked.append(url)
                return page("walther-pdp-2842475.html.gz")

        site = Site()
        variant = ModelVariant(label="PDP", maker_part="2842475")
        found = newprices.lookup(site, variant)
        assert found.low == 501.25
        assert found.stores > 50
        assert len(site.asked) == 1


class FakeGunDeals:
    def __init__(self):
        self.asked = []

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        return page("tracker-2-440041TKR.html.gz")

    def keep_at_least(self, *_args):
        pass


def _tracker(session, *, listed=True, checked=None):
    model = FirearmModel(name="Tracker", status=ArmoryStatus.APPROVED, modern_production=True)
    session.add(model)
    session.flush()
    variant = ModelVariant(
        model_id=model.id,
        label='Tracker .44 4" Black',
        upc="725327351238",
        status=ArmoryStatus.APPROVED,
        new_price_checked_at=checked,
    )
    site = Site(slug="np", name="Shop NP", base_url="https://np.test/")
    session.add_all([variant, site])
    session.flush()
    if listed:
        session.add(
            Item(
                site_id=site.id,
                external_key="t",
                url="https://np.test/t",
                title="TAURUS TRACKER PRE OWNED",
                is_pistol=True,
                firearm_model_id=model.id,
                is_active=True,
                is_sold=False,
            )
        )
    session.commit()
    return variant


class TestAsking:
    def test_a_due_variant_is_priced_and_its_source_kept(self, clean_db):
        variant = _tracker(clean_db)
        site = FakeGunDeals()
        counts = newprices.run(clean_db, site, log=lambda _m: None)
        assert counts["priced"] == 1
        clean_db.refresh(variant)
        assert variant.new_price == 462.23
        assert variant.new_price_url == "https://gun.deals/search/apachesolr_search/725327351238"
        assert site.asked == [variant.new_price_url]

    def test_nothing_for_sale_or_asked_today_is_not_asked(self, clean_db):
        _tracker(clean_db, listed=False)
        assert newprices.run(clean_db, FakeGunDeals(), log=lambda _m: None)["asked"] == 0

    def test_an_answer_a_day_old_is_asked_again(self, clean_db):
        _tracker(clean_db, checked=utcnow() - timedelta(hours=2))
        assert newprices.run(clean_db, FakeGunDeals(), log=lambda _m: None)["asked"] == 0
        clean_db.query(ModelVariant).update(
            {"new_price_checked_at": utcnow() - timedelta(hours=25)}
        )
        clean_db.commit()
        assert newprices.run(clean_db, FakeGunDeals(), log=lambda _m: None)["asked"] == 1
