"""Every scraper, run against a recorded copy of the shop it reads.

**What this is for.** A scraper is a parser for markup nobody here controls,
and the only thing that ever proves one still works is running it against that
markup. The suite could not do that: the choice was a hand-trimmed string
literal, which is a fragment of one page, or asking the vendor, which a test
suite must not do. So a parser could be broken by a refactor and stay green
until a scan ran at three in the morning and brought back nothing.

A recording is a scan's worth of real responses saved to disk. These tests
replay them with no network at all.

**They assert shape, never contents.** A recording is a photograph of a shop on
one day; asserting that it still sells a particular Mosin would be a test that
fails when somebody buys it. What is pinned is what the rest of the application
requires of every scraper regardless of vendor: that listings come back at all,
that each carries the identity the database keys on, and that nothing arrives
in a state the scan service would have to repair. A recording going stale is
ordinary and means re-record it. A recording that no longer *parses* is the
regression this exists to catch.

Record with ``scripts/record-fixtures.py``; see :mod:`recordings`.
"""

from __future__ import annotations

import contextlib

import pytest
from recordings import available, load, replaying

from app.scrapers import get_scraper
from app.scrapers.base import ScrapeCanceled

RECORDED = available()

#: Skip cleanly rather than fail when a site has no recording yet. A suite that
#: went red for a fixture nobody had taken would teach people to record badly.
requires_recordings = pytest.mark.skipif(not RECORDED, reason="no recordings on disk")


@pytest.fixture(params=RECORDED or ["none"])
def recorded(request):
    if not RECORDED:
        pytest.skip("no recordings on disk")
    return load(request.param)


def items_from(recording, context):
    """Everything the scraper parsed before the recording ran out.

    Running off the end is how a capped recording ends, and it arrives as the
    application's own cancellation -- which scrapers rightly do not catch,
    because a real cancellation must stop a scan. So it is caught here, once,
    and what was parsed up to that point is the answer.

    Collected eagerly rather than left as a generator: every assertion below
    needs the whole list, and consuming a generator twice would silently test
    nothing the second time.
    """
    found: list = []
    scan = get_scraper(recording.slug).scrape(replaying(context, recording))
    # The recording ending is not a fault, and `extend` keeps what a
    # partly-consumed generator already yielded.
    with contextlib.suppress(ScrapeCanceled):
        found.extend(scan)
    return found


@requires_recordings
class TestEveryRecordedShopStillParses:
    def test_it_yields_listings(self, recorded, ctx_factory, app_config):
        """The regression that matters: a parser that has stopped finding
        anything. It is silent in production -- a scan reports success with an
        empty catalog -- and obvious here."""
        items = items_from(recorded, ctx_factory())
        assert items, (
            f"{recorded.slug} parsed none of its {len(recorded)} recorded page(s). "
            f"Recorded {recorded.recorded_at}."
        )

    def test_every_listing_can_be_stored(self, recorded, ctx_factory, app_config):
        """The fields the database keys on, which no scan can repair after the
        fact: a listing with no external key cannot be matched to itself on the
        next run, and one with no URL cannot be opened by the person it is
        shown to."""
        for item in items_from(recorded, ctx_factory()):
            assert item.external_key, f"{recorded.slug}: a listing arrived with no key"
            assert item.url, f"{recorded.slug}: {item.external_key} has no URL"
            assert (
                item.title and item.title.strip()
            ), f"{recorded.slug}: {item.external_key} has no title"

    def test_keys_are_unique_within_a_scan(self, recorded, ctx_factory, app_config):
        """Two listings sharing a key is one listing overwriting the other on
        every scan, forever, with nothing to see."""
        keys = [i.external_key for i in items_from(recorded, ctx_factory())]
        duplicated = {k for k in keys if keys.count(k) > 1}
        assert not duplicated, f"{recorded.slug}: repeated keys {sorted(duplicated)[:5]}"

    def test_no_price_is_a_number_that_cannot_be_one(self, recorded, ctx_factory, app_config):
        """None is a fine answer -- plenty of these shops price on request.
        Zero or a negative number is a parse that went wrong, and it reaches
        the "is this a good deal?" comparison and the watchlist alerts."""
        for item in items_from(recorded, ctx_factory()):
            if item.price is not None:
                assert item.price > 0, f"{recorded.slug}: {item.external_key} priced {item.price}"


@requires_recordings
class TestTheRecordingsThemselves:
    def test_each_one_has_pages(self, recorded):
        assert len(recorded) > 0

    def test_asking_for_something_unrecorded_says_how_to_fix_it(self, recorded):
        """The failure a stale recording actually produces, so it arrives as an
        instruction rather than a KeyError."""
        from recordings import NotRecorded

        with pytest.raises(NotRecorded, match="record-fixtures"):
            recorded.text("https://example.invalid/never-fetched")


#: Scrapers that cannot have an HTTP recording, and why.
#:
#: Kept as a list with reasons rather than as a silent gap, so a scraper added
#: without a fixture fails the test below instead of quietly never being
#: exercised. Removing a name from here means recording it.
NOT_RECORDABLE = {
    "royal-tiger": "renders its catalog in JavaScript; its fixture is a rendered page, tested in test_royal_tiger.py",
    "simpson-ltd": "catalog is in Firestore, which refuses an unauthenticated read",
    "hunters-lodge": "reads a PDF flyer through OCR, not HTML — see test_flyer.py",
}


class TestEveryScraperIsCovered:
    """The rule the fixtures exist to make enforceable.

    A scraper with no recording is one nobody is testing against real markup,
    and the gap is invisible: the suite is green because there is nothing to
    run, not because the parser works.
    """

    def test_every_scraper_has_a_recording_or_a_stated_reason(self):
        from app.scrapers import SCRAPER_CLASSES

        registered = {cls.slug for cls in SCRAPER_CLASSES}
        missing = registered - set(RECORDED) - set(NOT_RECORDABLE)
        assert not missing, (
            "no recorded fixture for: " + ", ".join(sorted(missing)) + ".\n"
            "  Record it:  make record-fixtures SITE=<slug>\n"
            "  Or, if it cannot be recorded over HTTP, add it to NOT_RECORDABLE "
            "with the reason."
        )

    def test_the_exemptions_are_all_real_scrapers(self):
        """An exemption for a scraper that no longer exists is a name nobody
        will ever remove, hiding whatever takes its slug next."""
        from app.scrapers import SCRAPER_CLASSES

        registered = {cls.slug for cls in SCRAPER_CLASSES}
        assert not set(NOT_RECORDABLE) - registered

    def test_an_exemption_is_not_also_recorded(self):
        """If it turned out to be recordable, the reason is now wrong."""
        assert not set(NOT_RECORDABLE) & set(RECORDED)

    def test_nothing_replayed_would_open_a_browser(self):
        """The guard that matters, because getting this wrong is not a red
        test -- it is the suite quietly fetching from a vendor.

        Royal Tiger has a fixture directory of its own (a rendered page), and
        the first version of the exclusion trusted only the manifest's label.
        A mislabelled manifest sent `scrape()` off to open Chrome and go to the
        shop, which is the one thing these tests exist to stop.
        """
        from app.scrapers import get_scraper

        driving = [s for s in RECORDED if getattr(get_scraper(s), "requires_browser", False)]
        assert not driving, f"replaying these would reach the network: {driving}"
