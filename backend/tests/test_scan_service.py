"""The scan engine: upserts, price history, de-listing and run bookkeeping.

Driven by a fake scraper registered into the registry, so the whole reconcile
path runs without touching a vendor site or a browser.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import (
    ArmoryStatus,
    FirearmKind,
    FirearmModel,
    Item,
    ItemPhoto,
    PriceHistory,
    ScanRun,
    ScanStatus,
    Site,
    utcnow,
)
from app.scrapers import ScrapedItem, ScrapeError, SiteScraper
from app.services import armory, scan_service
from app.services.image_store import FetchResult, ImageStore, StoredImage


class FakeScraper(SiteScraper):
    """Returns whatever the test hands it."""

    slug = "fake-vendor"
    name = "Fake Vendor"
    base_url = "https://fake.test/"
    description = "Test double."
    requires_browser = False
    default_interval_minutes = 60

    #: Set by the fixture before each run.
    payload: list[ScrapedItem] = []
    raise_error: str | None = None
    warn_with: str | None = None
    #: Yield this many listings, then raise, to model a scan that is cut off
    #: part way through — a restart, a killed process, a network collapse.
    fail_after: int | None = None
    #: Called after each listing is yielded, standing in for the network wait
    #: a real scraper takes before producing the next one.
    between_items = None

    def scrape(self, ctx):
        if self.raise_error:
            raise ScrapeError(self.raise_error)
        if self.warn_with:
            ctx.warn(self.warn_with)
        ctx.log(f"Returning {len(self.payload)} listing(s).")
        return self._stream(ctx)

    def _stream(self, ctx):
        for index, item in enumerate(self.payload):
            if self.fail_after is not None and index >= self.fail_after:
                raise ScrapeError("connection lost part way through")
            yield item
            # Where a real scraper spends twenty seconds fetching the next
            # page. Anything the scan is holding, it holds across this.
            #
            # Read off the class, not off self: a plain function stored on the
            # class becomes a bound method through an instance, and the hook
            # would be handed the scraper as its first argument.
            hook = FakeScraper.between_items
            if hook is not None:
                hook(index)


@pytest.fixture
def fake_site(clean_db, monkeypatch):
    """Register FakeScraper and give it a site row."""
    from app import scrapers

    monkeypatch.setitem(scrapers._REGISTRY, FakeScraper.slug, FakeScraper)
    site = Site(
        slug=FakeScraper.slug,
        name=FakeScraper.name,
        base_url=FakeScraper.base_url,
        enabled=True,
        scan_interval_minutes=60,
    )
    FakeScraper.between_items = None
    clean_db.add(site)
    clean_db.commit()
    yield site
    FakeScraper.payload = []
    FakeScraper.raise_error = None
    FakeScraper.warn_with = None
    FakeScraper.fail_after = None


def listing(key: str, price: float | None = 500.0, **overrides) -> ScrapedItem:
    defaults = dict(
        external_key=key,
        url=f"https://fake.test/{key}",
        title=f"Test rifle {key}",
        price=price,
        description="A rifle.",
        category="Rifle",
    )
    defaults.update(overrides)
    return ScrapedItem(**defaults)


class TestFirstScan:
    def test_creates_items_and_prices(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a", 500.0), listing("b", 900.0)]
        run_id = scan_service.run_scan(fake_site.id, trigger="cli")

        run = clean_db.get(ScanRun, run_id)
        assert run.status == ScanStatus.SUCCESS
        assert run.items_found == 2
        assert run.items_new == 2
        assert run.items_updated == 0

        items = clean_db.execute(select(Item)).scalars().all()
        assert {i.external_key for i in items} == {"a", "b"}
        assert {i.current_price for i in items} == {500.0, 900.0}
        # A first observation is a price change, so history starts populated.
        assert clean_db.execute(select(PriceHistory)).scalars().all()

    def test_records_the_progress_log(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a")]
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
        assert "Returning 1 listing" in run.log

    def test_schedules_the_next_run(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a")]
        scan_service.run_scan(fake_site.id)
        clean_db.refresh(fake_site)
        assert fake_site.next_scan_at is not None
        assert fake_site.last_success_at is not None


class TestRescan:
    def test_updates_in_place_rather_than_duplicating(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a", 500.0)]
        scan_service.run_scan(fake_site.id)
        FakeScraper.payload = [listing("a", 500.0, title="Renamed rifle")]
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))

        assert run.items_new == 0
        assert run.items_updated == 1
        items = clean_db.execute(select(Item)).scalars().all()
        assert len(items) == 1
        assert items[0].title == "Renamed rifle"

    def test_unchanged_price_writes_no_history_row(self, fake_site, clean_db):
        """History tracks changes, not scans."""
        FakeScraper.payload = [listing("a", 500.0)]
        scan_service.run_scan(fake_site.id)
        before = len(clean_db.execute(select(PriceHistory)).scalars().all())

        scan_service.run_scan(fake_site.id)
        after = len(clean_db.execute(select(PriceHistory)).scalars().all())
        assert after == before

    def test_price_drop_is_recorded(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a", 900.0)]
        scan_service.run_scan(fake_site.id)
        FakeScraper.payload = [listing("a", 700.0)]
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))

        assert run.price_changes == 1
        assert run.price_drops == 1
        item = clean_db.execute(select(Item)).scalars().one()
        assert item.current_price == 700.0
        assert item.previous_price == 900.0
        assert item.lowest_price == 700.0
        assert item.highest_price == 900.0
        assert item.price_drop_amount == 200.0

    def test_price_rise_is_not_a_drop(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a", 500.0)]
        scan_service.run_scan(fake_site.id)
        FakeScraper.payload = [listing("a", 800.0)]
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
        assert run.price_changes == 1
        assert run.price_drops == 0

    def test_sub_cent_differences_are_not_changes(self, fake_site, clean_db):
        """Float noise must not manufacture a price change on every scan."""
        FakeScraper.payload = [listing("a", 500.0)]
        scan_service.run_scan(fake_site.id)
        FakeScraper.payload = [listing("a", 500.001)]
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
        assert run.price_changes == 0


class TestDelisting:
    def test_missing_items_are_delisted(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a"), listing("b")]
        scan_service.run_scan(fake_site.id)
        FakeScraper.payload = [listing("a")]
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))

        assert run.items_delisted == 1
        gone = clean_db.execute(select(Item).where(Item.external_key == "b")).scalars().one()
        assert gone.is_active is False
        assert gone.delisted_at is not None

    def test_returning_item_is_reactivated_but_keeps_its_age(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a")]
        scan_service.run_scan(fake_site.id)
        original = clean_db.execute(select(Item)).scalars().one().first_seen_at

        FakeScraper.payload = []
        scan_service.run_scan(fake_site.id)
        FakeScraper.payload = [listing("a")]
        scan_service.run_scan(fake_site.id)

        item = clean_db.execute(select(Item)).scalars().one()
        assert item.is_active is True
        assert item.delisted_at is None
        # "New" must stay honest across a de-list/re-list cycle.
        assert item.first_seen_at == original


class TestPhotos:
    def test_photo_rows_are_recorded(self, fake_site, clean_db):
        FakeScraper.payload = [
            listing("a", image_urls=["https://fake.test/1.jpg", "https://fake.test/2.jpg"])
        ]
        scan_service.run_scan(fake_site.id)
        photos = clean_db.execute(select(ItemPhoto)).scalars().all()
        assert len(photos) == 2
        assert [p.position for p in sorted(photos, key=lambda x: x.position)] == [0, 1]

    def test_a_richer_gallery_replaces_the_grid_thumbnail(self, fake_site, clean_db):
        """The detail pass supersedes the single listing-grid image."""
        FakeScraper.payload = [listing("a", image_urls=["https://fake.test/thumb.jpg"])]
        scan_service.run_scan(fake_site.id)

        FakeScraper.payload = [
            listing("a", image_urls=["https://fake.test/1.jpg", "https://fake.test/2.jpg"])
        ]
        scan_service.run_scan(fake_site.id)

        urls = {p.source_url for p in clean_db.execute(select(ItemPhoto)).scalars().all()}
        assert urls == {"https://fake.test/1.jpg", "https://fake.test/2.jpg"}


class TestFailures:
    def test_scraper_error_fails_the_run(self, fake_site, clean_db):
        FakeScraper.raise_error = "vendor returned 503"
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
        assert run.status == ScanStatus.FAILED
        assert "vendor returned 503" in run.error_message

    def test_a_warning_downgrades_to_partial(self, fake_site, clean_db):
        FakeScraper.payload = [listing("a")]
        FakeScraper.warn_with = "one page could not be fetched"
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
        assert run.status == ScanStatus.PARTIAL
        assert "one page" in run.error_message

    def test_duplicate_keys_are_collapsed(self, fake_site, clean_db):
        """Two listings sharing a key would violate the unique index."""
        FakeScraper.payload = [listing("a", 100.0), listing("a", 200.0)]
        run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
        assert run.status == ScanStatus.SUCCESS
        assert run.items_found == 1
        assert clean_db.execute(select(Item)).scalars().one().current_price == 200.0

    def test_missing_scraper_marks_the_site_unavailable(self, clean_db):
        orphan = Site(slug="no-such-scraper", name="Orphan", base_url="https://x.test/")
        clean_db.add(orphan)
        clean_db.commit()
        run = clean_db.get(ScanRun, scan_service.run_scan(orphan.id))
        assert run.status == ScanStatus.FAILED
        clean_db.refresh(orphan)
        assert orphan.is_available is False

    def test_concurrent_scan_is_refused(self, fake_site, monkeypatch):
        """One scan per site; a second request is rejected, not queued."""
        monkeypatch.setitem(scan_service._running, fake_site.id, 1)
        try:
            with pytest.raises(scan_service.ScanBusy):
                scan_service.run_scan(fake_site.id)
        finally:
            scan_service._running.pop(fake_site.id, None)


class TestScheduling:
    def test_due_sites(self, fake_site, clean_db):
        # next_scan_at is NULL on a fresh site, which means "due now".
        assert fake_site.id in scan_service.due_site_ids(clean_db)

    def test_disabled_sites_are_never_due(self, fake_site, clean_db):
        fake_site.enabled = False
        clean_db.commit()
        assert fake_site.id not in scan_service.due_site_ids(clean_db)

    def test_unavailable_sites_are_never_due(self, fake_site, clean_db):
        fake_site.is_available = False
        clean_db.commit()
        assert fake_site.id not in scan_service.due_site_ids(clean_db)

    def test_reaping_orphaned_runs(self, fake_site, clean_db, app_config):
        stale = ScanRun(site_id=fake_site.id, status=ScanStatus.RUNNING)
        clean_db.add(stale)
        clean_db.commit()

        assert scan_service.reap_stale_runs(clean_db, app_config) == 1
        clean_db.refresh(stale)
        assert stale.status == ScanStatus.FAILED
        assert "did not finish" in stale.error_message


class TestInterruptedScanKeepsItsWork:
    """A scan cut off part way must not throw away what it already had.

    This is the Royal Tiger case: sixteen minutes of browser work, a restart at
    minute fifteen, and — before the scan service consumed the scraper lazily —
    nothing at all to show for it.
    """

    def test_listings_scraped_before_the_failure_are_saved(self, fake_site, clean_db):
        FakeScraper.payload = [listing(f"k{n}") for n in range(10)]
        FakeScraper.fail_after = 6

        run_id = scan_service.run_scan(fake_site.id, trigger="manual")

        run = clean_db.get(ScanRun, run_id)
        assert run.status == ScanStatus.FAILED

        # The six that were yielded are on disk; the four that were not are not.
        keys = set(
            clean_db.execute(select(Item.external_key).where(Item.site_id == fake_site.id))
            .scalars()
            .all()
        )
        assert keys == {f"k{n}" for n in range(6)}

    def test_a_partial_scan_does_not_de_list_what_it_never_reached(self, fake_site, clean_db):
        # A complete scan first, so there is existing inventory to lose.
        FakeScraper.payload = [listing(f"k{n}") for n in range(10)]
        scan_service.run_scan(fake_site.id, trigger="manual")
        assert (
            clean_db.execute(
                select(Item).where(Item.site_id == fake_site.id, Item.is_active.is_(True))
            )
            .scalars()
            .all()
            .__len__()
            == 10
        )

        # Now a scan that dies after two listings. The other eight were never
        # reported missing — they were never looked at — so they must stay.
        FakeScraper.fail_after = 2
        scan_service.run_scan(fake_site.id, trigger="manual")

        still_active = (
            clean_db.execute(
                select(Item).where(Item.site_id == fake_site.id, Item.is_active.is_(True))
            )
            .scalars()
            .all()
        )
        assert len(still_active) == 10

    def test_the_next_scan_completes_the_job(self, fake_site, clean_db):
        FakeScraper.payload = [listing(f"k{n}") for n in range(10)]
        FakeScraper.fail_after = 6
        scan_service.run_scan(fake_site.id, trigger="manual")

        FakeScraper.fail_after = None
        run_id = scan_service.run_scan(fake_site.id, trigger="manual")

        run = clean_db.get(ScanRun, run_id)
        assert run.status == ScanStatus.SUCCESS
        assert run.items_found == 10
        # The six already stored are updates, not new listings.
        assert run.items_new == 4
        assert run.items_updated == 6


class TestRepeatedKeysInOneRun:
    """A scraper may yield a key twice: cheap version first, detailed second."""

    def test_the_later_version_wins_and_is_counted_once(self, fake_site, clean_db):
        FakeScraper.payload = [
            listing("k1", price=500.0, description=None),
            listing("k1", price=450.0, description="Now with the detail page text."),
        ]

        run_id = scan_service.run_scan(fake_site.id, trigger="manual")
        run = clean_db.get(ScanRun, run_id)

        item = clean_db.execute(select(Item).where(Item.external_key == "k1")).scalars().one()
        assert item.current_price == 450.0
        assert item.description == "Now with the detail page text."

        # One listing, not two, and it must not be double-counted as new.
        assert run.items_found == 1
        assert run.items_new == 1
        assert run.items_updated == 0

    def test_a_repeat_does_not_de_list_anything(self, fake_site, clean_db):
        FakeScraper.payload = [listing("k1"), listing("k2"), listing("k1")]
        run_id = scan_service.run_scan(fake_site.id, trigger="manual")
        run = clean_db.get(ScanRun, run_id)
        assert run.items_delisted == 0
        assert run.items_found == 2


class TestAPreviewNeverDestroysAGallery:
    """The catalog grid knows one photo. It must not speak for the rest.

    Royal Tiger yields each listing twice: once from the grid with its single
    low-resolution thumbnail, then again once the detail page has supplied the
    real gallery. Before ScrapedItem.images_are_complete existed, the grid pass
    was treated as authoritative and pruned everything it did not mention —
    which cut 207 live listings down from six and seven photos to one.
    """

    def _detailed(self, key, urls):
        item = listing(key)
        item.image_urls = list(urls)
        item.images_are_complete = True
        return item

    def _preview(self, key, url):
        item = listing(key)
        item.image_urls = [url]
        item.images_are_complete = False
        return item

    def _photo_urls(self, session, key):
        item = session.execute(select(Item).where(Item.external_key == key)).scalars().one()
        return [p.source_url for p in sorted(item.photos, key=lambda p: p.position)]

    def test_a_later_preview_leaves_the_gallery_alone(self, fake_site, clean_db):
        gallery = [f"https://fake.test/{n}.jpg" for n in range(6)]
        FakeScraper.payload = [self._detailed("k1", gallery)]
        scan_service.run_scan(fake_site.id, trigger="manual")
        assert self._photo_urls(clean_db, "k1") == gallery

        # A later scan that only got as far as the grid.
        FakeScraper.payload = [self._preview("k1", "https://fake.test/thumb.jpg")]
        scan_service.run_scan(fake_site.id, trigger="manual")
        assert self._photo_urls(clean_db, "k1") == gallery

    def test_a_preview_still_seeds_a_listing_that_has_no_photos_yet(self, fake_site, clean_db):
        FakeScraper.payload = [self._preview("k1", "https://fake.test/thumb.jpg")]
        scan_service.run_scan(fake_site.id, trigger="manual")
        # Something to show in the grid straight away, rather than a blank card.
        assert self._photo_urls(clean_db, "k1") == ["https://fake.test/thumb.jpg"]

    def test_a_complete_record_still_prunes_what_the_vendor_removed(self, fake_site, clean_db):
        FakeScraper.payload = [self._detailed("k1", ["a.jpg", "b.jpg", "c.jpg"])]
        scan_service.run_scan(fake_site.id, trigger="manual")

        FakeScraper.payload = [self._detailed("k1", ["a.jpg", "c.jpg"])]
        scan_service.run_scan(fake_site.id, trigger="manual")
        assert self._photo_urls(clean_db, "k1") == ["a.jpg", "c.jpg"]

    def test_a_preview_replaces_a_previous_preview(self, fake_site, clean_db):
        """Two grid passes in a row: the newer thumbnail wins, nothing is lost."""
        FakeScraper.payload = [self._preview("k1", "old-thumb.jpg")]
        scan_service.run_scan(fake_site.id, trigger="manual")
        FakeScraper.payload = [self._preview("k1", "new-thumb.jpg")]
        scan_service.run_scan(fake_site.id, trigger="manual")
        # Still exactly one photo; a preview must not accumulate junk either.
        assert len(self._photo_urls(clean_db, "k1")) == 1


class TestNeedsDetailIsRecordedNotGuessed:
    def test_a_preview_does_not_mark_the_listing_as_fetched(self, fake_site, clean_db):
        item = listing("k1")
        item.image_urls = ["thumb.jpg"]
        item.images_are_complete = False
        FakeScraper.payload = [item]
        scan_service.run_scan(fake_site.id, trigger="manual")

        stored = clean_db.execute(select(Item).where(Item.external_key == "k1")).scalars().one()
        # Photo rows and a description are not evidence of a detail fetch —
        # that inference is what destroyed the Royal Tiger galleries.
        assert stored.photos
        assert stored.description
        assert stored.detail_fetched_at is None

    def test_a_complete_record_marks_it(self, fake_site, clean_db):
        item = listing("k1")
        item.image_urls = ["a.jpg", "b.jpg"]
        FakeScraper.payload = [item]
        scan_service.run_scan(fake_site.id, trigger="manual")

        stored = clean_db.execute(select(Item).where(Item.external_key == "k1")).scalars().one()
        assert stored.detail_fetched_at is not None


class TestDueSiteIds:
    """The scheduler's one question: which sites should be scanned now?

    Answering it wrongly is invisible. `Scheduler._loop` isolates each tick so
    one bad tick cannot kill the thread, which means a tick that raises every
    time looks exactly like a tick with nothing to do — a scheduler thread
    alive, ticking, and never scanning anything.
    """

    def _read_back(self, session, site, next_scan_at):
        """Set next_scan_at and force it to be re-read from the database.

        The expire is the whole point. Held in memory the value is whatever
        Python assigned, timezone and all; read back from SQLite — which has no
        timezone type — it is naive. Only the second one is what the scheduler
        actually sees, and comparing it with the aware utcnow() raised
        TypeError. Without the expire this test passes against the bug.
        """
        site.next_scan_at = next_scan_at
        session.commit()
        session.expire_all()

    def test_a_site_whose_time_has_passed_is_due(self, fake_site, clean_db):
        self._read_back(clean_db, fake_site, utcnow() - timedelta(hours=1))
        assert scan_service.due_site_ids(clean_db) == [fake_site.id]

    def test_a_site_scheduled_for_later_is_not_due(self, fake_site, clean_db):
        self._read_back(clean_db, fake_site, utcnow() + timedelta(hours=1))
        assert scan_service.due_site_ids(clean_db) == []

    def test_a_site_that_has_never_been_scanned_is_due(self, fake_site, clean_db):
        # This is the one case that worked before: a NULL never reaches the
        # comparison, which is why every site scanned exactly once and then
        # never again.
        self._read_back(clean_db, fake_site, None)
        assert scan_service.due_site_ids(clean_db) == [fake_site.id]

    def test_a_completed_scan_leaves_the_site_due_again_later(self, fake_site, clean_db):
        FakeScraper.payload = [listing("k1")]
        scan_service.run_scan(fake_site.id, trigger="scheduled")
        clean_db.expire_all()

        site = clean_db.get(Site, fake_site.id)
        assert site.next_scan_at is not None
        assert scan_service.due_site_ids(clean_db) == []

        # Wind the clock past the interval; the site must come round again.
        self._read_back(clean_db, site, utcnow() - timedelta(minutes=1))
        assert scan_service.due_site_ids(clean_db) == [fake_site.id]

    def test_a_disabled_site_is_never_due(self, fake_site, clean_db):
        fake_site.enabled = False
        self._read_back(clean_db, fake_site, utcnow() - timedelta(hours=1))
        assert scan_service.due_site_ids(clean_db) == []


class TestDownloadPendingPhotos:
    """Draining the photo queue without re-scraping.

    A scan caps its own image downloads so a first pass over a large catalog
    cannot run for hours, and carries the rest forward. Left to scans alone
    that backlog drained one batch a day; the scheduler now works through it in
    the background, and this is the function it calls.
    """

    @pytest.fixture
    def images_enabled(self, monkeypatch, app_config):
        """Turn image downloading on for this class.

        The suite's config has `download_images: false`, which makes
        _download_photos return 0 before it looks at anything — so without this
        every test here would pass for the wrong reason.
        """
        enabled = dataclasses.replace(
            app_config, scraping=dataclasses.replace(app_config.scraping, download_images=True)
        )
        monkeypatch.setattr(scan_service, "get_config", lambda: enabled)
        return enabled

    def _seed_photos(self, session, site, count):
        item = Item(
            site_id=site.id,
            external_key="k1",
            url="https://fake.test/k1",
            title="Test rifle",
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
        )
        session.add(item)
        session.flush()
        for position in range(count):
            session.add(
                ItemPhoto(
                    item_id=item.id,
                    source_url=f"https://fake.test/{position}.jpg",
                    position=position,
                )
            )
        session.commit()
        return item

    def test_nothing_queued_is_not_an_error(self, fake_site, clean_db, images_enabled):
        assert scan_service.download_pending_photos() == 0

    def _always_fails(self, monkeypatch, reason="404 Not Found", permanent=True):
        """A store where every photograph refuses to arrive."""
        calls: list[str] = []

        class FailingStore:
            def __init__(self, _config):
                pass

            def fetch(self, _session, _slug, url):
                calls.append(url)
                return FetchResult(None, reason, permanent=permanent)

        monkeypatch.setattr(scan_service, "ImageStore", FailingStore)
        return calls

    def test_a_failure_is_counted_and_its_reason_kept(
        self, fake_site, clean_db, monkeypatch, images_enabled
    ):
        """Without this a queued photo that can never arrive is indistinguishable
        from one not reached yet."""
        self._seed_photos(clean_db, fake_site, 2)
        self._always_fails(monkeypatch)

        assert scan_service.download_pending_photos() == 0

        photos = clean_db.execute(select(ItemPhoto)).scalars().all()
        assert [photo.attempts for photo in photos] == [1, 1]
        assert all(photo.last_error == "404 Not Found" for photo in photos)
        assert all(photo.last_attempt_at is not None for photo in photos)
        assert all(photo.filename is None for photo in photos)

    def test_it_gives_up_after_enough_failures(
        self, fake_site, clean_db, monkeypatch, images_enabled
    ):
        """A dead URL used to be retried on every scan for the life of the
        listing, silently."""
        self._seed_photos(clean_db, fake_site, 1)
        calls = self._always_fails(monkeypatch)

        for _ in range(scan_service.MAX_PHOTO_ATTEMPTS + 3):
            scan_service.download_pending_photos()

        assert len(calls) == scan_service.MAX_PHOTO_ATTEMPTS

    def test_a_passing_failure_does_not_count_against_the_budget(
        self, fake_site, clean_db, monkeypatch, images_enabled
    ):
        """A 429 is the shop having a bad afternoon, not a broken URL.

        Counting those would strand every photograph the afternoon touched —
        which is what the host cooldown exists to prevent, not to cause.
        """
        self._seed_photos(clean_db, fake_site, 1)
        calls = self._always_fails(monkeypatch, "429 after 3 attempts", permanent=False)

        for _ in range(scan_service.MAX_PHOTO_ATTEMPTS + 2):
            scan_service.download_pending_photos()

        assert len(calls) == scan_service.MAX_PHOTO_ATTEMPTS + 2, "still being tried"
        photo = clean_db.execute(select(ItemPhoto)).scalars().one()
        assert photo.attempts == 0
        # The error is still recorded, so it is visible rather than silent.
        assert photo.last_error == "429 after 3 attempts"
        assert photo.last_attempt_at is not None

    def test_the_queue_puts_the_failures_last(
        self, fake_site, clean_db, monkeypatch, images_enabled
    ):
        """The budget is finite, so a handful of dead rows at the front of an
        unordered queue starve every photograph behind them."""
        self._seed_photos(clean_db, fake_site, 4)
        photos = clean_db.execute(select(ItemPhoto).order_by(ItemPhoto.id)).scalars().all()
        # The first two have already failed once; the last two are untouched.
        for photo in photos[:2]:
            photo.attempts = 1
        clean_db.commit()
        fresh = [photo.source_url for photo in photos[2:]]

        calls = self._always_fails(monkeypatch)
        scan_service.download_pending_photos(limit=2)

        assert calls == fresh

    def test_retrying_clears_the_count_so_they_are_tried_again(
        self, fake_site, clean_db, monkeypatch, images_enabled
    ):
        """The right thing after fixing whatever was wrong, and the wrong thing
        to do on a schedule — hence a flag rather than the default."""
        self._seed_photos(clean_db, fake_site, 1)
        calls = self._always_fails(monkeypatch)

        for _ in range(scan_service.MAX_PHOTO_ATTEMPTS):
            scan_service.download_pending_photos()
        assert len(calls) == scan_service.MAX_PHOTO_ATTEMPTS

        scan_service.download_pending_photos()
        assert len(calls) == scan_service.MAX_PHOTO_ATTEMPTS, "given up on, so not asked again"

        scan_service.download_pending_photos(retry_failed=True)
        assert len(calls) == scan_service.MAX_PHOTO_ATTEMPTS + 1

    def test_a_success_clears_a_previous_error(
        self, fake_site, clean_db, monkeypatch, images_enabled
    ):
        self._seed_photos(clean_db, fake_site, 1)
        photo = clean_db.execute(select(ItemPhoto)).scalars().one()
        photo.attempts, photo.last_error = 1, "429 Too Many Requests"
        clean_db.commit()

        class WorkingStore:
            def __init__(self, _config):
                pass

            def fetch(self, _session, _slug, _url):
                return FetchResult(
                    StoredImage(filename="s/a.jpg", content_type="image/jpeg", bytes=10), None
                )

        monkeypatch.setattr(scan_service, "ImageStore", WorkingStore)
        assert scan_service.download_pending_photos() == 1

        clean_db.expire_all()
        photo = clean_db.execute(select(ItemPhoto)).scalars().one()
        assert photo.filename == "s/a.jpg"
        assert photo.last_error is None

    def test_it_stops_at_the_limit_and_leaves_the_rest_queued(
        self, fake_site, clean_db, monkeypatch, images_enabled
    ):
        self._seed_photos(clean_db, fake_site, 5)

        calls: list[str] = []

        class FakeStore:
            def __init__(self, _config):
                pass

            def fetch(self, _session, _slug, url):
                calls.append(url)
                return FetchResult(
                    StoredImage(
                        filename=f"f/{len(calls)}.jpg",
                        content_type="image/jpeg",
                        bytes=10,
                        thumb_filename=f"f/{len(calls)}_t.jpg",
                        thumb_bytes=5,
                        width=10,
                        height=10,
                    ),
                    None,
                )

        monkeypatch.setattr(scan_service, "ImageStore", FakeStore)

        assert scan_service.download_pending_photos(limit=2) == 2
        assert len(calls) == 2

        # The remainder is still waiting, not lost.
        remaining = (
            clean_db.execute(select(ItemPhoto).where(ItemPhoto.filename.is_(None))).scalars().all()
        )
        assert len(remaining) == 3

        # A second pass picks up where the first stopped.
        assert scan_service.download_pending_photos(limit=10) == 3
        assert len(calls) == 5

    def test_an_unknown_site_is_rejected(self, fake_site, clean_db, images_enabled):
        with pytest.raises(scan_service.ScanBusy):
            scan_service.download_pending_photos(site_slug="no-such-vendor")


class TestGeneratedCropsFollowTheReader:
    """A crop this application cuts is only as good as the code that cut it.

    Photographs come from a URL and do not change unless the vendor changes
    them, so recognizing one by its key is right. A crop out of a flyer is
    different: the page has not changed, but the reader has, and when it
    learned to include the heading above the picture every crop moved. Skipping
    on the key alone left every listing showing the picture it had been cut
    before, under its new and correct title.
    """

    @pytest.fixture(autouse=True)
    def storing_images(self, app_config, monkeypatch, tmp_path):
        """The suite runs with image storage off; these tests are about it."""
        config = dataclasses.replace(
            app_config,
            images_path=tmp_path / "images",
            scraping=dataclasses.replace(app_config.scraping, download_images=True),
        )
        config.images_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("app.services.scan_service.get_config", lambda: config)
        return config

    @staticmethod
    def png(shade: int, size: tuple[int, int] = (40, 30)) -> bytes:
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("L", size, shade).save(buffer, format="PNG")
        return buffer.getvalue()

    def photos_of(self, session, key="a"):
        item = session.execute(select(Item).where(Item.external_key == key)).scalar_one()
        return (
            session.execute(select(ItemPhoto).where(ItemPhoto.item_id == item.id)).scalars().all()
        )

    def test_an_unchanged_crop_is_left_alone(self, clean_db, fake_site):
        image = self.png(120)
        FakeScraper.payload = [listing("a", generated_images=[("a-001", image)])]
        scan_service.run_scan(fake_site.id, trigger="test")
        first = self.photos_of(clean_db)[0].downloaded_at

        scan_service.run_scan(fake_site.id, trigger="test")
        clean_db.expire_all()
        again = self.photos_of(clean_db)

        assert len(again) == 1
        assert again[0].downloaded_at == first

    def test_a_changed_crop_replaces_the_stored_one(self, clean_db, fake_site):
        FakeScraper.payload = [listing("a", generated_images=[("a-001", self.png(120))])]
        scan_service.run_scan(fake_site.id, trigger="test")

        taller = self.png(120, size=(40, 90))
        FakeScraper.payload = [listing("a", generated_images=[("a-001", taller)])]
        scan_service.run_scan(fake_site.id, trigger="test")
        clean_db.expire_all()
        photos = self.photos_of(clean_db)

        # Replaced in place, not added beside: the key is still the same crop.
        assert len(photos) == 1
        assert photos[0].height == 90
        assert photos[0].bytes == len(taller)

    def test_the_same_size_but_different_pixels_still_counts(
        self, clean_db, fake_site, storing_images
    ):
        """Comparing lengths alone would call these two the same picture."""
        FakeScraper.payload = [listing("a", generated_images=[("a-001", self.png(0))])]
        scan_service.run_scan(fake_site.id, trigger="test")

        other = self.png(255)
        FakeScraper.payload = [listing("a", generated_images=[("a-001", other)])]
        scan_service.run_scan(fake_site.id, trigger="test")
        clean_db.expire_all()

        store = ImageStore(storing_images)
        stored = store.absolute_path(self.photos_of(clean_db)[0].filename).read_bytes()
        assert stored == other


class TestDescriptiveFieldsAreDerivedWhereTheVendorGivesNone:
    """A catalog with no field for the caliber still names it in the title.

    Royal Tiger publishes the caliber, the country and the condition as their
    own fields; a WooCommerce shop has nowhere structured to put them. The
    first one read in came back with "7.62x54R" in every title and nothing in
    the column.
    """

    def stored(self, session, key="a"):
        return session.execute(select(Item).where(Item.external_key == key)).scalar_one()

    def test_they_are_read_out_of_the_text(self, clean_db, fake_site):
        FakeScraper.payload = [
            listing(
                "a",
                title="WWII Russian Izhevsk M91/30 Mosin-Nagant 7.62x54R",
                description="Bore is excellent with strong rifling.",
                caliber=None,
                country=None,
                condition=None,
            )
        ]
        scan_service.run_scan(fake_site.id, trigger="test")

        item = self.stored(clean_db)
        assert item.caliber == "7.62x54R"
        assert item.country == "Russia"
        assert item.condition == "Excellent"

    def test_what_the_vendor_states_is_never_overwritten(self, clean_db, fake_site):
        """Their field beats our reading of their prose."""
        FakeScraper.payload = [
            listing(
                "a",
                title="Mosin-Nagant 7.62x54R",
                description="Bore is excellent.",
                caliber="7.62x54mmR",
                country="Soviet Union",
                condition="Fair",
            )
        ]
        scan_service.run_scan(fake_site.id, trigger="test")

        item = self.stored(clean_db)
        assert (item.caliber, item.country, item.condition) == (
            "7.62x54mmR",
            "Soviet Union",
            "Fair",
        )


class TestTheArmorySuppliesACountryNobodyStated:
    """The case the model's country exists for.

    "M1 Garand, EXC, all matching" names no country and there is nothing in it
    to read one out of, so the listing had none -- and the browse page's
    country filter had no opinion about it. The armory knows the pattern is
    American whoever built the rifle.
    """

    def stored(self, session, key="a"):
        return session.execute(select(Item).where(Item.external_key == key)).scalar_one()

    @pytest.fixture
    def garand(self, clean_db):
        row = FirearmModel(
            name="M1 Garand",
            kind=FirearmKind.RIFLE,
            country="United States",
            status=ArmoryStatus.APPROVED,
        )
        clean_db.add(row)
        clean_db.commit()
        armory.invalidate()
        yield row
        armory.invalidate()

    def test_a_title_that_names_no_country_gets_the_models(self, clean_db, fake_site, garand):
        FakeScraper.payload = [
            listing("a", title="M1 Garand, EXC, all matching", description=None, country=None)
        ]
        scan_service.run_scan(fake_site.id, trigger="test")
        assert self.stored(clean_db).country == "United States"

    def test_a_title_that_names_one_keeps_what_it_says(self, clean_db, fake_site, garand):
        """A K98k assembled in Brno after the war is a German pattern made in
        Czechoslovakia, and whoever wrote the listing was looking at the gun."""
        FakeScraper.payload = [
            listing("a", title="Italian M1 Garand, Beretta rebuild", country=None)
        ]
        scan_service.run_scan(fake_site.id, trigger="test")
        assert self.stored(clean_db).country == "Italy"

    def test_and_so_does_a_vendor_who_states_one(self, clean_db, fake_site, garand):
        FakeScraper.payload = [
            listing("a", title="M1 Garand, EXC, all matching", country="Denmark")
        ]
        scan_service.run_scan(fake_site.id, trigger="test")
        assert self.stored(clean_db).country == "Denmark"

    def test_a_pending_model_supplies_nothing(self, clean_db, fake_site, garand):
        garand.status = ArmoryStatus.PENDING
        clean_db.commit()
        armory.invalidate()
        FakeScraper.payload = [
            listing("a", title="M1 Garand, EXC, all matching", description=None, country=None)
        ]
        scan_service.run_scan(fake_site.id, trigger="test")
        assert self.stored(clean_db).country is None


class TestAScanFillsTheArmoryQueue:
    """The half that was missing: the armory was read by every scan and never
    written to, so meeting a gun the table had never heard of recorded nothing.
    """

    def test_an_unknown_designation_is_proposed(self, clean_db, fake_site):
        FakeScraper.payload = [
            listing("a", title="Winchester Model 1873 Lever Action Rifle", caliber=None)
        ]
        scan_service.run_scan(fake_site.id, trigger="test")
        row = clean_db.query(FirearmModel).filter_by(name="Model 1873").one()
        assert row.status is ArmoryStatus.PENDING
        assert "Winchester" in (row.first_seen_in or "")

    def test_it_is_reported_in_the_scan_log(self, clean_db, fake_site):
        FakeScraper.payload = [
            listing("a", title="Winchester Model 1873 Lever Action Rifle", caliber=None)
        ]
        run_id = scan_service.run_scan(fake_site.id, trigger="test")
        run = clean_db.get(ScanRun, run_id)
        assert "Armory: proposed" in (run.log or "")

    def test_it_does_not_make_the_scan_partial(self, clean_db, fake_site):
        """Proposals are housekeeping. They must not change what a scan reports
        about the catalog it just saved."""
        FakeScraper.payload = [
            listing("a", title="Winchester Model 1873 Lever Action Rifle", caliber=None)
        ]
        run_id = scan_service.run_scan(fake_site.id, trigger="test")
        assert clean_db.get(ScanRun, run_id).status is ScanStatus.SUCCESS

    def test_a_second_scan_proposes_nothing_new(self, clean_db, fake_site):
        FakeScraper.payload = [
            listing("a", title="Winchester Model 1873 Lever Action Rifle", caliber=None)
        ]
        scan_service.run_scan(fake_site.id, trigger="test")
        run_id = scan_service.run_scan(fake_site.id, trigger="test")
        assert "Armory: proposed" not in (clean_db.get(ScanRun, run_id).log or "")
        assert clean_db.query(FirearmModel).filter_by(name="Model 1873").count() == 1

    def test_a_catalog_larger_than_sqlites_variable_limit(self, clean_db, fake_site):
        """The keys are gathered back in one SELECT, and SQLite caps a
        statement at 999 bound variables. A first scan of a large shop carries
        more listings than that."""
        FakeScraper.payload = [
            listing(f"k{n}", title=f"Winchester Model 18{n:02d} Rifle", caliber=None)
            for n in range(scan_service._KEYS_PER_QUERY + 120)
        ]
        run_id = scan_service.run_scan(fake_site.id, trigger="test")
        assert clean_db.get(ScanRun, run_id).status is ScanStatus.SUCCESS
        assert clean_db.query(FirearmModel).count() > 0

    def test_nothing_proposed_decides_anything(self, clean_db, fake_site):
        """A pending row is inert, which is what makes proposing from a guess
        safe. The listing must not take a kind or a caliber from one."""
        FakeScraper.payload = [
            listing("a", title="Winchester Model 1873 Lever Action Rifle", caliber=None)
        ]
        scan_service.run_scan(fake_site.id, trigger="test")
        item = clean_db.execute(select(Item).where(Item.external_key == "a")).scalar_one()
        assert item.firearm_model_id is None


class TestTheWriteLockIsNotHeldAcrossTheNetwork:
    """Why a scan must commit on a clock, not only on a count.

    SQLite has one writer. A scan takes the write lock the moment it saves a
    listing and holds it until it commits, so batching by count alone means
    holding it for however long the vendor takes to hand over the next
    twenty-five listings. Against a shop that wants twenty seconds between
    requests that is eight minutes, and every write the web application
    attempts in that window waits out its busy timeout and fails — signing in
    updates a last-seen timestamp, so signing in returned a 500.
    """

    @pytest.fixture
    def commits(self):
        """Count commits on any session, via SQLAlchemy's own event."""
        from sqlalchemy import event
        from sqlalchemy.orm import Session as SessionClass

        counted: list[int] = [0]

        def bump(_session):
            counted[0] += 1

        event.listen(SessionClass, "after_commit", bump)
        yield counted
        event.remove(SessionClass, "after_commit", bump)

    def clock(self, monkeypatch, step: float):
        """A monotonic clock that advances by `step` every time it is read."""
        now = [1000.0]

        def read():
            now[0] += step
            return now[0]

        monkeypatch.setattr("app.services.scan_service.time.monotonic", read)

    def test_a_slow_vendor_gets_a_commit_between_listings(
        self, clean_db, fake_site, monkeypatch, commits
    ):
        FakeScraper.payload = [listing(str(index)) for index in range(5)]
        self.clock(monkeypatch, step=5.0)

        scan_service.run_scan(fake_site.id, trigger="test")

        # Five listings, five commits at least: one each, rather than one for
        # the batch of twenty-five that never arrives.
        assert commits[0] >= 5

    def test_a_fast_vendor_still_gets_the_cheap_batch(
        self, clean_db, fake_site, monkeypatch, commits
    ):
        """The batching is what makes a fast scan cheap; it must survive.

        Compared against a slow run rather than against a fixed number: a scan
        commits a few times whatever happens — opening the run, finishing it —
        and what is under test is the commits the *listings* cause.
        """
        FakeScraper.payload = [listing(str(index)) for index in range(5)]

        self.clock(monkeypatch, step=0.0)
        scan_service.run_scan(fake_site.id, trigger="test")
        fast = commits[0]

        commits[0] = 0
        self.clock(monkeypatch, step=5.0)
        scan_service.run_scan(fake_site.id, trigger="test")
        slow = commits[0]

        assert fast < slow

    def test_and_everything_still_lands(self, clean_db, fake_site, monkeypatch):
        FakeScraper.payload = [listing(str(index)) for index in range(5)]
        self.clock(monkeypatch, step=5.0)

        scan_service.run_scan(fake_site.id, trigger="test")

        assert clean_db.execute(select(func.count(Item.id))).scalar_one() == 5


class TestTheWriteLockIsFreeBetweenListings:
    """The property the whole thing exists for, checked the way it is felt.

    SQLite has one writer. A scan that keeps a transaction open while it waits
    on the network holds the write lock for as long as the *vendor* takes, and
    every write the web application attempts meanwhile fails — signing in
    updates a last-seen timestamp, so signing in returned a 500.

    Checked from a separate connection, because that is what the web
    application is. An earlier fix committed "every N listings, or every N
    seconds checked when a listing arrives", passed its own tests, and failed
    this one: ten listings arrive in milliseconds, sit below the batch size,
    and the lock is then held across the twenty-second fetch of the next page
    — with the clock never checked, because checking it happens when a listing
    arrives.
    """

    def another_connection(self):
        """A connection like the web application's: separate, and impatient."""
        import sqlite3

        from app.config import get_config

        connection = sqlite3.connect(str(get_config().database_path), timeout=0.5)
        connection.execute("PRAGMA busy_timeout=500")
        return connection

    def can_write(self) -> bool:
        import sqlite3

        connection = self.another_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        except sqlite3.OperationalError:
            return False
        else:
            return True
        finally:
            connection.close()

    def test_another_connection_can_write_between_listings(self, clean_db, fake_site):
        free: list[bool] = []
        FakeScraper.between_items = lambda _index: free.append(self.can_write())
        FakeScraper.payload = [listing(str(index)) for index in range(4)]

        scan_service.run_scan(fake_site.id, trigger="test")

        assert free == [True, True, True, True]

    def test_and_the_work_is_visible_there_too(self, clean_db, fake_site):
        """Not merely unlocked but committed, so an interrupted scan keeps what
        it had reached."""
        counts: list[int] = []

        def count(_index):
            connection = self.another_connection()
            try:
                counts.append(connection.execute("SELECT count(*) FROM items").fetchone()[0])
            finally:
                connection.close()

        FakeScraper.between_items = count
        FakeScraper.payload = [listing(str(index)) for index in range(4)]

        scan_service.run_scan(fake_site.id, trigger="test")

        assert counts == [1, 2, 3, 4]


class TestPhotoDownloadsDoNotHoldTheLockEither:
    """The second loop with the same bug, found after the first was fixed.

    Each iteration downloads an image over the network, and it committed every
    fifty — so the write lock was held across up to fifty downloads. It runs at
    the *end* of a scan, which is where a person trying to sign in would meet
    it.
    """

    @pytest.fixture
    def storing_images(self, app_config, monkeypatch, tmp_path):
        config = dataclasses.replace(
            app_config,
            images_path=tmp_path / "images",
            scraping=dataclasses.replace(app_config.scraping, download_images=True),
        )
        config.images_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("app.services.scan_service.get_config", lambda: config)
        return config

    @pytest.fixture
    def commits(self):
        from sqlalchemy import event
        from sqlalchemy.orm import Session as SessionClass

        counted = [0]

        def bump(_session):
            counted[0] += 1

        event.listen(SessionClass, "after_commit", bump)
        yield counted
        event.remove(SessionClass, "after_commit", bump)

    def test_a_slow_image_host_gets_a_commit_between_photos(
        self, clean_db, fake_site, monkeypatch, storing_images, commits
    ):
        monkeypatch.setattr(
            "app.services.image_store.ImageStore.fetch",
            lambda *_args, **_kwargs: FetchResult(
                StoredImage(
                    filename="s/a.jpg",
                    thumb_filename="s/a_t.jpg",
                    content_type="image/jpeg",
                    bytes=10,
                    thumb_bytes=5,
                    width=10,
                    height=10,
                ),
                None,
            ),
        )
        FakeScraper.payload = [
            listing("a", image_urls=[f"https://fake.test/{n}.jpg" for n in range(6)])
        ]
        now = [1000.0]

        def slow():
            now[0] += 5.0
            return now[0]

        monkeypatch.setattr("app.services.scan_service.time.monotonic", slow)

        scan_service.run_scan(fake_site.id, trigger="test")

        # Six photos, and the loop used to commit once for all of them.
        assert commits[0] >= 6


class TestOnlyOneProcessScansASite:
    """A scan claimed its site in a process-local dictionary.

    So the CLI and the web application could not see each other's runs. Both
    scanned Collectors Firearms at once, at twice the request rate their
    robots.txt asks for, and the vendor answered with 429s. Worse, each
    process's stale-run reaper marked the other's *live* scan as failed,
    because a RUNNING row it did not own looked orphaned.

    The database is the only thing the two processes share, so the claim lives
    there.
    """

    def running_row(self, session, site, *, pid, host=None, minutes_ago=0):
        import socket

        run = ScanRun(
            site_id=site.id,
            trigger="manual",
            status=ScanStatus.RUNNING,
            started_at=utcnow() - timedelta(minutes=minutes_ago),
            owner_host=host if host is not None else socket.gethostname(),
            owner_pid=pid,
        )
        session.add(run)
        session.commit()
        return run

    def test_a_live_scan_in_another_process_blocks_a_second(self, clean_db, fake_site):
        import os

        self.running_row(clean_db, fake_site, pid=os.getpid())
        FakeScraper.payload = [listing("a")]

        with pytest.raises(scan_service.ScanBusy, match="already running"):
            scan_service.run_scan(fake_site.id, trigger="test")

    def test_and_says_which_process(self, clean_db, fake_site):
        import os

        self.running_row(clean_db, fake_site, pid=os.getpid())
        with pytest.raises(scan_service.ScanBusy, match=str(os.getpid())):
            scan_service.run_scan(fake_site.id, trigger="test")

    def test_a_row_whose_process_is_gone_does_not_block(self, clean_db, fake_site):
        """A crash should not lock a site out until its timeout."""
        stale = self.running_row(clean_db, fake_site, pid=999_999)
        FakeScraper.payload = [listing("a")]

        scan_service.run_scan(fake_site.id, trigger="test")

        clean_db.expire_all()
        assert clean_db.get(ScanRun, stale.id).status == ScanStatus.FAILED

    def test_nor_does_one_from_before_this_column_existed(self, clean_db, fake_site):
        """Rows written by an older version have no owner recorded."""
        self.running_row(clean_db, fake_site, pid=None, host=None)
        FakeScraper.payload = [listing("a")]
        scan_service.run_scan(fake_site.id, trigger="test")

    def test_another_machine_is_left_to_the_timeout(self, clean_db, fake_site):
        """A pid means nothing on somebody else's host, so it is not evidence
        either way — but a recent run there is still a claim."""
        self.running_row(clean_db, fake_site, pid=1, host="some-other-host")
        FakeScraper.payload = [listing("a")]

        scan_service.run_scan(fake_site.id, trigger="test")

    def test_the_new_run_records_who_owns_it(self, clean_db, fake_site):
        import os
        import socket

        FakeScraper.payload = [listing("a")]
        run_id = scan_service.run_scan(fake_site.id, trigger="test")

        run = clean_db.get(ScanRun, run_id)
        assert run.owner_pid == os.getpid()
        assert run.owner_host == socket.gethostname()

    def test_the_reaper_leaves_another_process_s_live_scan_alone(self, clean_db, fake_site):
        import os

        live = self.running_row(clean_db, fake_site, pid=os.getpid())

        assert scan_service.reap_stale_runs(clean_db) == 0
        clean_db.expire_all()
        assert clean_db.get(ScanRun, live.id).status == ScanStatus.RUNNING

    def test_but_still_reaps_one_that_has_timed_out(self, clean_db, fake_site):
        import os

        old = self.running_row(clean_db, fake_site, pid=os.getpid(), minutes_ago=600)

        assert scan_service.reap_stale_runs(clean_db) == 1
        clean_db.expire_all()
        assert clean_db.get(ScanRun, old.id).status == ScanStatus.FAILED
