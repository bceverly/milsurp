"""The scan engine: upserts, price history, de-listing and run bookkeeping.

Driven by a fake scraper registered into the registry, so the whole reconcile
path runs without touching a vendor site or a browser.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Item, ItemPhoto, PriceHistory, ScanRun, ScanStatus, Site
from app.scrapers import ScrapedItem, ScrapeError, SiteScraper
from app.services import scan_service


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

    def scrape(self, ctx):
        if self.raise_error:
            raise ScrapeError(self.raise_error)
        if self.warn_with:
            ctx.warn(self.warn_with)
        ctx.log(f"Returning {len(self.payload)} listing(s).")
        return list(self.payload)


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
    clean_db.add(site)
    clean_db.commit()
    yield site
    FakeScraper.payload = []
    FakeScraper.raise_error = None
    FakeScraper.warn_with = None


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
