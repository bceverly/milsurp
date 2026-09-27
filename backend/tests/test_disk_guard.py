"""Photographs must never fill the disk the database writes to.

On 2026-09-27 they did: the production VM's root filesystem reached 100%,
PostgreSQL could not write a checkpoint, and it crash-looped until the disk
grew. Two guards came of it: photo downloads pause under a floor of free space,
and the canary warns well before the floor is reached.
"""

from __future__ import annotations

import dataclasses
from collections import namedtuple
from pathlib import Path

import pytest

from app.config import load_config
from app.services import canary, image_store
from app.services.image_store import GIB, ImageStore

Usage = namedtuple("Usage", "total used free")


@pytest.fixture
def store(app_config, tmp_path):
    """A store with the shipped 5 GB floor; the suite's own config turns it off."""
    config = dataclasses.replace(app_config)
    object.__setattr__(config, "images_path", tmp_path / "images")
    object.__setattr__(
        config, "scraping", dataclasses.replace(app_config.scraping, min_free_disk_gb=5.0)
    )
    config.images_path.mkdir(parents=True, exist_ok=True)
    return ImageStore(config)


def _free(monkeypatch, gigabytes: float) -> None:
    monkeypatch.setattr(image_store, "free_bytes", lambda _path: int(gigabytes * GIB))


class TestPhotoDownloadsPause:
    def test_under_the_floor_nothing_is_fetched(self, store, monkeypatch):
        _free(monkeypatch, 1.2)
        monkeypatch.setattr(image_store, "_check_url", lambda _url: image_store.UrlVerdict(True))
        asked: list[str] = []
        monkeypatch.setattr(
            store, "_get_photo", lambda _session, url: asked.append(url) or (None, "x", False)
        )

        result = store.fetch(None, "site", "https://example.test/a.jpg")

        assert asked == []
        assert result.image is None
        # Resting, so the batch stops and no photograph loses a retry.
        assert result.resting and not result.permanent
        assert "1.2 GB is free" in (result.reason or "")
        assert "min_free_disk_gb" in (result.reason or "")

    def test_above_it_the_fetch_goes_ahead(self, store, monkeypatch):
        _free(monkeypatch, 40)
        assert store.disk_too_full() is None

    def test_a_disk_that_will_not_say_is_not_full(self, store, monkeypatch):
        """An unreadable answer must not stop photographs forever."""
        monkeypatch.setattr(image_store, "free_bytes", lambda _path: None)
        assert store.disk_too_full() is None

    def test_zero_turns_the_guard_off(self, store, monkeypatch):
        _free(monkeypatch, 0.01)
        scraping = dataclasses.replace(store.config.scraping, min_free_disk_gb=0)
        object.__setattr__(store.config, "scraping", scraping)
        assert store.disk_too_full() is None

    def test_generated_images_are_held_back_too(self, store, monkeypatch):
        _free(monkeypatch, 1)
        assert store.store_bytes("hunters-lodge", "flyer#1", b"\x89PNG not really") is None


class TestTheSettings:
    def _load(self, tmp_path: Path, body: str):
        path = tmp_path / "config.yaml"
        path.write_text(body, encoding="utf-8")
        return load_config(path).scraping

    def test_the_floor_defaults_to_five_gigabytes(self, tmp_path):
        assert self._load(tmp_path, "scraping: {}\n").min_free_disk_gb == 5.0

    def test_and_can_be_set(self, tmp_path):
        assert self._load(tmp_path, "scraping:\n  min_free_disk_gb: 12\n").min_free_disk_gb == 12

    def test_the_photo_budget_is_read_at_last(self, tmp_path):
        """max_photo_downloads_per_scan was documented in the sample config
        and never read, so setting it did nothing."""
        body = "scraping:\n  max_photo_downloads_per_scan: 900\n"
        assert self._load(tmp_path, body).max_photo_downloads_per_scan == 900


class TestTheCanaryWarnsFirst:
    def _disk(self, free_gb: float, total_gb: float = 124, floor_gb: float = 5):
        return canary.DiskHealth(
            holds="photographs, database",
            path="/etc/milsurp/images",
            free=int(free_gb * GIB),
            total=int(total_gb * GIB),
            floor=int(floor_gb * GIB),
        )

    def test_plenty_of_room_is_quiet(self):
        assert not self._disk(60).low

    def test_under_a_tenth_of_the_disk_is_low(self):
        disk = self._disk(11)
        assert disk.low and not disk.paused
        assert "Photo downloads pause below 5 GB" in disk.headline

    def test_under_twice_the_floor_is_low_on_a_small_disk(self):
        """On a 40 GB disk a tenth is 4 GB, which would warn only after the
        5 GB floor had already stopped the photographs."""
        assert self._disk(9, total_gb=40).low

    def test_under_the_floor_says_downloads_have_stopped(self):
        disk = self._disk(3)
        assert disk.paused
        assert "paused until there is more room" in disk.headline

    def test_each_filesystem_is_reported_once_with_all_it_holds(
        self, app_config, monkeypatch, tmp_path
    ):
        images = tmp_path / "images"
        backups = tmp_path / "backups"
        images.mkdir()
        backups.mkdir()
        config = dataclasses.replace(app_config)
        object.__setattr__(config, "images_path", images)
        object.__setattr__(
            config, "backups", dataclasses.replace(app_config.backups, directory=backups)
        )
        monkeypatch.setattr(
            canary.shutil, "disk_usage", lambda _p: Usage(100 * GIB, 95 * GIB, 5 * GIB)
        )

        [disk] = canary.disk_health(config)

        assert disk.holds.startswith("photographs, backups")
        assert disk.low

    def test_the_report_leads_with_it(self):
        from cli import _canary_report

        text = _canary_report([], disks=[self._disk(3)])
        assert text.startswith("DISK: 3.0 GB free of 124 GB")
