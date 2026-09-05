"""The photo store: SSRF guard, path safety, thumbnails and housekeeping."""

from __future__ import annotations

import io

import pytest
import requests
from PIL import Image

from app.services.image_store import (
    MAX_IMAGE_BYTES,
    THUMBNAIL_MAX_EDGE,
    ImageStore,
    ImageStoreError,
    _is_public_url,
)


def make_png(width: int, height: int, mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), (120, 140, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeResponse:
    """Enough of requests.Response for ImageStore.download."""

    def __init__(self, content: bytes, content_type="image/png", status=200, headers=None):
        self.content = content
        self.status_code = status
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
        if headers:
            self.headers.update(headers)
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response=None, raises=None):
        self.response = response
        self.raises = raises
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if self.raises:
            raise self.raises
        return self.response


@pytest.fixture
def store(app_config, tmp_path):
    import dataclasses

    config = dataclasses.replace(app_config)
    object.__setattr__(config, "images_path", tmp_path / "images")
    config.images_path.mkdir(parents=True, exist_ok=True)
    return ImageStore(config)


class TestSsrfGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/photo.jpg",
            "http://localhost/photo.jpg",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://10.0.0.5/photo.jpg",
            "http://192.168.1.10/photo.jpg",
            "http://[::1]/photo.jpg",
        ],
    )
    def test_private_and_loopback_addresses_rejected(self, url):
        """A hostile listing must not turn the scraper into an internal probe."""
        assert not _is_public_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/photo.jpg",
            "gopher://example.com/",
            "not-a-url",
            "",
        ],
    )
    def test_non_http_schemes_rejected(self, url):
        assert not _is_public_url(url)

    def test_unresolvable_host_rejected(self):
        assert not _is_public_url("http://this-host-does-not-exist.invalid/x.jpg")

    def test_download_refuses_a_private_url(self, store):
        session = FakeSession(FakeResponse(make_png(10, 10)))
        assert store.download(session, "site", "http://127.0.0.1/x.png") is None
        # Rejected before any request was made.
        assert session.requested == []


class TestPathSafety:
    def test_traversal_is_refused(self, store):
        with pytest.raises(ImageStoreError):
            store.absolute_path("../../etc/passwd")

    def test_absolute_escape_is_refused(self, store):
        with pytest.raises(ImageStoreError):
            store.absolute_path("/etc/passwd")

    def test_normal_path_resolves_inside_the_root(self, store):
        resolved = store.absolute_path("site/ab/deadbeef.jpg")
        assert resolved.is_relative_to(store.root.resolve())

    def test_exists_is_false_for_a_bad_path(self, store):
        assert store.exists("../../etc/passwd") is False
        assert store.exists(None) is False


class TestDownload:
    def test_stores_the_file_and_a_thumbnail(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        session = FakeSession(FakeResponse(make_png(1600, 1200)))
        stored = store.download(session, "royal-tiger", "https://example.test/big.png")

        assert stored is not None
        assert store.exists(stored.filename)
        assert stored.width == 1600
        assert stored.height == 1200
        # A separate, smaller thumbnail was generated locally.
        assert stored.thumb_filename != stored.filename
        assert store.exists(stored.thumb_filename)
        assert stored.thumb_bytes < stored.bytes

        with Image.open(store.absolute_path(stored.thumb_filename)) as thumb:
            assert max(thumb.size) <= THUMBNAIL_MAX_EDGE

    def test_small_images_reuse_the_original(self, store, monkeypatch):
        """No point writing a second copy of an already-small picture."""
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        session = FakeSession(FakeResponse(make_png(200, 150)))
        stored = store.download(session, "site", "https://example.test/small.png")
        assert stored.thumb_filename == stored.filename

    def test_transparency_is_flattened(self, store, monkeypatch):
        """JPEG has no alpha channel; an RGBA source must not fail to save."""
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        session = FakeSession(FakeResponse(make_png(1200, 900, mode="RGBA")))
        stored = store.download(session, "site", "https://example.test/alpha.png")
        assert stored.thumb_filename is not None
        assert store.exists(stored.thumb_filename)

    def test_content_addressed_filenames_are_stable(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        url = "https://example.test/same.png"
        first = store.download(FakeSession(FakeResponse(make_png(300, 200))), "site", url)
        second = store.download(FakeSession(FakeResponse(make_png(300, 200))), "site", url)
        assert first.filename == second.filename

    def test_non_image_content_type_rejected(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        session = FakeSession(FakeResponse(b"<html>nope</html>", content_type="text/html"))
        assert store.download(session, "site", "https://example.test/page") is None

    def test_oversized_declared_length_rejected(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        response = FakeResponse(make_png(10, 10))
        response.headers["Content-Length"] = str(MAX_IMAGE_BYTES + 1)
        assert store.download(FakeSession(response), "site", "https://example.test/x.png") is None

    def test_network_failure_returns_none(self, store, monkeypatch):
        """A missing photo is never worth failing a scan over."""
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        session = FakeSession(raises=requests.ConnectionError("refused"))
        assert store.download(session, "site", "https://example.test/x.png") is None

    def test_http_error_returns_none(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        session = FakeSession(FakeResponse(b"", content_type="image/png", status=404))
        assert store.download(session, "site", "https://example.test/x.png") is None

    def test_corrupt_image_keeps_the_file_but_has_no_thumbnail(self, store, monkeypatch):
        """Pillow cannot decode it, but the bytes are already on disk."""
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        session = FakeSession(FakeResponse(b"not really a png", content_type="image/png"))
        stored = store.download(session, "site", "https://example.test/bad.png")
        assert stored is not None
        assert store.exists(stored.filename)
        assert stored.thumb_filename is None

    def test_no_partial_files_left_behind(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        store.download(
            FakeSession(FakeResponse(make_png(800, 600))), "site", "https://e.test/a.png"
        )
        assert list(store.root.rglob("*.part")) == []


class TestHousekeeping:
    def test_usage_bytes(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        assert store.usage_bytes() == 0
        store.download(FakeSession(FakeResponse(make_png(400, 300))), "s", "https://e.test/a.png")
        assert store.usage_bytes() > 0

    def test_prune_removes_unreferenced_files(self, store, monkeypatch):
        monkeypatch.setattr("app.services.image_store._is_public_url", lambda _url: True)
        keep = store.download(
            FakeSession(FakeResponse(make_png(400, 300))), "s", "https://e.test/keep.png"
        )
        store.download(
            FakeSession(FakeResponse(make_png(400, 300))), "s", "https://e.test/drop.png"
        )

        known = {keep.filename}
        if keep.thumb_filename:
            known.add(keep.thumb_filename)

        removed = store.prune_orphans(known)
        assert removed >= 1
        assert store.exists(keep.filename)

    def test_delete_is_safe_on_missing_and_bad_paths(self, store):
        store.delete(None)
        store.delete("site/does/not/exist.jpg")
        store.delete("../../etc/passwd")  # must not raise
