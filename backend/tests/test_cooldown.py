"""The shared "leave this host alone" register.

The subject here is what survives a process. Every fetching path consults this
before making a request, so a limit learned by the scheduler is one the CLI and
a `make photos` run also obey — which is the difference between one crawler
being told to slow down and several ignoring the same instruction.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import HostCooldown, utcnow
from app.services import cooldown

URL = "https://vendor.test/product/rifle/"
OTHER = "https://elsewhere.test/a.jpg"


@pytest.fixture(autouse=True)
def _clean(_database):
    cooldown.clear()
    cooldown._cache.clear()
    yield
    cooldown.clear()
    cooldown._cache.clear()


class TestRecordingARefusal:
    def test_a_free_host_is_free(self):
        assert cooldown.paused_for(URL) == 0.0

    def test_a_refusal_pauses_the_host(self):
        waited = cooldown.refused(URL, "429 at the slowest pace available")
        assert waited >= cooldown.MIN_COOLDOWN.total_seconds()
        cooldown._cache.clear()
        assert cooldown.paused_for(URL) > 0

    def test_it_pauses_the_host_and_not_the_path(self):
        """A rate limiter counts requests to a hostname. The vendor's catalog
        and their uploads directory are the same host, and where they are not,
        the CDN in front of both is what is counting."""
        cooldown.refused(URL, "429")
        cooldown._cache.clear()
        assert cooldown.paused_for("https://vendor.test/wp-content/uploads/a.jpg") > 0

    def test_and_leaves_every_other_host_alone(self):
        cooldown.refused(URL, "429")
        cooldown._cache.clear()
        assert cooldown.paused_for(OTHER) == 0.0

    def test_the_wait_grows_with_each_refusal(self):
        first = cooldown.refused(URL, "429")
        second = cooldown.refused(URL, "429")
        assert second > first

    def test_but_never_past_the_ceiling(self):
        """A longer pause only delays the next honest attempt: a scan that
        finds a host resting reports it and moves on."""
        for _ in range(20):
            waited = cooldown.refused(URL, "429")
        assert waited <= cooldown.MAX_COOLDOWN.total_seconds() + 1

    def test_a_retry_after_the_host_sent_wins(self):
        """It is the only number in the exchange the vendor chose."""
        waited = cooldown.refused(URL, "429", retry_after=900)
        assert waited >= 900

    def test_a_pause_is_never_shortened(self):
        """Another process may have been told something worse than we were."""
        cooldown.refused(URL, "429", retry_after=1800)
        before = cooldown.paused_for(URL)
        cooldown._cache.clear()
        cooldown.refused(URL, "429")
        cooldown._cache.clear()
        assert cooldown.paused_for(URL) >= before - 5


class TestClearing:
    def test_a_host_that_answers_again_is_released(self):
        cooldown.refused(URL, "429")
        cooldown._cache.clear()
        assert cooldown.paused_for(URL) > 0

        cooldown.succeeded(URL)
        cooldown._cache.clear()
        assert cooldown.paused_for(URL) == 0.0

    def test_clearing_by_hand_lifts_one(self):
        cooldown.refused(URL, "429")
        cooldown.refused(OTHER, "429")
        cooldown._cache.clear()

        assert cooldown.clear("vendor.test") == 1
        assert cooldown.paused_for(URL) == 0.0
        assert cooldown.paused_for(OTHER) > 0

    def test_or_all_of_them(self):
        cooldown.refused(URL, "429")
        cooldown.refused(OTHER, "429")
        assert cooldown.clear() == 2

    def test_an_expired_pause_is_not_active(self, session):
        session.add(
            HostCooldown(
                host="stale.test",
                until=utcnow() - timedelta(hours=2),
                refusals=1,
            )
        )
        session.commit()

        assert cooldown.paused_for("https://stale.test/x") == 0.0
        assert "stale.test" not in [row.host for row in cooldown.active()]


class TestItNeverBreaksAFetch:
    """The register is politeness bookkeeping, not correctness.

    An application whose HTTP layer stops working because a table is missing
    is a strictly worse failure than asking a vendor too often, so every path
    through here has to fail open.
    """

    def test_a_broken_register_reads_as_free(self, monkeypatch):
        def explode():
            raise RuntimeError("no database here")

        monkeypatch.setattr(cooldown, "session_scope", explode)
        cooldown._cache.clear()
        cooldown._warned = False

        assert cooldown.paused_for(URL) == 0.0

    def test_a_broken_register_swallows_a_refusal(self, monkeypatch):
        from sqlalchemy.exc import OperationalError

        def explode():
            raise OperationalError("select 1", {}, Exception("no such table"))

        monkeypatch.setattr(cooldown, "session_scope", explode)
        cooldown._warned = False

        assert cooldown.refused(URL, "429") == 0.0

    def test_a_url_with_no_host_is_not_a_host(self):
        assert cooldown.paused_for("not a url") == 0.0
        assert cooldown.refused("not a url", "429") == 0.0
