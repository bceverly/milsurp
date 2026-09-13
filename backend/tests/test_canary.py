"""What the canary concludes from each way a shop can disappoint it.

The verdicts are the whole product here: a sweep that reported one
undifferentiated "failed" would be technically correct and useless, because
"they are refusing us" and "our parser no longer reads their page" send the
reader to completely different files. So each mapping is pinned.

Nothing in here touches the network. A test that asked a real vendor whether
it was blocking us would fail on their bad days rather than ours.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

import pytest

from app.scrapers.base import (
    Disallowed,
    HostResting,
    ScrapeCanceled,
    ScrapeContext,
    ScrapeError,
    SiteScraper,
)
from app.services import canary
from app.services.canary import Verdict


class _Fake(SiteScraper):
    """A scraper that does whatever the test told it to."""

    slug = "fake-shop"
    name = "Fake Shop"
    base_url = "https://example.test/"

    def __init__(self, behavior, *, requires_browser: bool = False) -> None:
        self._behavior = behavior
        self.requires_browser = requires_browser
        #: How many listings were actually asked for. The early stop is a
        #: promise about the vendor's bandwidth, so it is measured, not assumed.
        self.produced = 0

    def scrape(self, ctx: ScrapeContext) -> Iterable:
        return self._behavior(self, ctx)


def _yielding(count: int):
    def behave(scraper: _Fake, _ctx):
        for index in range(count):
            scraper.produced += 1
            yield f"item-{index}"

    return behave


def _raising(exc: Exception):
    def behave(_scraper, _ctx):
        raise exc
        yield  # pragma: no cover - makes this a generator like the others

    return behave


@pytest.fixture
def config(app_config):
    return app_config


class TestWhatEachFailureIsCalled:
    def test_listings_arriving_is_the_only_pass(self, config):
        result = canary.probe(config, _Fake(_yielding(5)), want=3)
        assert result.verdict is Verdict.OK
        assert result.healthy
        assert result.items == 3

    def test_a_policy_status_is_the_vendor_refusing(self, config):
        """401/403/404/410 -- VENDOR_ANSWERS. The six-vendor case."""
        error = ScrapeError("nope", status=403)
        result = canary.probe(config, _Fake(_raising(error)))
        assert result.verdict is Verdict.REFUSED
        assert result.status == 403
        assert not result.healthy

    def test_a_server_error_is_the_shop_breaking_not_refusing(self, config):
        """A 503 is not a decision, and pointing someone at an IP block over
        one would waste their evening."""
        result = canary.probe(config, _Fake(_raising(ScrapeError("oops", status=503))))
        assert result.verdict is Verdict.BROKE

    def test_robots_saying_no_is_a_refusal(self, config):
        result = canary.probe(config, _Fake(_raising(Disallowed("https://example.test/x"))))
        assert result.verdict is Verdict.REFUSED

    def test_our_own_cooldown_is_its_own_verdict(self, config):
        """HostResting subclasses ScrapeError, so it must be caught first or it
        reads as the vendor breaking. checkpoint-charlies had been failing this
        way for three days when the first sweep found it."""
        result = canary.probe(config, _Fake(_raising(HostResting("https://example.test/x", 900))))
        assert result.verdict is Verdict.RESTING

    def test_a_clean_run_with_nothing_in_it_is_empty(self, config):
        """The quiet one: they answered, we parsed, nothing came out."""
        result = canary.probe(config, _Fake(_yielding(0)))
        assert result.verdict is Verdict.EMPTY
        assert result.items == 0

    def test_an_unexpected_exception_never_escapes(self, config):
        """A canary that dies on shop three takes the other twenty-five with
        it and reports a partial picture as a whole one."""
        result = canary.probe(config, _Fake(_raising(ValueError("surprise"))))
        assert result.verdict is Verdict.BROKE
        assert "ValueError" in result.detail

    def test_a_scraper_honoring_our_stopwatch_is_a_timeout_not_a_fault(self, config):
        """ScrapeCanceled is what should_stop() produces, and should_stop() is
        how the budget is enforced. Calling that BROKE blames the vendor for
        our clock -- which is what royal-tiger, the one Selenium site, reported
        on its first run."""
        result = canary.probe(config, _Fake(_raising(ScrapeCanceled("stopped"))))
        assert result.verdict is Verdict.TIMEOUT

    def test_running_out_of_time_with_nothing_is_a_timeout(self, config):
        def slow(_scraper, _ctx):
            time.sleep(0.05)
            return
            yield  # pragma: no cover

        result = canary.probe(config, _Fake(slow), budget=0.0)
        assert result.verdict is Verdict.TIMEOUT


class TestItStopsEarly:
    def test_it_asks_for_no_more_than_it_needs(self, config):
        """The probe is one page of work, not a scrape. A scraper is a
        generator, so breaking out of the loop closes it where it stands --
        which is the entire reason this can run nightly against 28 shops."""
        scraper = _Fake(_yielding(10_000))
        result = canary.probe(config, scraper, want=3)
        assert result.items == 3
        assert scraper.produced == 3, "the generator kept running past the break"

    def test_a_shop_with_fewer_listings_than_wanted_still_passes(self, config):
        result = canary.probe(config, _Fake(_yielding(1)), want=3)
        assert result.verdict is Verdict.OK
        assert result.items == 1


class TestTheSweep:
    def test_an_unregistered_slug_is_reported_not_raised(self, config):
        results = canary.sweep(config, ["no-such-shop"])
        assert [r.verdict for r in results] == [Verdict.BROKE]
        assert "no scraper" in results[0].detail

    def test_browser_sites_can_be_left_out(self, config, monkeypatch):
        needs_chrome = _Fake(_yielding(3), requires_browser=True)
        monkeypatch.setattr(canary, "get_scraper", lambda _slug: needs_chrome)
        assert canary.sweep(config, ["x"], skip_browser=True) == []
        assert len(canary.sweep(config, ["x"], skip_browser=False)) == 1

    def test_a_browser_site_gets_a_longer_clock(self, config, monkeypatch):
        """Starting Chrome and waiting for a page's scripts is most of a minute
        before any parsing happens, so the ordinary ceiling would report a
        timeout every night for a site that works. Raising the default instead
        would let a genuinely hung HTTP shop sit there five times as long."""
        seen: list[float] = []
        monkeypatch.setattr(
            canary, "get_scraper", lambda _slug: _Fake(_yielding(3), requires_browser=True)
        )
        monkeypatch.setattr(
            canary,
            "probe",
            lambda _c, _s, want, budget: (
                seen.append(budget)
                or canary.Probe(slug="x", name="x", verdict=Verdict.OK, items=3, seconds=0.0)
            ),
        )
        canary.sweep(config, ["x"], budget=canary.DEFAULT_BUDGET)
        assert seen == [canary.BROWSER_BUDGET]


class TestTheReportReadsWorstFirst:
    def _probe(self, slug, verdict):
        return canary.Probe(slug=slug, name=slug, verdict=verdict, items=0, seconds=0.0)

    def test_healthy_rows_are_not_failures(self):
        rows = [self._probe("a", Verdict.OK), self._probe("b", Verdict.EMPTY)]
        assert [r.slug for r in canary.failures(rows)] == ["b"]

    def test_a_refusal_outranks_an_empty_parse(self):
        """One refusal is usually one cause behind many rows -- an address, an
        identity. An empty parse is one shop's own markup."""
        rows = [
            self._probe("empty", Verdict.EMPTY),
            self._probe("resting", Verdict.RESTING),
            self._probe("refused", Verdict.REFUSED),
        ]
        assert [r.slug for r in canary.failures(rows)] == ["refused", "resting", "empty"]


class TestItWritesNothing:
    def test_the_module_never_reaches_for_a_session(self):
        """Source-inspected. A canary that stored listings would be a scan, and
        a scrape abandoned after three items marks everything it never reached
        as de-listed -- which is the accident SiteScraper.scrape warns about.
        """
        from pathlib import Path

        source = Path(canary.__file__).read_text(encoding="utf-8")
        assert "session_scope" not in source
        assert "commit" not in source
