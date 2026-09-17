"""The shape of what the current results cost.

The rail had no price control at all: the API has taken `min_price` and
`max_price` since the beginning and nothing on screen ever set them. A reader
had no way to know what a sensible range was, which is the whole reason this
is a histogram and not two number boxes.

Two decisions carry it, and both are held here. **The buckets are log-spaced**,
because a catalog running from a $2 clip pouch to a $750,000 Gatling gun puts
all but a handful of listings in the first column of a linear axis. And **the
histogram ignores the price filter itself**, because a slider shaped by its own
setting redraws as only the slice you chose, leaving nothing on screen to widen
back towards.
"""

from __future__ import annotations

import pytest

from app.models import Item, Site


@pytest.fixture
def catalog(clean_db, seeded):
    session = seeded
    site = Site(slug="p", name="P", base_url="https://p.test/")
    session.add(site)
    session.flush()
    # Three orders of magnitude, which is what the real catalog looks like.
    prices = [20, 25, 30, 400, 450, 500, 550, 600, 7000, 8000, 750000]
    session.add_all(
        Item(
            site_id=site.id,
            external_key=f"k{index}",
            url=f"https://p.test/{index}",
            title=f"Thing {index}",
            current_price=float(price),
            is_active=True,
            is_sold=False,
            caliber="8mm Mauser",
        )
        for index, price in enumerate(prices)
    )
    # And one with no price: "call for price" is common in the trade.
    session.add(
        Item(
            site_id=site.id,
            external_key="callme",
            url="https://p.test/callme",
            title="Call for price",
            current_price=None,
            is_active=True,
            is_sold=False,
            caliber="8mm Mauser",
        )
    )
    session.commit()
    return session


def distribution(client, headers, **params):
    response = client.get("/api/items", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["facets"]["prices"]


class TestTheShape:
    def test_it_spans_the_cheapest_and_dearest(self, catalog, client, admin_headers):
        prices = distribution(client, admin_headers)
        assert prices["low"] == 20
        assert prices["high"] == 750000

    def test_every_listing_lands_in_a_bucket(self, catalog, client, admin_headers):
        prices = distribution(client, admin_headers)
        assert sum(bucket["count"] for bucket in prices["buckets"]) == 11

    def test_the_dearest_is_not_lost_off_the_end_of_its_own_histogram(
        self, catalog, client, admin_headers
    ):
        """The last bucket is closed at the top. Half-open throughout drops the
        maximum, which is the listing most likely to be looked for."""
        prices = distribution(client, admin_headers)
        assert prices["buckets"][-1]["count"] == 1
        assert prices["buckets"][-1]["high"] == pytest.approx(750000)

    def test_the_buckets_are_log_spaced(self, catalog, client, admin_headers):
        """Each is a constant *ratio* wider than the last, not a constant
        amount. On a linear axis ten of these eleven listings would be in the
        first column."""
        buckets = distribution(client, admin_headers)["buckets"]
        ratios = [bucket["high"] / bucket["low"] for bucket in buckets]
        assert max(ratios) == pytest.approx(min(ratios), rel=0.01)
        # And the shape is legible: the bulk is not all in one column.
        occupied = [bucket for bucket in buckets if bucket["count"]]
        assert len(occupied) >= 4

    def test_the_bulk_is_reported_separately_from_the_extremes(
        self, clean_db, seeded, client, admin_headers
    ):
        """The slider opens here. One $750,000 listing should not decide where
        the handles start.

        Its own fixture, and a hundred listings rather than eleven: nearest-rank
        cannot exclude the top 2% of eleven items, so on the small catalog above
        the typical high *is* the high -- correctly, and uninformatively.
        """
        site = Site(slug="bulk", name="Bulk", base_url="https://b.test/")
        seeded.add(site)
        seeded.flush()
        seeded.add_all(
            Item(
                site_id=site.id,
                external_key=f"b{index}",
                url=f"https://b.test/{index}",
                title=f"Rifle {index}",
                current_price=500.0 + index,
                is_active=True,
            )
            for index in range(100)
        )
        seeded.add(
            Item(
                site_id=site.id,
                external_key="gatling",
                url="https://b.test/gatling",
                title="Gatling gun",
                current_price=750000.0,
                is_active=True,
            )
        )
        seeded.commit()

        prices = distribution(client, admin_headers)
        assert prices["high"] == 750000
        assert prices["typical_high"] < 1000

    def test_listings_with_no_price_are_counted_not_hidden(self, catalog, client, admin_headers):
        assert distribution(client, admin_headers)["unpriced"] == 1


class TestWhatItIsComputedOver:
    def test_the_other_filters_narrow_it(self, catalog, client, admin_headers):
        """It describes what is on screen, so a caliber filter reshapes it."""
        assert distribution(client, admin_headers, caliber="8mm Mauser")["low"] == 20
        narrowed = distribution(client, admin_headers, caliber="No Such Caliber")
        assert narrowed is None

    def test_but_the_price_filter_does_not(self, catalog, client, admin_headers):
        """The important one. Shaped by its own setting, narrowing to $400-$600
        would redraw the histogram as only that slice and there would be
        nothing on screen to widen back towards."""
        narrowed = distribution(client, admin_headers, min_price=400, max_price=600)
        assert narrowed["low"] == 20
        assert narrowed["high"] == 750000
        assert sum(bucket["count"] for bucket in narrowed["buckets"]) == 11

    def test_and_the_results_themselves_are_still_filtered(self, catalog, client, admin_headers):
        """So the histogram is the only thing that ignores the range."""
        response = client.get(
            "/api/items", params={"min_price": 400, "max_price": 600}, headers=admin_headers
        )
        assert response.json()["total"] == 5


class TestNothingToShow:
    def test_a_result_set_with_no_prices_has_no_distribution(
        self, clean_db, seeded, client, admin_headers
    ):
        site = Site(slug="q", name="Q", base_url="https://q.test/")
        seeded.add(site)
        seeded.flush()
        seeded.add(
            Item(
                site_id=site.id,
                external_key="x",
                url="https://q.test/x",
                title="No price",
                current_price=None,
                is_active=True,
            )
        )
        seeded.commit()
        assert distribution(client, admin_headers) is None
