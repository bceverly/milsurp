"""The rule for when a price already mailed about is news again.

The stories against real listings are in test_watchlist.py
(TestARecurringSaleIsNotSilenced) and test_hotdeals.py (TestTheWatermarkIsAPrice).
These pin the rule itself, case by case.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.renotify import is_news

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
TOLD_AT = NOW - timedelta(days=3)


def news(price, *, told=450.0, peak=None, told_at=TOLD_AT, after_days=30):
    return is_news(price, told, told_at, peak_since=peak, now=NOW, after_days=after_days)


class TestTheRule:
    def test_never_mentioned_is_news(self):
        assert news(450.0, told=None) is True

    def test_the_same_price_is_not(self):
        assert news(450.0) is False

    def test_a_new_low_is(self):
        assert news(440.0) is True

    def test_a_rise_is_not(self):
        assert news(480.0) is False

    def test_the_same_price_after_it_went_away_is(self):
        assert news(450.0, peak=500.0) is True

    def test_and_lower_still_after_it_went_away(self):
        assert news(430.0, peak=500.0) is True

    def test_a_partial_retreat_is_not(self):
        assert news(470.0, peak=500.0) is False

    def test_a_peak_no_higher_than_what_we_said_is_no_rebound(self):
        assert news(450.0, peak=450.0) is False

    @pytest.mark.parametrize("told", [449.999, 450.004])
    def test_prices_are_compared_in_cents(self, told):
        """Dollars stored as floats differ from themselves in the last bits."""
        assert news(450.0, told=told) is False


class TestTheExpiry:
    def test_a_notice_older_than_the_expiry_stops_suppressing(self):
        assert news(450.0, told_at=NOW - timedelta(days=31)) is True

    def test_younger_than_it_still_does(self):
        assert news(450.0, told_at=NOW - timedelta(days=29)) is False

    def test_zero_means_it_never_expires(self):
        assert news(450.0, told_at=NOW - timedelta(days=400), after_days=0) is False

    def test_a_naive_timestamp_from_the_database_is_read_as_utc(self):
        assert news(450.0, told_at=(NOW - timedelta(days=31)).replace(tzinfo=None)) is True

    def test_even_expired_a_rise_is_a_reminder_of_a_worse_price(self):
        """After the expiry the listing is simply mentioned again at whatever
        it costs, provided it still qualifies (under the target, or still a
        deal): a reminder, not a claim that the price fell."""
        assert news(480.0, told_at=NOW - timedelta(days=31)) is True
