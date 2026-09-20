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
from unittest import mock

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

    def test_a_whole_shop_skipped_for_resting_is_resting_too(self, config):
        """The shape that actually reaches this, rather than a bare
        HostResting constructed in a test.

        A WooCommerce shop whose every section was skipped used to raise a
        plain ScrapeError carrying a sentence about the cooldown, and a
        sentence is not a type: the branch above never fired, and Checkpoint
        Charlie's was mailed out as BROKE every morning for a week while the
        register was doing exactly what it was built to do.
        """
        from app.scrapers.woocommerce import WooCommerceScraper

        class RestingShop(WooCommerceScraper):
            slug = "resting-shop"
            name = "Resting Shop"
            base_url = "https://example.test/"
            description = "A test double."
            sources = tuple(
                {"category": f"Section {n}", "url": f"https://example.test/c/{n}/"}
                for n in range(13)
            )

        with (
            mock.patch.object(canary.cooldown, "paused_for", return_value=900.0),
            mock.patch("app.scrapers.base.cooldown.paused_for", return_value=900.0),
            mock.patch("app.scrapers.woocommerce.cooldown.paused_for", return_value=900.0),
        ):
            result = canary.probe(config, RestingShop())

        assert result.verdict is Verdict.RESTING
        assert "13 section(s) not asked" in result.detail

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


class TestAPacedHostIsGivenTimeToBeAskedSlowly:
    """The canary must not blame a vendor for our own politeness.

    checkpointcharlies.com refused a run of photo fetches, so the cooldown
    register held every request to it to a sixty-second gap. Two requests
    therefore cannot fit in a ninety-second budget and never will -- and the
    first night this ran in production it reported the shop as a timeout, which
    reads as the vendor being broken.
    """

    def test_the_budget_grows_with_the_gap(self, config, monkeypatch):
        asked: list[float] = []
        monkeypatch.setattr(canary, "get_scraper", lambda _slug: _Fake(_yielding(3)))
        monkeypatch.setattr(canary.cooldown, "pace_for", lambda _url: 60.0)
        monkeypatch.setattr(
            canary,
            "probe",
            lambda _c, _s, want, budget: asked.append(budget)
            or canary.Probe(slug="x", name="x", verdict=Verdict.OK, items=3, seconds=0.0),
        )
        canary.sweep(config, ["x"], budget=90.0)
        assert asked == [90.0 + 60.0 * canary.PACED_REQUESTS]

    def test_and_stays_put_for_a_host_nobody_is_pacing(self, config, monkeypatch):
        asked: list[float] = []
        monkeypatch.setattr(canary, "get_scraper", lambda _slug: _Fake(_yielding(3)))
        monkeypatch.setattr(canary.cooldown, "pace_for", lambda _url: 0.0)
        monkeypatch.setattr(
            canary,
            "probe",
            lambda _c, _s, want, budget: asked.append(budget)
            or canary.Probe(slug="x", name="x", verdict=Verdict.OK, items=3, seconds=0.0),
        )
        canary.sweep(config, ["x"], budget=90.0)
        assert asked == [90.0]

    def test_a_timeout_says_whose_fault_the_waiting_was(self, config, monkeypatch):
        """ "gave up after 90s" sends a reader to check the vendor. If the
        register is holding us to a request a minute, the vendor is not the
        thing to check."""
        monkeypatch.setattr(canary.cooldown, "pace_for", lambda _url: 60.0)
        result = canary.probe(config, _Fake(_raising(ScrapeCanceled("stopped"))))
        assert result.verdict is Verdict.TIMEOUT
        assert "our own pacing" in result.detail

    def test_and_does_not_when_there_was_none(self, config, monkeypatch):
        monkeypatch.setattr(canary.cooldown, "pace_for", lambda _url: 0.0)
        result = canary.probe(config, _Fake(_raising(ScrapeCanceled("stopped"))))
        assert "our own pacing" not in result.detail


class TestWatchingOurOwnSite:
    """The check that exists because the application cannot report its absence.

    Everything else in this module watches somebody else's website. This one
    goes out through `public_url` and comes back in the way a visitor does,
    because the outage it was written for had the Python process answering in
    under a millisecond while the proxy in front returned 504s. Anything that
    only asked localhost would have called that healthy.
    """

    @staticmethod
    def _config(app_config, url="https://milsurp.test"):
        import dataclasses

        return dataclasses.replace(
            app_config, server=dataclasses.replace(app_config.server, public_url=url)
        )

    @staticmethod
    def _answers(monkeypatch, sequence):
        """Make requests.get walk `sequence`, one entry per attempt.

        An int is a status code; an exception instance is raised; a tuple is
        (status, seconds) so an attempt can be made to look slow without one.
        """
        calls = {"n": 0}
        clock = {"t": 1000.0}

        def fake_get(url, timeout=None):
            index = min(calls["n"], len(sequence) - 1)
            calls["n"] += 1
            entry = sequence[index]
            if isinstance(entry, Exception):
                raise entry
            status, elapsed = entry if isinstance(entry, tuple) else (entry, 0.01)
            clock["t"] += elapsed
            return _Response(status)

        monkeypatch.setattr(canary.requests, "get", fake_get)
        monkeypatch.setattr(canary.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(canary, "SITE_GAP", 0.0)
        return calls

    def test_a_site_that_answers_is_up(self, app_config, monkeypatch):
        self._answers(monkeypatch, [200])
        health = canary.site_health(self._config(app_config), sleep=lambda _: None)
        assert not health.unhappy
        assert not health.down
        assert "is up" in health.headline

    def test_it_asks_through_the_public_url(self, app_config, monkeypatch):
        seen = {}

        def fake_get(url, timeout=None):
            seen["url"] = url
            return _Response(200)

        monkeypatch.setattr(canary.requests, "get", fake_get)
        monkeypatch.setattr(canary, "SITE_GAP", 0.0)
        canary.site_health(self._config(app_config), sleep=lambda _: None)
        # Not localhost: localhost proves the process is alive, which was
        # never the half in doubt.
        assert seen["url"] == "https://milsurp.test/api/health"

    def test_nothing_answering_is_down(self, app_config, monkeypatch):
        self._answers(monkeypatch, [canary.requests.ConnectionError("refused")])
        health = canary.site_health(self._config(app_config), sleep=lambda _: None)
        assert health.down
        assert health.unhappy
        assert "not answering" in health.headline

    def test_a_gateway_error_is_down_too(self, app_config, monkeypatch):
        """What a visitor actually saw: the proxy answering instead of us."""
        self._answers(monkeypatch, [504])
        health = canary.site_health(self._config(app_config), sleep=lambda _: None)
        assert health.down
        assert health.status == 504

    def test_some_answering_and_some_not_is_flapping(self, app_config, monkeypatch):
        """The shape of the real outage: fine between the bursts."""
        self._answers(monkeypatch, [200, canary.requests.ConnectionError("x"), 200])
        health = canary.site_health(self._config(app_config), sleep=lambda _: None)
        assert not health.down
        assert health.flapping
        assert health.unhappy
        assert "1 of 3" not in health.headline  # it reports successes, not failures
        assert "2 of 3" in health.headline

    def test_answering_slowly_is_worth_saying(self, app_config, monkeypatch):
        self._answers(monkeypatch, [(200, canary.SITE_SLOW_SECONDS + 1)])
        health = canary.site_health(self._config(app_config), sleep=lambda _: None)
        assert health.slow
        assert health.unhappy
        assert not health.down

    def test_a_normal_answer_is_not_called_slow(self, app_config, monkeypatch):
        self._answers(monkeypatch, [(200, 0.02)])
        health = canary.site_health(self._config(app_config), sleep=lambda _: None)
        assert not health.slow

    def test_it_samples_more_than_once(self, app_config, monkeypatch):
        """One probe cannot see an intermittent fault, and the fault this was
        written for was intermittent."""
        calls = self._answers(monkeypatch, [200])
        canary.site_health(self._config(app_config), sleep=lambda _: None)
        assert calls["n"] == canary.SITE_ATTEMPTS
        assert canary.SITE_ATTEMPTS > 1

    def test_the_slow_threshold_warns_before_a_visitor_would(self, app_config):
        """It has to fire while requests are still being answered, not once
        the proxy in front has already given up on them."""
        assert canary.SITE_SLOW_SECONDS < canary.SITE_TIMEOUT


class _Response:
    """Just enough of requests.Response for the checks above."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class TestTheDetailIsReadable:
    """A connection error's repr is three hundred characters of retry
    machinery, and this ends up in an email somebody reads on a phone."""

    def test_a_long_error_is_trimmed(self):
        trimmed = canary._short("x" * 500)
        assert len(trimmed) <= canary.SITE_DETAIL_CHARS
        assert trimmed.endswith("…")

    def test_a_short_one_is_left_alone(self):
        assert canary._short("ConnectionError: refused") == "ConnectionError: refused"

    def test_newlines_do_not_survive(self):
        assert "\n" not in canary._short("first line\nsecond line")
