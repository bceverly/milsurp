"""A shop's stock picture goes to the back of the gallery.

Madison Guns led 171 galleries with a red "STOP -- you must be 21+" sign (or its
"18+" twin), each at its own URL, at two sizes, and one copy differs from its
siblings by 14 bytes of re-encoding. So it is recognized by how it looks, and
moved last.
"""

from __future__ import annotations

import dataclasses
import io

import pytest
from PIL import Image, ImageDraw

from app.models import Item, ItemPhoto
from app.scrapers import get_scraper_class
from app.services import image_store, scan_service
from app.services.image_store import ImageStore, difference_hash, looks_like


def _picture(kind: str, quality: int = 90) -> bytes:
    image = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(image)
    if kind == "sign":
        draw.regular_polygon((150, 130, 110), 8, fill="red")
        draw.rectangle((20, 250, 280, 290), fill="black")
    elif kind == "rifle":
        draw.rectangle((10, 140, 290, 160), fill="saddlebrown")
        draw.rectangle((200, 120, 280, 175), fill="dimgray")
    else:
        draw.ellipse((60, 60, 240, 240), fill="navy")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)
    return out.getvalue()


@pytest.fixture
def store(app_config, tmp_path):
    config = dataclasses.replace(app_config)
    object.__setattr__(config, "images_path", tmp_path / "images")
    config.images_path.mkdir(parents=True, exist_ok=True)
    return ImageStore(config)


def _stored(store, name: str, data: bytes) -> str:
    path = store.root / name
    path.write_bytes(data)
    return name


class TestTheFingerprint:
    def test_the_same_picture_saved_twice_matches(self, tmp_path):
        first, second = tmp_path / "a.jpg", tmp_path / "b.jpg"
        first.write_bytes(_picture("sign", quality=90))
        second.write_bytes(_picture("sign", quality=70))
        assert first.read_bytes() != second.read_bytes()
        assert looks_like(difference_hash(second), difference_hash(first))

    def test_a_different_picture_does_not(self, tmp_path):
        sign, rifle = tmp_path / "s.jpg", tmp_path / "r.jpg"
        sign.write_bytes(_picture("sign"))
        rifle.write_bytes(_picture("rifle"))
        assert not looks_like(difference_hash(rifle), difference_hash(sign))

    def test_an_unreadable_file_is_nothing(self, tmp_path):
        broken = tmp_path / "broken.jpg"
        broken.write_bytes(b"not a picture")
        assert difference_hash(broken) is None


class TestTheGallery:
    def _item(self, store, kinds):
        item = Item(title="Used rifle")
        item.photos = [
            ItemPhoto(
                source_url=f"https://m.test/{index}.jpg",
                position=index,
                filename=_stored(store, f"{index}-{kind}.jpg", _picture(kind)),
            )
            for index, kind in enumerate(kinds)
        ]
        return item

    def _sign_is_stock(self, monkeypatch, store):
        sign = store.root / "reference.jpg"
        sign.write_bytes(_picture("sign"))
        fingerprint = difference_hash(sign)
        monkeypatch.setattr(scan_service, "_demoted_fingerprints", lambda _slug: [fingerprint])

    def order(self, item):
        return [photo.filename for photo in sorted(item.photos, key=lambda p: p.position)]

    def test_the_sign_goes_last_and_the_rest_move_up(self, store, monkeypatch):
        self._sign_is_stock(monkeypatch, store)
        item = self._item(store, ["sign", "rifle", "other"])

        assert scan_service._demote_placeholders(item, store, "madison-guns")
        assert self.order(item) == ["1-rifle.jpg", "2-other.jpg", "0-sign.jpg"]

    def test_already_last_is_left_alone(self, store, monkeypatch):
        self._sign_is_stock(monkeypatch, store)
        item = self._item(store, ["rifle", "sign"])
        assert not scan_service._demote_placeholders(item, store, "madison-guns")

    def test_a_listing_with_only_the_sign_keeps_it(self, store, monkeypatch):
        self._sign_is_stock(monkeypatch, store)
        item = self._item(store, ["sign"])
        assert not scan_service._demote_placeholders(item, store, "madison-guns")

    def test_a_photo_not_yet_downloaded_is_not_judged(self, store, monkeypatch):
        self._sign_is_stock(monkeypatch, store)
        item = self._item(store, ["rifle", "other"])
        item.photos.insert(0, ItemPhoto(source_url="https://m.test/new.jpg", position=-1))
        assert not scan_service._demote_placeholders(item, store, "madison-guns")

    def test_a_shop_with_nothing_to_demote_costs_nothing(self, store, monkeypatch):
        """No fingerprints, no file is opened."""
        opened: list[object] = []
        monkeypatch.setattr(scan_service, "difference_hash", opened.append)
        item = self._item(store, ["sign", "rifle"])
        assert not scan_service._demote_placeholders(item, store, "officer-store")
        assert opened == []


def test_madison_names_its_stop_sign():
    fingerprints = get_scraper_class("madison-guns").demoted_images
    assert fingerprints and all(len(value) == 16 and int(value, 16) for value in fingerprints)
    assert image_store.IMAGE_MATCH_DISTANCE < 16
