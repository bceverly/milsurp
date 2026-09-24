"""How long a gun takes to sell, and the two things that make that honest.

A duration needs two dates, and each was a trap. ``first_seen_at`` is when *we*
first saw a listing, so for anything already on the shelf when we started
watching its shop, the time is only an "at least" -- and averaging floors in
with measurements quietly understates every figure. And nothing recorded when a
listing sold until ``sold_at`` did, so a sale is dated by the scan that saw it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import FirearmModel, Item, ScanRun, ScanStatus, Site
from app.services import market

#: Naive, as every stored timestamp here is: UTC by convention, no tzinfo.
WATCHING = datetime(2026, 9, 1, 12, 0)  # noqa: DTZ001


@pytest.fixture
def shop(clean_db):
    """Two shops, both first scanned on 1 September."""
    sites = [Site(slug=f"s{n}", name=f"Shop {n}", base_url=f"https://s{n}.test/") for n in (1, 2)]
    clean_db.add_all(sites)
    clean_db.flush()
    for site in sites:
        clean_db.add(
            ScanRun(
                site_id=site.id,
                status=ScanStatus.SUCCESS,
                started_at=WATCHING - timedelta(minutes=5),
                finished_at=WATCHING,
                trigger="scheduled",
            )
        )
    model = FirearmModel(name="Swiss K31")
    clean_db.add(model)
    clean_db.commit()
    return clean_db, sites, model


def add(session, site, model, n, *, arrived_days, lasted_days, sold=True, caliber="7.5x55mm"):
    first_seen = WATCHING + timedelta(days=arrived_days)
    left = first_seen + timedelta(days=lasted_days)
    item = Item(
        site_id=site.id,
        external_key=f"{site.slug}-{n}",
        url=f"{site.base_url}{n}",
        title=f"Swiss K31 rifle {n}",
        caliber=caliber,
        firearm_model_id=model.id,
        is_rifle=True,
        first_seen_at=first_seen,
        is_sold=sold,
        sold_at=left if sold else None,
        delisted_at=None if sold else left,
        is_active=sold,
    )
    session.add(item)
    return item


class TestTheFigure:
    def test_the_median_and_quartiles_in_days(self, shop):
        session, (one, two), model = shop
        for n, days in enumerate((2, 4, 6, 8, 10)):
            add(session, one if n % 2 else two, model, n, arrived_days=1, lasted_days=days)
        session.commit()

        result = market.time_to_sell(session, "model")
        (row,) = result.rows
        assert (row.value, row.sold) == ("Swiss K31", 5)
        assert row.median_days == 6.0
        assert (row.fast_days, row.slow_days) == (4.0, 8.0)
        assert row.sites == 2

    def test_leaving_by_de_listing_counts_as_leaving(self, shop):
        """Most shops that sell a gun take it down rather than marking it."""
        session, (one, _two), model = shop
        for n in range(5):
            add(session, one, model, n, arrived_days=1, lasted_days=3, sold=False)
        session.commit()
        assert market.time_to_sell(session, "model").rows[0].median_days == 3.0

    def test_it_can_be_grouped_by_caliber(self, shop):
        session, (one, _two), model = shop
        for n in range(5):
            add(session, one, model, n, arrived_days=1, lasted_days=5)
        session.commit()
        assert market.time_to_sell(session, "caliber").rows[0].value == "7.5x55mm"


class TestWhatIsLeftOut:
    def test_a_listing_there_before_we_started_watching_is_a_floor(self, shop):
        session, (one, _two), model = shop
        for n in range(5):
            add(session, one, model, n, arrived_days=1, lasted_days=5)
        add(session, one, model, 99, arrived_days=-30, lasted_days=40)
        session.commit()

        result = market.time_to_sell(session, "model")
        assert result.floors == 1
        assert result.measured == 5
        assert result.rows[0].median_days == 5.0

    def test_one_already_sold_when_first_seen_is_not_a_sale_we_watched(self, shop):
        session, (one, _two), model = shop
        for n in range(5):
            add(session, one, model, n, arrived_days=1, lasted_days=5)
        add(session, one, model, 99, arrived_days=2, lasted_days=0)
        session.commit()
        assert market.time_to_sell(session, "model").measured == 5

    def test_a_group_under_the_minimum_is_counted_not_shown(self, shop):
        session, (one, _two), model = shop
        for n in range(3):
            add(session, one, model, n, arrived_days=1, lasted_days=5)
        session.commit()
        result = market.time_to_sell(session, "model")
        assert result.rows == []
        assert (result.thin_groups, result.thin_listings) == (1, 3)

    def test_one_shop_s_turnover_is_marked(self, shop):
        session, (one, _two), model = shop
        for n in range(5):
            add(session, one, model, n, arrived_days=1, lasted_days=5)
        session.commit()
        assert market.time_to_sell(session, "model").rows[0].concentrated is True


class TestTheApi:
    def test_it_answers(self, client, admin_headers):
        response = client.get("/api/market/time-to-sell?by=caliber", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["dimension"] == "caliber"

    def test_an_unknown_dimension_is_refused(self, client, admin_headers):
        response = client.get("/api/market/time-to-sell?by=color", headers=admin_headers)
        assert response.status_code == 422
