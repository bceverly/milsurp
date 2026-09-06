"""Email digest preference endpoints, plus the admin email views."""

from __future__ import annotations

import pytest

from app.models import EmailLog, EmailStatus, Site
from app.scrapers import available_slugs


class TestReading:
    def test_defaults_are_created_on_first_read(self, client, admin_headers):
        body = client.get("/api/preferences/email", headers=admin_headers).json()
        assert body["enabled"] is False
        assert body["frequency_hours"] == 24
        assert body["new_items_per_site_limit"] == 10
        # An empty selection means "every enabled site".
        assert body["site_ids"] == []

    def test_requires_authentication(self, client):
        assert client.get("/api/preferences/email").status_code == 401

    def test_normal_users_have_their_own(self, client, normal_user):
        response = client.get("/api/preferences/email", headers=normal_user["headers"])
        assert response.status_code == 200


class TestUpdating:
    def test_round_trip(self, client, admin_headers):
        payload = {
            "enabled": True,
            "frequency_hours": 12,
            "include_new_items": True,
            "new_items_per_site_limit": 5,
            "include_price_drops": True,
            "price_drops_per_site_limit": 3,
            "minimum_price_drop": 25.0,
            "skip_when_empty": False,
            "display_timezone": "America/New_York",
        }
        saved = client.put("/api/preferences/email", json=payload, headers=admin_headers).json()
        for key, value in payload.items():
            assert saved[key] == value

        # And it persists.
        reread = client.get("/api/preferences/email", headers=admin_headers).json()
        assert reread["frequency_hours"] == 12

    def test_enabling_sets_a_send_time(self, client, admin_headers):
        body = client.put(
            "/api/preferences/email", json={"enabled": True}, headers=admin_headers
        ).json()
        assert body["next_send_at"] is not None

    def test_disabling_clears_the_send_time(self, client, admin_headers):
        client.put("/api/preferences/email", json={"enabled": True}, headers=admin_headers)
        body = client.put(
            "/api/preferences/email", json={"enabled": False}, headers=admin_headers
        ).json()
        assert body["next_send_at"] is None

    def test_site_selection_persists(self, client, admin_headers, seeded):
        site_ids = [s.id for s in seeded.query(Site).all()]
        saved = client.put(
            "/api/preferences/email", json={"site_ids": site_ids[:1]}, headers=admin_headers
        ).json()
        assert saved["site_ids"] == site_ids[:1]
        assert (
            client.get("/api/preferences/email", headers=admin_headers).json()["site_ids"]
            == site_ids[:1]
        )

    def test_empty_selection_means_all_sites(self, client, admin_headers, seeded):
        site_ids = [s.id for s in seeded.query(Site).all()]
        client.put("/api/preferences/email", json={"site_ids": site_ids}, headers=admin_headers)
        cleared = client.put(
            "/api/preferences/email", json={"site_ids": []}, headers=admin_headers
        ).json()
        assert cleared["site_ids"] == []

    def test_duplicate_site_ids_are_collapsed(self, client, admin_headers, seeded):
        site = seeded.query(Site).first()
        saved = client.put(
            "/api/preferences/email",
            json={"site_ids": [site.id, site.id, site.id]},
            headers=admin_headers,
        ).json()
        assert saved["site_ids"] == [site.id]

    def test_unknown_site_rejected(self, client, admin_headers):
        response = client.put(
            "/api/preferences/email", json={"site_ids": [99999]}, headers=admin_headers
        )
        assert response.status_code == 400
        assert "99999" in response.json()["detail"]

    def test_unknown_timezone_rejected(self, client, admin_headers):
        response = client.put(
            "/api/preferences/email",
            json={"display_timezone": "Mars/Olympus"},
            headers=admin_headers,
        )
        assert response.status_code == 400

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("frequency_hours", 0),
            ("frequency_hours", 99999),
            ("new_items_per_site_limit", 0),
            ("new_items_per_site_limit", 101),
            ("price_drops_per_site_limit", 0),
            ("minimum_price_drop", -5),
        ],
    )
    def test_out_of_range_values_rejected(self, client, admin_headers, field, value):
        response = client.put("/api/preferences/email", json={field: value}, headers=admin_headers)
        assert response.status_code == 422

    def test_partial_updates_leave_other_fields_alone(self, client, admin_headers):
        client.put(
            "/api/preferences/email",
            json={"frequency_hours": 6, "new_items_per_site_limit": 15},
            headers=admin_headers,
        )
        body = client.put(
            "/api/preferences/email", json={"frequency_hours": 48}, headers=admin_headers
        ).json()
        assert body["frequency_hours"] == 48
        assert body["new_items_per_site_limit"] == 15

    def test_users_cannot_see_each_others_preferences(self, client, admin_headers, normal_user):
        client.put("/api/preferences/email", json={"frequency_hours": 6}, headers=admin_headers)
        theirs = client.get("/api/preferences/email", headers=normal_user["headers"]).json()
        assert theirs["frequency_hours"] == 24  # still the default


class TestTestDigest:
    def test_refused_when_email_is_disabled(self, client, admin_headers):
        """The test config has email off, which is the interesting case."""
        response = client.post("/api/preferences/email/test", headers=admin_headers)
        assert response.status_code == 409
        assert "disabled" in response.json()["detail"]


class TestHistory:
    def test_own_history(self, client, admin_headers, seeded):
        me = client.get("/api/auth/me", headers=admin_headers).json()
        seeded.add(
            EmailLog(
                user_id=me["id"],
                status=EmailStatus.SENT,
                subject="Digest",
                new_item_count=3,
                price_drop_count=1,
            )
        )
        seeded.commit()
        body = client.get("/api/preferences/email/history", headers=admin_headers).json()
        assert len(body) == 1
        assert body[0]["status"] == "sent"
        assert body[0]["new_item_count"] == 3

    def test_history_is_per_user(self, client, admin_headers, normal_user, seeded):
        me = client.get("/api/auth/me", headers=admin_headers).json()
        seeded.add(EmailLog(user_id=me["id"], status=EmailStatus.SENT, subject="Mine"))
        seeded.commit()
        theirs = client.get("/api/preferences/email/history", headers=normal_user["headers"]).json()
        assert theirs == []


class TestAdminViews:
    def test_admin_sees_every_user(self, client, admin_headers, normal_user, seeded):
        seeded.add(
            EmailLog(
                user_id=normal_user["user"]["id"],
                status=EmailStatus.FAILED,
                error_message="smtp down",
            )
        )
        seeded.commit()
        body = client.get("/api/admin/email/history", headers=admin_headers).json()
        assert len(body) == 1
        # The admin view attributes each row to its user.
        assert body[0]["username"] == "viewer"
        assert body[0]["status"] == "failed"

    def test_normal_user_forbidden(self, client, normal_user):
        response = client.get("/api/admin/email/history", headers=normal_user["headers"])
        assert response.status_code == 403

    def test_smtp_test_reports_the_failure(self, client, admin_headers):
        response = client.post("/api/admin/email/test-connection", headers=admin_headers)
        assert response.status_code == 502
        assert "disabled" in response.json()["detail"]

    def test_smtp_test_forbidden_for_normal_users(self, client, normal_user):
        response = client.post("/api/admin/email/test-connection", headers=normal_user["headers"])
        assert response.status_code == 403


class TestPolicy:
    def test_reports_the_configured_minimum(self, client, admin_headers):
        body = client.get("/api/policy", headers=admin_headers).json()
        assert body["password_min_length"] == 12

    def test_available_to_normal_users(self, client, normal_user):
        """The change-password form needs it, and that is not admin-only."""
        response = client.get("/api/policy", headers=normal_user["headers"])
        assert response.status_code == 200

    def test_requires_authentication(self, client):
        assert client.get("/api/policy").status_code == 401

    def test_reports_the_derived_rules(self, client, admin_headers):
        """The text the UI shows comes from the server, so it cannot drift."""
        body = client.get("/api/policy", headers=admin_headers).json()
        assert body["password_requirements"][0] == "at least 12 characters"
        # The test config leaves the class toggles off.
        assert body["password_require_uppercase"] is False
        assert body["password_require_special"] is False


class TestSystemStatus:
    def test_reports_counts_and_paths(self, client, admin_headers):
        body = client.get("/api/admin/status", headers=admin_headers).json()
        assert body["mode"] == "dev"
        # Derived from the registry, not a literal: every vendor added to
        # SCRAPER_CLASSES seeds a site row, and hard-coding the number here
        # made adding one break two unrelated API tests.
        assert body["counts"]["sites"] == len(available_slugs())
        assert body["counts"]["users"] >= 1
        assert body["database_path"].endswith(".db")
        assert body["email_enabled"] is False
        assert "running" in body["scheduler"]

    def test_health_reports_utc(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["server_time"].endswith("Z")
