"""Loading an armory writes down every row it touches.

"Load shipped armory" used to write one line however much it added, and a
sync from a file wrote nothing at all -- so the log could not say what a
load had changed, and nothing it changed could be undone. Now every load
records one created, edited or deleted event per row, carrying what an edited
row held before, so each change reads like curation by hand and can be put
back from the log on its own. Applying the shipped file from the page shows
its plan first, and re-matches the listings its spellings touch.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func

from app.models import ArmoryStatus, AuditEvent, Caliber, FirearmModel, Item, Site
from app.services import armory

SHIPPED = """
calibers:
- name: 7.62x54R
  aliases:
  - 7.62x54mmR
  - 7.62 Russian
  status: approved
- name: .52 Caliber
  aliases:
  - '.52'
  status: approved
- name: '.52'
  status: merged
manufacturers:
- name: Tula
  country: Russia
  status: approved
models:
- name: Mosin-Nagant M91/30
  aliases:
  - M91/30
  - 91/30
  kind: rifle
  country: Russia
  calibers:
  - 7.62x54R
  manufacturers:
  - Tula
  status: approved
"""


@pytest.fixture
def shipped(tmp_path, monkeypatch):
    path = tmp_path / "armory.yaml"
    path.write_text(SHIPPED, encoding="utf-8")
    monkeypatch.setattr(armory, "SEED_FILE", path)
    return path


@pytest.fixture
def since(seeded):
    """Audit events persist across tests, so each test reads only its own."""
    return seeded.query(func.max(AuditEvent.id)).scalar() or 0


def _events(session, since, action=None):
    query = session.query(AuditEvent).filter(AuditEvent.id > since)
    if action:
        query = query.filter(AuditEvent.action == action)
    return query.order_by(AuditEvent.id).all()


def _clear_armory(session):
    for model in (FirearmModel, Caliber):
        for row in session.query(model).all():
            session.delete(row)
    session.commit()


class TestLoadingTheShippedArmory:
    def test_each_row_added_is_recorded_and_one_summary(
        self, client, admin_headers, seeded, shipped, since
    ):
        _clear_armory(seeded)
        body = client.post("/api/armory/seed", headers=admin_headers).json()
        assert body["changed"] >= 4
        created = _events(seeded, since, "armory.created")
        labels = {(event.target_type, event.target_label) for event in created}
        assert ("caliber", "7.62x54R") in labels
        assert ("model", "Mosin-Nagant M91/30") in labels
        assert all(event.detail.startswith("from the shipped armory") for event in created)
        assert all(event.actor_name for event in created)
        assert len(_events(seeded, since, "armory.seeded")) == 1


class TestApplyingTheShippedArmory:
    @pytest.fixture
    def behind(self, seeded, shipped):
        """A database that has the rows, but not the file's corrections."""
        _clear_armory(seeded)
        armory.apply_sync(seeded, shipped)
        seeded.commit()
        caliber = seeded.query(Caliber).filter_by(name="7.62x54R").one()
        caliber.aliases = "7.62x54mmR"  # lost "7.62 Russian"
        seeded.query(Caliber).filter_by(name=".52").one().status = ArmoryStatus.APPROVED
        seeded.commit()
        return caliber

    def test_the_plan_says_what_would_change_and_changes_nothing(
        self, client, admin_headers, seeded, behind, since
    ):
        plan = client.get("/api/armory/sync/plan", headers=admin_headers).json()
        changes = {change["name"]: change for change in plan["calibers"]}
        assert changes["7.62x54R"]["fields"] == ["aliases"]
        assert changes[".52"]["fields"] == ["status"]
        assert plan["updated"] == 2 and plan["added"] == 0
        seeded.refresh(behind)
        assert behind.aliases == "7.62x54mmR"
        assert _events(seeded, since) == []

    def test_applying_records_each_change_with_what_it_held(
        self, client, admin_headers, seeded, behind, since
    ):
        body = client.post("/api/armory/sync", headers=admin_headers).json()
        assert body["changed"] == 2
        edited = {e.target_label: e for e in _events(seeded, since, "armory.edited")}
        assert set(edited) == {"7.62x54R", ".52"}
        assert json.loads(edited["7.62x54R"].before_state)["aliases"] == "7.62x54mmR"
        assert edited[".52"].detail == "from the shipped armory: status"
        assert len(_events(seeded, since, "armory.synced")) == 1
        seeded.refresh(behind)
        assert "7.62 Russian" in behind.aliases

    def test_each_change_can_be_undone_from_the_log(
        self, client, admin_headers, seeded, behind, since
    ):
        client.post("/api/armory/sync", headers=admin_headers)
        event = next(
            e for e in _events(seeded, since, "armory.edited") if e.target_label == "7.62x54R"
        )
        assert (
            client.post(f"/api/armory/revert/{event.id}", headers=admin_headers).status_code == 200
        )
        seeded.expire_all()
        assert seeded.query(Caliber).filter_by(name="7.62x54R").one().aliases == "7.62x54mmR"

    def test_listings_its_spellings_touch_are_matched_again(
        self, client, admin_headers, seeded, behind
    ):
        site = seeded.query(Site).first()
        item = Item(
            site_id=site.id,
            external_key="ru",
            url="https://x.test/ru",
            title="Mosin-Nagant M91/30 rifle in 7.62 Russian",
            is_rifle=True,
        )
        seeded.add(item)
        seeded.commit()
        body = client.post("/api/armory/sync", headers=admin_headers).json()
        assert body["items_restamped"] >= 1
        seeded.refresh(item)
        assert item.caliber == "7.62x54R"
        assert item.firearm_model_id is not None

    def test_an_armory_that_matches_changes_nothing(
        self, client, admin_headers, seeded, shipped, since
    ):
        _clear_armory(seeded)
        armory.apply_sync(seeded, shipped)
        seeded.commit()
        body = client.post("/api/armory/sync", headers=admin_headers).json()
        assert body["changed"] == 0 and "matches" in body["message"]
        assert _events(seeded, since) == []

    def test_only_an_administrator(self, client, normal_user, shipped):
        headers = normal_user["headers"]
        assert client.get("/api/armory/sync/plan", headers=headers).status_code == 403
        assert client.post("/api/armory/sync", headers=headers).status_code == 403


class TestFromTheCommandLine:
    def test_a_sync_records_its_changes_too(self, seeded, shipped, since):
        _clear_armory(seeded)
        events: list[armory.LoadEvent] = []
        armory.apply_sync(seeded, shipped, events=events)
        armory.record_load(seeded, events, actor=None, source="armory.yaml (command line)")
        seeded.commit()
        created = _events(seeded, since, "armory.created")
        assert len(created) == len(events) >= 4
        assert all("command line" in event.detail for event in created)

    def test_a_pruning_sync_records_what_it_deleted(self, seeded, shipped, since):
        _clear_armory(seeded)
        armory.apply_sync(seeded, shipped)
        extra = Caliber(name="9x99mm Imaginary", status=ArmoryStatus.APPROVED)
        seeded.add(extra)
        seeded.commit()
        extra_id = extra.id
        events: list[armory.LoadEvent] = []
        armory.apply_sync(seeded, shipped, prune=True, events=events)
        armory.record_load(seeded, events, actor=None, source="armory.yaml (command line)")
        seeded.commit()
        [deleted] = _events(seeded, since, "armory.deleted")
        assert (deleted.target_label, deleted.target_id) == ("9x99mm Imaginary", str(extra_id))
        assert json.loads(deleted.before_state)["name"] == "9x99mm Imaginary"
