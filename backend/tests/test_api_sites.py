"""Site administration and scan-history endpoints."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Item, ScanRun, ScanStatus, Site, utcnow


@pytest.fixture
def site(seeded):
    return seeded.query(Site).order_by(Site.id).first()


class TestListing:
    def test_any_signed_in_user_can_read(self, client, normal_user):
        response = client.get("/api/sites", headers=normal_user["headers"])
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_includes_rollups(self, client, admin_headers, seeded, site):
        seeded.add(
            Item(
                site_id=site.id,
                external_key="k",
                url="https://example.test/k",
                title="Rifle",
                is_active=True,
                first_seen_at=utcnow(),
                last_seen_at=utcnow(),
            )
        )
        seeded.commit()
        entry = next(
            s for s in client.get("/api/sites", headers=admin_headers).json() if s["id"] == site.id
        )
        assert entry["item_count"] == 1
        assert entry["active_item_count"] == 1
        assert entry["is_scanning"] is False

    def test_includes_the_last_run(self, client, admin_headers, seeded, site):
        seeded.add(
            ScanRun(site_id=site.id, status=ScanStatus.SUCCESS, items_found=7, finished_at=utcnow())
        )
        seeded.commit()
        entry = next(
            s for s in client.get("/api/sites", headers=admin_headers).json() if s["id"] == site.id
        )
        assert entry["last_run"]["status"] == "success"
        assert entry["last_run"]["items_found"] == 7

    def test_single_site(self, client, admin_headers, site):
        body = client.get(f"/api/sites/{site.id}", headers=admin_headers).json()
        assert body["slug"] == site.slug

    def test_missing_site(self, client, admin_headers):
        assert client.get("/api/sites/99999", headers=admin_headers).status_code == 404


class TestUpdating:
    def test_disable_clears_the_schedule(self, client, admin_headers, site):
        body = client.patch(
            f"/api/sites/{site.id}", json={"enabled": False}, headers=admin_headers
        ).json()
        assert body["enabled"] is False
        # A disabled site must not remain queued.
        assert body["next_scan_at"] is None

    def test_enable_schedules_immediately(self, client, admin_headers, site):
        """Re-enabling should not wait out an interval that elapsed while off."""
        client.patch(f"/api/sites/{site.id}", json={"enabled": False}, headers=admin_headers)
        body = client.patch(
            f"/api/sites/{site.id}", json={"enabled": True}, headers=admin_headers
        ).json()
        assert body["enabled"] is True
        assert body["next_scan_at"] is not None

    def test_interval_change_rebases_the_schedule(self, client, admin_headers, seeded, site):
        site.last_scan_at = utcnow() - timedelta(hours=10)
        seeded.commit()
        body = client.patch(
            f"/api/sites/{site.id}",
            json={"scan_interval_minutes": 180},
            headers=admin_headers,
        ).json()
        assert body["scan_interval_minutes"] == 180
        assert body["next_scan_at"] is not None

    @pytest.mark.parametrize("minutes", [0, 1, 4, 50000])
    def test_out_of_range_intervals_rejected(self, client, admin_headers, site, minutes):
        response = client.patch(
            f"/api/sites/{site.id}",
            json={"scan_interval_minutes": minutes},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_rename(self, client, admin_headers, site):
        body = client.patch(
            f"/api/sites/{site.id}", json={"name": "Renamed Vendor"}, headers=admin_headers
        ).json()
        assert body["name"] == "Renamed Vendor"

    def test_normal_user_forbidden(self, client, normal_user, site):
        response = client.patch(
            f"/api/sites/{site.id}", json={"enabled": False}, headers=normal_user["headers"]
        )
        assert response.status_code == 403

    def test_missing_site(self, client, admin_headers):
        assert (
            client.patch(
                "/api/sites/99999", json={"enabled": True}, headers=admin_headers
            ).status_code
            == 404
        )


class TestScanControl:
    def test_unavailable_site_cannot_be_scanned(self, client, admin_headers, seeded, site):
        site.is_available = False
        seeded.commit()
        response = client.post(f"/api/sites/{site.id}/scan", headers=admin_headers)
        assert response.status_code == 409
        assert "No scraper" in response.json()["detail"]

    def test_busy_site_is_rejected(self, client, admin_headers, site, monkeypatch):
        from app.services import scan_service

        monkeypatch.setitem(scan_service._running, site.id, 1)
        try:
            response = client.post(f"/api/sites/{site.id}/scan", headers=admin_headers)
            assert response.status_code == 409
        finally:
            scan_service._running.pop(site.id, None)

    def test_cancel_without_a_running_scan(self, client, admin_headers, site):
        response = client.post(f"/api/sites/{site.id}/scan/cancel", headers=admin_headers)
        assert response.status_code == 409

    def test_cancel_signals_a_running_scan(self, client, admin_headers, site, monkeypatch):
        import threading

        from app.services import scan_service

        event = threading.Event()
        monkeypatch.setitem(scan_service._cancel_flags, site.id, event)
        try:
            response = client.post(f"/api/sites/{site.id}/scan/cancel", headers=admin_headers)
            assert response.status_code == 202
            assert event.is_set()
        finally:
            scan_service._cancel_flags.pop(site.id, None)

    def test_normal_user_cannot_start_or_cancel(self, client, normal_user, site):
        headers = normal_user["headers"]
        assert client.post(f"/api/sites/{site.id}/scan", headers=headers).status_code == 403
        assert client.post(f"/api/sites/{site.id}/scan/cancel", headers=headers).status_code == 403


class TestScanHistory:
    @pytest.fixture
    def runs(self, seeded, site):
        created = []
        for index in range(5):
            run = ScanRun(
                site_id=site.id,
                status=ScanStatus.SUCCESS if index % 2 == 0 else ScanStatus.FAILED,
                started_at=utcnow() - timedelta(hours=index),
                finished_at=utcnow() - timedelta(hours=index) + timedelta(minutes=2),
                items_found=index * 10,
                trigger="scheduled",
            )
            seeded.add(run)
            created.append(run)
        seeded.commit()
        return created

    def test_newest_first(self, client, admin_headers, site, runs):
        body = client.get(f"/api/sites/{site.id}/scans", headers=admin_headers).json()
        assert len(body) == 5
        stamps = [entry["started_at"] for entry in body]
        assert stamps == sorted(stamps, reverse=True)

    def test_pagination(self, client, admin_headers, site, runs):
        first = client.get(f"/api/sites/{site.id}/scans?limit=2", headers=admin_headers).json()
        assert len(first) == 2
        second = client.get(
            f"/api/sites/{site.id}/scans?limit=2&offset=2", headers=admin_headers
        ).json()
        assert {r["id"] for r in first} & {r["id"] for r in second} == set()

    def test_missing_site(self, client, admin_headers):
        assert client.get("/api/sites/99999/scans", headers=admin_headers).status_code == 404

    def test_readable_by_a_normal_user(self, client, normal_user, site, runs):
        response = client.get(f"/api/sites/{site.id}/scans", headers=normal_user["headers"])
        assert response.status_code == 200


class TestScansEndpoints:
    @pytest.fixture
    def runs(self, seeded, site):
        for index in range(3):
            seeded.add(
                ScanRun(
                    site_id=site.id,
                    status=ScanStatus.SUCCESS if index else ScanStatus.FAILED,
                    started_at=utcnow() - timedelta(minutes=index),
                    log=f"line {index}",
                )
            )
        seeded.commit()
        return seeded.query(ScanRun).all()

    def test_cross_site_listing(self, client, admin_headers, runs):
        assert len(client.get("/api/scans", headers=admin_headers).json()) == 3

    def test_filter_by_site(self, client, admin_headers, runs, site):
        body = client.get(f"/api/scans?site_id={site.id}", headers=admin_headers).json()
        assert all(entry["site_id"] == site.id for entry in body)

    def test_filter_by_status(self, client, admin_headers, runs):
        body = client.get("/api/scans?status=failed", headers=admin_headers).json()
        assert len(body) == 1
        assert body[0]["status"] == "failed"

    def test_unknown_status_rejected(self, client, admin_headers, runs):
        assert client.get("/api/scans?status=sideways", headers=admin_headers).status_code == 400

    def test_detail_includes_the_log_and_site_name(self, client, admin_headers, runs, site):
        run_id = runs[0].id
        body = client.get(f"/api/scans/{run_id}", headers=admin_headers).json()
        assert body["log"] is not None
        assert body["site_name"] == site.name

    def test_missing_run(self, client, admin_headers):
        assert client.get("/api/scans/99999", headers=admin_headers).status_code == 404
