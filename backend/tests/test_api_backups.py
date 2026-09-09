"""The backup page's API: the schedule, and the button.

Administrator-only, because it decides what the machine writes to disk and how
much of it accumulates.
"""

from __future__ import annotations

import pytest

from app.services import backup


@pytest.fixture(autouse=True)
def isolated(client, app_config, clean_db, tmp_path):
    """A backup directory and a settings row of this test's own.

    Both are otherwise shared: the config is session-scoped, so every test in
    this file would write snapshots into the same directory and read each
    other's, and the settings row survives between them. `Config` is frozen, so
    the directory is changed by replacing the dependency rather than the
    object.
    """
    import dataclasses

    from app.deps import get_config

    directory = tmp_path / "backups"
    isolated_config = dataclasses.replace(
        app_config, backups=dataclasses.replace(app_config.backups, directory=directory)
    )
    client.app.dependency_overrides[get_config] = lambda: isolated_config

    row = backup.settings(clean_db)
    row.enabled = False
    row.interval_hours = 24
    row.keep = 10
    row.last_run_at = row.last_status = row.last_error = row.last_bytes = None
    clean_db.commit()

    yield isolated_config
    client.app.dependency_overrides.pop(get_config, None)


@pytest.fixture
def state(client, admin_headers):
    def read():
        response = client.get("/api/admin/backups", headers=admin_headers)
        assert response.status_code == 200
        return response.json()

    return read


class TestReading:
    def test_it_reports_the_schedule_and_what_is_on_disk(self, state):
        body = state()
        assert set(body) >= {
            "settings",
            "directory",
            "engine",
            "restore_hint",
            "snapshots",
            "total_bytes",
        }
        assert body["settings"]["interval_hours"] == 24
        assert body["snapshots"] == []

    def test_the_choices_come_from_the_server(self, state):
        """So the page's dropdown and the endpoint's validation cannot disagree
        about what is allowed."""
        body = state()
        assert body["interval_choices"] == [6, 12, 24, 48, 72, 168]
        assert body["keep_choices"] == [3, 5, 10, 20, 30]

    def test_it_says_how_to_restore_one(self, state):
        """A .dump needs pg_restore and a .db opens with sqlite3; finding that
        out at the moment you need a restore is the wrong time."""
        assert "sqlite3" in state()["restore_hint"] or "move the file" in state()["restore_hint"]

    def test_a_normal_user_cannot_see_it(self, client, normal_user):
        response = client.get("/api/admin/backups", headers=normal_user["headers"])
        assert response.status_code == 403

    def test_nor_can_a_stranger(self, client):
        assert client.get("/api/admin/backups").status_code == 401


class TestChangingTheSchedule:
    def test_each_setting_can_be_changed_on_its_own(self, client, admin_headers, state):
        client.patch("/api/admin/backups", headers=admin_headers, json={"enabled": True})
        client.patch("/api/admin/backups", headers=admin_headers, json={"interval_hours": 12})
        client.patch("/api/admin/backups", headers=admin_headers, json={"keep": 5})

        settings = state()["settings"]
        assert (settings["enabled"], settings["interval_hours"], settings["keep"]) == (True, 12, 5)

    def test_an_interval_nobody_offers_is_refused(self, client, admin_headers):
        """A free-text number invites "1", which on a large database is a
        snapshot still running when the next one starts."""
        response = client.patch(
            "/api/admin/backups", headers=admin_headers, json={"interval_hours": 1}
        )
        assert response.status_code == 400
        assert "interval_hours" in response.json()["detail"]

    def test_so_is_a_retention_nobody_offers(self, client, admin_headers):
        assert (
            client.patch(
                "/api/admin/backups", headers=admin_headers, json={"keep": 999}
            ).status_code
            == 400
        )

    def test_a_refused_change_leaves_the_setting_alone(self, client, admin_headers, state):
        client.patch("/api/admin/backups", headers=admin_headers, json={"interval_hours": 1})
        assert state()["settings"]["interval_hours"] == 24

    def test_a_normal_user_cannot_change_it(self, client, normal_user):
        response = client.patch(
            "/api/admin/backups", headers=normal_user["headers"], json={"enabled": True}
        )
        assert response.status_code == 403


class TestTheButton:
    def test_it_takes_one_now(self, client, admin_headers, state):
        response = client.post("/api/admin/backups/run", headers=admin_headers)
        assert response.status_code == 200

        body = response.json()
        assert len(body["snapshots"]) == 1
        assert body["snapshots"][0]["bytes"] > 0
        assert body["settings"]["last_status"] == "SUCCESS"
        assert state()["snapshots"] == body["snapshots"]

    def test_it_works_with_the_schedule_switched_off(self, client, admin_headers, state):
        """Which is the case it is most useful in: about to do something risky,
        backups not otherwise on."""
        assert state()["settings"]["enabled"] is False
        assert client.post("/api/admin/backups/run", headers=admin_headers).status_code == 200
        assert len(state()["snapshots"]) == 1

    def test_a_failure_says_why_and_is_remembered(self, client, admin_headers, state, monkeypatch):
        def explode(*_args, **_kwargs):
            raise RuntimeError("pg_dump is not on PATH")

        monkeypatch.setattr(backup, "take", explode)
        response = client.post("/api/admin/backups/run", headers=admin_headers)

        assert response.status_code == 500
        assert "pg_dump" in response.json()["detail"]
        # And on the page after a reload, not only in a response nobody kept.
        assert state()["settings"]["last_status"] == "FAILED"

    def test_a_normal_user_cannot_press_it(self, client, normal_user):
        response = client.post("/api/admin/backups/run", headers=normal_user["headers"])
        assert response.status_code == 403


class TestTimesReachTheBrowserUnambiguously:
    """Every datetime leaves this API with an explicit Z.

    Without it the browser's Date.parse reads a bare "2026-09-09T19:36:49" as
    *local* time, which on this machine is four hours out — on the very page
    whose job is to say when the last backup ran. The first version of this
    endpoint had exactly that bug, because BackupSettingsOut extended BaseModel
    rather than UTCModel.
    """

    def test_last_run_at_carries_its_timezone(self, client, admin_headers):
        client.post("/api/admin/backups/run", headers=admin_headers)
        body = client.get("/api/admin/backups", headers=admin_headers).json()

        stamp = body["settings"]["last_run_at"]
        assert stamp is not None
        assert stamp.endswith(("Z", "+00:00")), stamp

    def test_and_so_does_every_snapshot(self, client, admin_headers):
        client.post("/api/admin/backups/run", headers=admin_headers)
        body = client.get("/api/admin/backups", headers=admin_headers).json()

        assert body["snapshots"]
        for snapshot in body["snapshots"]:
            assert snapshot["taken_at"].endswith(("Z", "+00:00")), snapshot
