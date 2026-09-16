"""A week in review of the catalog.

The thing worth pinning down is that this is **not** the per-user digest: no
preferences are applied, every signed-in user gets the same answer, and it
carries the three things the digest cannot -- what left, which shops were
quiet, and what the catalog learned.

The quiet-shop test is the one that earns its keep. A site that produced
nothing all week is either a slow vendor or a broken scraper, and if the page
drops it from the table there is nothing on screen to notice.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Item, ScanRun, ScanStatus, Site, utcnow
from app.services import changes


@pytest.fixture
def catalog(clean_db, seeded):
    """Two shops, one busy and one that has not moved in a month."""
    session = seeded
    busy = Site(slug="busy-shop", name="Busy Shop", base_url="https://busy.test", enabled=True)
    quiet = Site(slug="quiet-shop", name="Quiet Shop", base_url="https://quiet.test", enabled=True)
    session.add_all([busy, quiet])
    session.flush()

    now = utcnow()
    inside = now - timedelta(days=2)
    outside = now - timedelta(days=40)

    def item(site, key, **kwargs):
        defaults = {
            "site_id": site.id,
            "external_key": key,
            "url": f"{site.base_url}/{key}",
            "title": f"{site.name} {key}",
            "first_seen_at": inside,
            "last_seen_at": now,
            "is_active": True,
            "is_sold": False,
            "currency": "USD",
        }
        defaults.update(kwargs)
        return Item(**defaults)

    session.add_all(
        [
            item(busy, "new-1", current_price=200.0),
            item(busy, "new-2", current_price=9000.0, caliber="11mm Gras", country="France"),
            # Arrived before the window: counts towards "listed now" and not
            # towards "arrived".
            item(busy, "old-1", first_seen_at=outside, current_price=150.0),
            item(
                busy,
                "sold-1",
                first_seen_at=outside,
                is_sold=True,
                is_active=False,
                last_seen_at=inside,
            ),
            item(
                busy,
                "gone-1",
                first_seen_at=outside,
                is_active=False,
                delisted_at=inside,
            ),
            item(
                busy,
                "cut-1",
                first_seen_at=outside,
                current_price=500.0,
                previous_price=800.0,
                price_changed_at=inside,
            ),
            # A reduction too small to be worth a line.
            item(
                busy,
                "cut-2",
                first_seen_at=outside,
                current_price=99.0,
                previous_price=100.0,
                price_changed_at=inside,
            ),
            # The quiet shop has stock and no news.
            item(quiet, "still-here", first_seen_at=outside, current_price=300.0),
        ]
    )
    session.commit()
    return session


class TestTheNumbers:
    def test_the_window_is_closed_at_both_ends(self, catalog):
        week = changes.summarize(catalog, days=7)
        assert week.days == 7
        assert (week.until - week.since).days == 7
        # "old-1" arrived forty days ago and must not be counted as an arrival
        # however many times somebody reloads the page.
        assert week.added == 2

    def test_departures_are_counted_which_is_what_the_digest_cannot_do(self, catalog):
        week = changes.summarize(catalog, days=7)
        assert week.sold == 1
        assert week.delisted == 1

    def test_a_trivial_reduction_is_not_news(self, catalog):
        week = changes.summarize(catalog, days=7)
        assert week.reduced == 1
        assert week.total_reduction == 300.0

    def test_listed_now_counts_stock_rather_than_movement(self, catalog):
        week = changes.summarize(catalog, days=7)
        # new-1, new-2, old-1, cut-1, cut-2 and the quiet shop's one.
        assert week.active_now == 6

    def test_a_longer_window_reaches_further_back(self, catalog):
        assert changes.summarize(catalog, days=90).added == 8


class TestBySite:
    def test_a_shop_that_reported_nothing_is_listed_anyway(self, catalog):
        """The finding is the silence, so dropping the row would answer the
        question the page is asking."""
        week = changes.summarize(catalog, days=7)
        by_name = {site.name: site for site in week.sites}
        assert "Quiet Shop" in by_name
        assert by_name["Quiet Shop"].silent is True
        assert by_name["Quiet Shop"].active == 1
        assert by_name["Busy Shop"].silent is False

    def test_a_disabled_shop_shows_only_if_something_happened(self, catalog):
        quiet = catalog.query(Site).filter_by(slug="quiet-shop").one()
        quiet.enabled = False
        catalog.commit()
        week = changes.summarize(catalog, days=7)
        assert "Quiet Shop" not in {site.name for site in week.sites}

        # ...but a shop switched off on Wednesday still had a Monday, and the
        # headline numbers count those rows, so the table has to as well.
        busy = catalog.query(Site).filter_by(slug="busy-shop").one()
        busy.enabled = False
        catalog.commit()
        week = changes.summarize(catalog, days=7)
        by_name = {site.name: site for site in week.sites}
        assert by_name["Busy Shop"].enabled is False
        assert by_name["Busy Shop"].added == 2

    def test_a_failed_scan_is_distinct_from_a_quiet_week(self, catalog):
        quiet = catalog.query(Site).filter_by(slug="quiet-shop").one()
        catalog.add(
            ScanRun(
                site_id=quiet.id,
                status=ScanStatus.FAILED,
                started_at=utcnow() - timedelta(days=1),
            )
        )
        catalog.commit()
        week = changes.summarize(catalog, days=7)
        by_name = {site.name: site for site in week.sites}
        assert by_name["Quiet Shop"].failed_scans == 1
        assert by_name["Quiet Shop"].silent is True


class TestHighlights:
    def test_reductions_are_ranked_by_how_much_came_off(self, catalog):
        week = changes.summarize(catalog, days=7)
        assert [row.title for row in week.biggest_drops] == ["Busy Shop cut-1"]
        assert week.biggest_drops[0].drop == 300.0
        assert week.biggest_drops[0].drop_percent == 37.5

    def test_arrivals_are_ranked_by_price_not_by_recency(self, catalog):
        """ "Newest" is what the browse view already answers, and better."""
        week = changes.summarize(catalog, days=7)
        assert [row.price for row in week.arrivals] == [9000.0, 200.0]

    def test_what_the_catalog_learned(self, catalog):
        week = changes.summarize(catalog, days=7)
        assert week.new_calibers == ["11mm Gras"]
        assert week.new_countries == ["France"]

    def test_a_value_the_catalog_already_had_is_not_new(self, catalog):
        """Asked as "the earliest listing carrying this is recent", not "a
        recent listing carries this" -- which would name every caliber in the
        catalog every week."""
        old = catalog.query(Item).filter_by(external_key="old-1").one()
        old.caliber = "11mm Gras"
        old.first_seen_at = utcnow() - timedelta(days=40)
        catalog.commit()
        assert changes.summarize(catalog, days=7).new_calibers == []


class TestTheEndpoint:
    def test_any_signed_in_user_may_read_it(self, client, normal_user):
        """Not admin-only. The parts an operator reads it for -- a shop gone
        quiet, a scan that failed -- are also what explains to everybody else
        why a shop has had nothing new for a fortnight."""
        response = client.get("/api/changes", headers=normal_user["headers"])
        assert response.status_code == 200, response.text
        assert response.json()["days"] == 7

    def test_it_needs_signing_in(self, client):
        assert client.get("/api/changes").status_code == 401

    def test_the_window_is_bounded(self, client, admin_headers):
        assert client.get("/api/changes?days=0", headers=admin_headers).status_code == 422
        assert client.get("/api/changes?days=400", headers=admin_headers).status_code == 422
        assert client.get("/api/changes?days=90", headers=admin_headers).status_code == 200
