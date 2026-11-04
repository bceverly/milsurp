"""A hosted platform resting as a whole (services/platform_rest).

November 2026: Shopify began answering 429 to this address for every store it
hosts, ours and others, and each shop's own hour-long cooldown kept walking
back into it. Two shops on one platform refused within a day now rests every
shop on that platform for a week, through the ordinary cooldown register, and
the week ending is all it takes for them to be scanned again.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
import responses
from sqlalchemy import select

from app.models import HostCooldown, PlatformRefusal, Site, as_utc, utcnow
from app.scrapers import ScrapeContext, get_scraper_class
from app.scrapers.base import HostResting
from app.services import canary, cooldown, platform_rest, scan_service, scanalerts
from app.services.canary import Verdict

SHOPIFY = ("centerfire-systems", "ima-usa", "muzzle-loaders", "tortuga-trading")


def _url(slug: str, path: str = "collections/x/products.json") -> str:
    return get_scraper_class(slug).base_url.rstrip("/") + "/" + path


@pytest.fixture
def shops(clean_db):
    """Site rows for the Shopify shops and one shop on its own server."""
    rows = []
    for slug in (*SHOPIFY, "sarco"):
        cls = get_scraper_class(slug)
        rows.append(Site(slug=slug, name=cls.name, base_url=cls.base_url, enabled=True))
    clean_db.add_all(rows)
    clean_db.commit()
    yield {site.slug: site for site in rows}
    clean_db.rollback()
    cooldown.clear()


@pytest.fixture
def mailed():
    with mock.patch.object(scanalerts, "send") as send:
        yield send


def _rest_rows(session):
    session.expire_all()
    return {
        row.host: row
        for row in session.execute(select(HostCooldown).where(HostCooldown.platform.is_not(None)))
        .scalars()
        .all()
    }


class TestWhichShopsAreOnAPlatform:
    def test_the_shopify_shops_are_shopify(self):
        for slug in SHOPIFY:
            assert platform_rest.platform_of(_url(slug)) == "Shopify"

    def test_with_or_without_www(self):
        url = _url("ima-usa")
        assert platform_rest.platform_of(url.replace("://www.", "://")) == "Shopify"

    def test_bigcommerce_and_wix_are_hosted_too(self):
        assert platform_rest.platform_of(_url("kittery-trading-post")) == "BigCommerce"
        assert platform_rest.platform_of(_url("surplus-defense")) == "Wix"

    def test_a_shop_on_its_own_server_is_on_none(self):
        """Two WooCommerce shops refusing on one day are two shops having a
        bad day: each runs on its own server."""
        assert platform_rest.platform_of(_url("checkpoint-charlies")) is None
        assert platform_rest.platform_of(_url("sarco")) is None

    def test_a_cdn_is_not_a_shop(self):
        assert platform_rest.platform_of("https://cdn.shopify.com/s/files/a.jpg") is None


class TestTheRule:
    def test_one_shop_refusing_is_that_shop_s_business(self, shops, mailed, clean_db):
        assert platform_rest.saw_429(_url("ima-usa")) is None
        assert _rest_rows(clean_db) == {}
        mailed.assert_not_called()

    def test_the_same_shop_twice_is_still_one_shop(self, shops, mailed, clean_db):
        platform_rest.saw_429(_url("ima-usa"))
        assert platform_rest.saw_429(_url("ima-usa", "collections/y/products.json")) is None
        assert _rest_rows(clean_db) == {}

    def test_two_shops_within_a_day_rest_every_shop_on_it(self, shops, mailed, clean_db):
        platform_rest.saw_429(_url("ima-usa"))
        assert platform_rest.saw_429(_url("tortuga-trading")) == "Shopify"

        rows = _rest_rows(clean_db)
        hosts = {cooldown.host_of(shops[slug].base_url) for slug in SHOPIFY}
        assert set(rows) == hosts, "the shops that did not refuse rest too"
        for row in rows.values():
            assert row.platform == "Shopify"
            left = as_utc(row.until) - utcnow()
            assert timedelta(days=6, hours=23) < left <= platform_rest.REST
        assert cooldown.host_of(shops["sarco"].base_url) not in rows

    def test_and_every_fetcher_then_leaves_them_alone(self, shops, mailed):
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))
        cooldown._cache.clear()
        assert cooldown.paused_for(_url("muzzle-loaders")) > 6 * 86400
        assert cooldown.paused_for(_url("sarco")) == 0

    def test_refusals_a_day_apart_are_not_the_platform(self, shops, mailed, clean_db):
        platform_rest.saw_429(_url("ima-usa"))
        old = clean_db.execute(select(PlatformRefusal)).scalar_one()
        old.refused_at = (utcnow() - platform_rest.WINDOW - timedelta(minutes=1)).replace(
            tzinfo=None
        )
        clean_db.commit()
        assert platform_rest.saw_429(_url("tortuga-trading")) is None
        assert _rest_rows(clean_db) == {}

    def test_different_platforms_do_not_add_up(self, shops, mailed, clean_db):
        platform_rest.saw_429(_url("ima-usa"))
        assert platform_rest.saw_429(_url("kittery-trading-post")) is None

    def test_the_administrators_are_told_once(self, shops, mailed):
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))
        # A request already in flight when the rest began.
        assert platform_rest.saw_429(_url("centerfire-systems")) is None
        assert mailed.call_count <= 1

    def test_the_evidence_is_spent_on_the_rest(self, shops, mailed, clean_db):
        """A week later the shops are asked again, and one refusal then must
        not combine with refusals from before the rest to start another."""
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))
        clean_db.expire_all()
        assert clean_db.execute(select(PlatformRefusal)).scalars().all() == []

    def test_a_longer_pause_already_set_is_never_shortened(self, shops, mailed, clean_db):
        host = cooldown.host_of(shops["muzzle-loaders"].base_url)
        later = utcnow() + timedelta(days=30)
        clean_db.add(HostCooldown(host=host, until=later, refusals=3))
        clean_db.commit()
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))
        row = _rest_rows(clean_db)[host]
        assert as_utc(row.until) >= later - timedelta(seconds=1)
        assert row.refusals == 3

    def test_it_never_raises(self, shops):
        with mock.patch.object(platform_rest, "session_scope", side_effect=RuntimeError("db")):
            assert platform_rest.saw_429(_url("ima-usa")) is None


class TestEndingTheRest:
    def test_a_stray_success_does_not_end_it(self, shops, mailed):
        """A rest is a week the platform asked for, not a host's own count."""
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))
        cooldown._cache.clear()
        cooldown.succeeded(_url("muzzle-loaders"))
        cooldown._cache.clear()
        assert cooldown.paused_for(_url("muzzle-loaders")) > 6 * 86400

    def test_stop_resting_still_lifts_it(self, shops, mailed):
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))
        cooldown.clear(cooldown.host_of(_url("ima-usa")))
        assert cooldown.paused_for(_url("ima-usa")) == 0
        assert cooldown.paused_for(_url("tortuga-trading")) > 0

    def test_once_the_week_is_up_the_shop_is_asked_again_gently(self, shops, mailed, clean_db):
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))
        for row in _rest_rows(clean_db).values():
            row.until = utcnow() - timedelta(minutes=1)
        clean_db.commit()
        cooldown._cache.clear()
        assert cooldown.paused_for(_url("ima-usa")) == 0
        assert cooldown.pace_for(_url("ima-usa")) > 0
        # ...and the first answer is trusted like any other host's.
        cooldown.succeeded(_url("ima-usa"))
        cooldown._cache.clear()
        assert cooldown.pace_for(_url("ima-usa")) == 0


class TestWhatTheRestOfTheApplicationDoes:
    def _rest(self):
        platform_rest.saw_429(_url("ima-usa"))
        platform_rest.saw_429(_url("tortuga-trading"))

    def test_the_scheduler_starts_no_scan_into_it(self, shops, mailed, clean_db):
        """Otherwise each shop fails a scan that asked nothing, every day for
        a week, and is reported broken for being left alone on purpose."""
        self._rest()
        due = scan_service.due_site_ids(clean_db)
        assert shops["sarco"].id in due
        for slug in SHOPIFY:
            assert shops[slug].id not in due

    def test_and_they_are_due_the_moment_it_ends(self, shops, mailed, clean_db):
        self._rest()
        for row in _rest_rows(clean_db).values():
            row.until = utcnow() - timedelta(minutes=1)
        clean_db.commit()
        due = scan_service.due_site_ids(clean_db)
        for slug in SHOPIFY:
            assert shops[slug].id in due

    def test_the_canary_excuses_it_without_asking(self, shops, mailed, app_config):
        self._rest()
        scraper = get_scraper_class("ima-usa")()
        with mock.patch.object(type(scraper), "scrape", side_effect=AssertionError("asked")):
            result = canary.probe(app_config, scraper)
        assert result.verdict is Verdict.RESTING
        assert result.excused and result.healthy
        assert "Shopify is resting until" in result.detail

    def test_and_does_not_turn_it_into_a_failure_after_three_days(self, shops, mailed, app_config):
        self._rest()
        result = canary.probe(app_config, get_scraper_class("ima-usa")())
        long_ago = utcnow() - timedelta(days=10)
        judged = canary.excuse_resting([result], {"ima-usa": long_ago}, {"ima-usa": 1440}, utcnow())
        assert judged[0].healthy

    def test_no_stopped_scraping_mail_during_it(self, shops, mailed, clean_db):
        self._rest()
        mailed.reset_mock()
        site = shops["ima-usa"]
        site.scan_failing_since = utcnow() - timedelta(days=5)
        clean_db.commit()
        assert scanalerts.report_overdue(clean_db, timedelta(hours=1)) == []
        clean_db.refresh(site)
        assert site.scan_failure_reported is False, "still owed once the rest is over"


class TestTheHttpLayerReportsIt:
    @responses.activate
    def test_a_429_from_a_shopify_shop_is_counted(self, shops, mailed, app_config, clean_db):
        url = _url("ima-usa")
        responses.add(responses.GET, url, status=429, headers={"Retry-After": "0"})
        ctx = ScrapeContext(app_config)
        try:
            with mock.patch.object(ctx, "sleep"), pytest.raises(Exception):  # noqa: B017
                ctx.get(url, retries=1)
        finally:
            ctx.close()
        clean_db.expire_all()
        hosts = clean_db.execute(select(PlatformRefusal.host)).scalars().all()
        assert hosts == [cooldown.host_of(url)]

    @responses.activate
    def test_the_second_shop_s_429_rests_the_platform_and_stops_the_scan(
        self, shops, mailed, app_config
    ):
        platform_rest.saw_429(_url("ima-usa"))
        first, second = _url("tortuga-trading"), _url("tortuga-trading", "products/b.json")
        responses.add(responses.GET, first, status=429, headers={"Retry-After": "0"})
        ctx = ScrapeContext(app_config)
        try:
            with mock.patch.object(ctx, "sleep"):
                with pytest.raises(Exception):  # noqa: B017
                    ctx.get(first, retries=1)
                cooldown._cache.clear()
                with pytest.raises(HostResting):
                    ctx.get(second)
        finally:
            ctx.close()
        assert any("platform now resting for a week" in w for w in ctx.warnings)
