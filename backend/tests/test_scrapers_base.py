"""What every scraper gets for free: politeness, retries, and robots.txt."""

from __future__ import annotations

import dataclasses

import pytest
import responses

from app.scrapers import Disallowed, ScrapeContext
from app.scrapers.base import ScrapeError

SITE = "https://shop.test"


@pytest.fixture
def obeying(app_config):
    """A config with robots enforcement on, as production has it."""
    return dataclasses.replace(
        app_config, scraping=dataclasses.replace(app_config.scraping, obey_robots=True)
    )


def robots(body: str, status: int = 200) -> None:
    responses.add(
        responses.GET, f"{SITE}/robots.txt", body=body, status=status, content_type="text/plain"
    )


class TestRobotsIsEnforced:
    @responses.activate
    def test_an_allowed_page_is_fetched(self, obeying):
        robots("User-agent: *\nDisallow: /wp-admin/")
        responses.add(responses.GET, f"{SITE}/product-category/rifles/", body="<html/>")

        context = ScrapeContext(obeying)
        try:
            assert context.get_text(f"{SITE}/product-category/rifles/") == "<html/>"
        finally:
            context.close()

    @responses.activate
    def test_a_disallowed_page_is_never_requested(self, obeying):
        """Not fetched and discarded — not fetched at all."""
        robots("User-agent: *\nDisallow: /private/")

        context = ScrapeContext(obeying)
        try:
            with pytest.raises(Disallowed, match="disallows"):
                context.get(f"{SITE}/private/thing")
        finally:
            context.close()

        assert [call.request.url for call in responses.calls] == [f"{SITE}/robots.txt"]

    @responses.activate
    def test_the_rules_are_read_once_for_the_whole_scan(self, obeying):
        robots("User-agent: *\nAllow: /")
        for path in ("/a", "/b", "/c"):
            responses.add(responses.GET, f"{SITE}{path}", body="ok")

        context = ScrapeContext(obeying)
        try:
            for path in ("/a", "/b", "/c"):
                context.get(f"{SITE}{path}")
        finally:
            context.close()

        assert [call.request.url for call in responses.calls].count(f"{SITE}/robots.txt") == 1

    @responses.activate
    def test_a_site_that_cannot_serve_its_rules_is_left_alone(self, obeying):
        """A 503 from the robots endpoint is not an invitation."""
        robots("", status=503)

        context = ScrapeContext(obeying)
        try:
            with pytest.raises(Disallowed):
                context.get(f"{SITE}/anything")
        finally:
            context.close()

    @responses.activate
    def test_no_robots_file_means_no_restrictions(self, obeying):
        robots("", status=404)
        responses.add(responses.GET, f"{SITE}/anything", body="ok")

        context = ScrapeContext(obeying)
        try:
            assert context.get(f"{SITE}/anything").status_code == 200
        finally:
            context.close()

    @responses.activate
    def test_allowed_answers_without_fetching_the_page(self, obeying):
        """So a scraper can choose a different route instead of failing."""
        robots("User-agent: *\nDisallow: /*?*")

        context = ScrapeContext(obeying)
        try:
            assert context.allowed(f"{SITE}/wp-json/wc/store/v1/products")
            assert not context.allowed(f"{SITE}/wp-json/wc/store/v1/products?page=2")
        finally:
            context.close()

    @responses.activate
    def test_turning_it_off_turns_it_off(self, app_config):
        """The setting exists for a vendor who has given explicit permission."""
        robots("User-agent: *\nDisallow: /")
        responses.add(responses.GET, f"{SITE}/private/thing", body="ok")

        context = ScrapeContext(app_config)  # obey_robots is false in the tests
        try:
            assert context.get(f"{SITE}/private/thing").status_code == 200
        finally:
            context.close()


class TestCrawlDelay:
    @responses.activate
    def test_the_site_s_own_delay_is_used_when_it_is_longer(self, obeying, monkeypatch):
        """Collectors Firearms asks for ten seconds. That is their call."""
        robots("User-agent: *\nCrawl-delay: 10\nAllow: /")
        responses.add(responses.GET, f"{SITE}/a", body="ok")
        slept: list[float] = []
        monkeypatch.setattr("app.scrapers.base.time.sleep", slept.append)

        context = ScrapeContext(obeying)
        try:
            context.get(f"{SITE}/a")
            context.get(f"{SITE}/a")
        finally:
            context.close()

        assert slept and max(slept) > 9

    @responses.activate
    def test_our_own_delay_wins_when_it_is_longer(self, app_config, monkeypatch):
        config = dataclasses.replace(
            app_config,
            scraping=dataclasses.replace(app_config.scraping, obey_robots=True, request_delay=30.0),
        )
        robots("User-agent: *\nCrawl-delay: 1\nAllow: /")
        responses.add(responses.GET, f"{SITE}/a", body="ok")
        slept: list[float] = []
        monkeypatch.setattr("app.scrapers.base.time.sleep", slept.append)

        context = ScrapeContext(config)
        try:
            context.get(f"{SITE}/a")
            context.get(f"{SITE}/a")
        finally:
            context.close()

        assert max(slept) > 29


class TestBeingRateLimited:
    """A 429 is an instruction about the rest of the scan, not one request.

    Collectors Firearms publishes ``Crawl-delay: 10``, was crawled at exactly
    that pace, and returned 429 after sixteen minutes and ninety listings —
    their limiter counts over a window that ten seconds a request eventually
    fills. The old retry treated it like a flaky 500 and waited a second or
    two, which is asking too often again.
    """

    @pytest.fixture
    def slept(self, monkeypatch):
        recorded: list[float] = []
        monkeypatch.setattr("app.scrapers.base.time.sleep", recorded.append)
        return recorded

    def context(self, config):
        robots("User-agent: *\nAllow: /")
        return ScrapeContext(config)

    @responses.activate
    def test_the_pace_slows_for_everything_after_it(self, obeying, slept):
        responses.add(responses.GET, f"{SITE}/a", status=429)
        responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            assert context.get(f"{SITE}/a").status_code == 200
            assert context._delay_for(f"{SITE}/b") >= 30
        finally:
            context.close()

    @responses.activate
    def test_it_waits_at_least_that_long_before_retrying(self, obeying, slept):
        responses.add(responses.GET, f"{SITE}/a", status=429)
        responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            context.get(f"{SITE}/a")
        finally:
            context.close()

        assert max(slept) >= 30

    @responses.activate
    def test_retry_after_in_seconds_is_honored(self, obeying, slept):
        responses.add(responses.GET, f"{SITE}/a", status=429, headers={"Retry-After": "90"})
        responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            context.get(f"{SITE}/a")
        finally:
            context.close()

        assert max(slept) >= 90

    @responses.activate
    def test_retry_after_as_a_date_is_honored(self, obeying, slept):
        from datetime import UTC, datetime, timedelta
        from email.utils import format_datetime

        when = format_datetime(datetime.now(UTC) + timedelta(seconds=120))
        responses.add(responses.GET, f"{SITE}/a", status=429, headers={"Retry-After": when})
        responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            context.get(f"{SITE}/a")
        finally:
            context.close()

        assert max(slept) >= 100

    @responses.activate
    def test_a_second_refusal_slows_it_further(self, obeying, slept):
        for _ in range(2):
            responses.add(responses.GET, f"{SITE}/a", status=429)
            responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            context.get(f"{SITE}/a")
            first = context._delay_for(f"{SITE}/a")
            context.get(f"{SITE}/a")
            assert context._delay_for(f"{SITE}/a") > first
        finally:
            context.close()

    @responses.activate
    def test_the_scan_says_it_was_told_to_slow_down(self, obeying, slept):
        """A run that quietly takes six times as long is a mystery to whoever
        reads it later."""
        responses.add(responses.GET, f"{SITE}/a", status=429)
        responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            context.get(f"{SITE}/a")
        finally:
            context.close()

        assert any("429" in warning for warning in context.warnings)

    def refused_until_capped(self, context) -> int:
        """Ask until the pace stops getting slower. Returns how many it took."""
        for asked in range(1, 20):
            context.get(f"{SITE}/a")
            if context._delay_for(f"{SITE}/a") >= 300:
                return asked
        raise AssertionError("the pace never reached its ceiling")

    @responses.activate
    def test_however_insistent_the_site_the_pace_is_capped(self, obeying, slept):
        """Doubling without a ceiling reaches an hour a request, which is not
        politeness any more — it is a scan that will never finish."""
        for _ in range(40):
            responses.add(responses.GET, f"{SITE}/a", status=429)
            responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            self.refused_until_capped(context)
            assert context._delay_for(f"{SITE}/a") == 300
        finally:
            context.close()

    @responses.activate
    def test_a_refusal_at_the_ceiling_is_a_refusal_not_a_speed_limit(self, obeying, slept):
        """Once there is no slower left to go, "slow down" cannot be what the
        site means. Checkpoint Charlie's is the real case: their /product/
        pages answer 429 to any pace at all, and the old code answered by
        sleeping five minutes and asking again, three more times, per listing.

        Failing here is what lets the scrapers fall back to the catalog."""
        for _ in range(40):
            responses.add(responses.GET, f"{SITE}/a", status=429)
            responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            self.refused_until_capped(context)
            before = len(responses.calls)
            with pytest.raises(ScrapeError, match="refusing this request"):
                context.get(f"{SITE}/a")
            # And it gave up on the first one, rather than retrying into it.
            assert len(responses.calls) - before == 1
        finally:
            context.close()

    @responses.activate
    def test_a_site_that_answers_again_is_no_longer_refusing(self, obeying, slept):
        """The flag has to outlive nothing but the condition. A genuine rate
        limit arriving after an hour of successful requests deserves the same
        chance to be slowed down as the first one did."""
        for _ in range(40):
            responses.add(responses.GET, f"{SITE}/a", status=429)
            responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            self.refused_until_capped(context)
            # One more refusal at the ceiling, which fails fast and leaves the
            # host marked as refusing.
            with pytest.raises(ScrapeError, match="refusing this request"):
                context.get(f"{SITE}/a")
            assert context._refusing

            # Then it answers, and the mark comes off.
            responses.add(responses.GET, f"{SITE}/a", body="ok")
            assert context.get(f"{SITE}/a").status_code == 200
            assert not context._refusing
        finally:
            context.close()

    @responses.activate
    def test_a_flaky_server_still_gets_a_short_retry(self, obeying, slept):
        """A 500 usually clears on the next request; it is not a rate limit."""
        responses.add(responses.GET, f"{SITE}/a", status=500)
        responses.add(responses.GET, f"{SITE}/a", body="ok")

        context = self.context(obeying)
        try:
            context.get(f"{SITE}/a")
            assert context._delay_for(f"{SITE}/a") < 30
        finally:
            context.close()

        assert max(slept) < 30
