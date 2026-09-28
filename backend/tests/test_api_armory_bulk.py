"""Switching off, or deleting, a whole selection in any of the armory's tables.

The page could promote and send back a selection; ruling on a long queue of
scan-proposed junk still meant opening each row. These are the same rulings
the row editor makes, applied to many rows, and each is audited on its own so
the revert button still works row by row.
"""

from __future__ import annotations

import pytest

from app import sessions
from app.models import ArmoryStatus, AuditEvent, FirearmModel, Item, Manufacturer, Site


@pytest.fixture
def signed_in(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-passphrase"},
    )
    assert response.status_code == 200, response.text
    return response


def csrf(response) -> dict[str, str]:
    return {sessions.CSRF_HEADER: response.json()["csrf_token"]}


@pytest.fixture
def queue(clean_db, seeded):
    """Three pending models, two pending makers and one approved model with
    listings it explains."""
    session = seeded
    site = Site(slug="bulk", name="Bulk", base_url="https://b.test/")
    session.add(site)
    session.flush()
    session.add_all(
        Item(
            site_id=site.id,
            external_key=f"k{index}",
            url=f"https://b.test/{index}",
            title="Swiss K31 straight-pull rifle",
            is_active=True,
            is_rifle=True,
        )
        for index in range(2)
    )
    session.add_all(
        [
            FirearmModel(name="FAL 7", status=ArmoryStatus.PENDING),
            FirearmModel(name="RPK 7", status=ArmoryStatus.PENDING),
            FirearmModel(name="AUG 5", status=ArmoryStatus.PENDING),
            FirearmModel(name="K31", status=ArmoryStatus.APPROVED),
            Manufacturer(name="Milled", status=ArmoryStatus.PENDING),
            Manufacturer(name="Pouch", status=ArmoryStatus.PENDING),
        ]
    )
    session.commit()
    from app.services import armory

    armory.invalidate()
    armory.reprocess(session, ["K31"])
    session.commit()
    return session


def _events_since(session, action, since):
    """Audit events are not cleared between tests, so only this test's."""
    return (
        session.query(AuditEvent)
        .filter(AuditEvent.action == action, AuditEvent.id > since)
        .order_by(AuditEvent.id)
        .all()
    )


def _last_event_id(session) -> int:
    newest = session.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
    return newest.id if newest else 0


def _ids(session, model, *names):
    return [session.query(model).filter(model.name == name).one().id for name in names]


class TestSwitchingOff:
    def test_a_selection_leaves_the_queue_for_disabled(self, queue, client, signed_in):
        ids = _ids(queue, FirearmModel, "FAL 7", "RPK 7")
        response = client.post(
            "/api/armory/models/disable", json={"ids": ids}, headers=csrf(signed_in)
        )
        assert response.status_code == 200, response.text
        assert response.json()["changed"] == 2

        pending = client.get("/api/armory/models?status=pending", headers=csrf(signed_in)).json()
        disabled = client.get("/api/armory/models?status=disabled", headers=csrf(signed_in)).json()
        assert [row["name"] for row in pending] == ["AUG 5"]
        assert sorted(row["name"] for row in disabled) == ["FAL 7", "RPK 7"]

    def test_the_rows_are_kept_so_a_scan_cannot_propose_them_again(self, queue, client, signed_in):
        ids = _ids(queue, FirearmModel, "FAL 7")
        client.post("/api/armory/models/disable", json={"ids": ids}, headers=csrf(signed_in))
        from app.services import armory

        queue.expire_all()
        row = armory.propose_model(queue, "FAL 7", seen_in="FN FAL 7.62")
        # The same row, still off: nothing new joins the queue.
        assert row is not None and row.id == ids[0] and not row.enabled
        assert queue.query(FirearmModel).filter(FirearmModel.name == "FAL 7").count() == 1

    def test_makers_too(self, queue, client, signed_in):
        ids = _ids(queue, Manufacturer, "Milled", "Pouch")
        response = client.post(
            "/api/armory/manufacturers/disable", json={"ids": ids}, headers=csrf(signed_in)
        )
        assert response.json()["changed"] == 2

    def test_switching_off_an_approved_model_unlinks_its_listings(self, queue, client, signed_in):
        ids = _ids(queue, FirearmModel, "K31")
        response = client.post(
            "/api/armory/models/disable", json={"ids": ids}, headers=csrf(signed_in)
        )
        assert response.json()["items_restamped"] == 2
        queue.expire_all()
        assert all(item.firearm_model_id is None for item in queue.query(Item))

    def test_each_row_is_audited_and_can_be_reverted(self, queue, client, signed_in):
        ids = _ids(queue, FirearmModel, "FAL 7", "RPK 7")
        since = _last_event_id(queue)
        client.post("/api/armory/models/disable", json={"ids": ids}, headers=csrf(signed_in))
        events = _events_since(queue, "armory.edited", since)
        assert sorted(event.target_label for event in events) == ["FAL 7", "RPK 7"]

        response = client.post(f"/api/armory/revert/{events[0].id}", headers=csrf(signed_in))
        assert response.status_code == 200, response.text
        queue.expire_all()
        assert queue.get(FirearmModel, events[0].target_id).enabled


class TestDeleting:
    def test_a_selection_is_gone(self, queue, client, signed_in):
        ids = _ids(queue, FirearmModel, "FAL 7", "AUG 5")
        response = client.post(
            "/api/armory/models/delete", json={"ids": ids}, headers=csrf(signed_in)
        )
        assert response.json()["changed"] == 2
        names = [
            row["name"] for row in client.get("/api/armory/models", headers=csrf(signed_in)).json()
        ]
        assert "FAL 7" not in names and "AUG 5" not in names

    def test_a_deleted_maker_is_audited_and_comes_back_on_revert(self, queue, client, signed_in):
        """A single maker delete never recorded anything; through here it does."""
        ids = _ids(queue, Manufacturer, "Pouch")
        since = _last_event_id(queue)
        client.post("/api/armory/manufacturers/delete", json={"ids": ids}, headers=csrf(signed_in))
        [event] = _events_since(queue, "armory.deleted", since)
        assert event.target_label == "Pouch"

        client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))
        queue.expire_all()
        assert queue.query(Manufacturer).filter(Manufacturer.name == "Pouch").count() == 1


class TestTheGate:
    @pytest.mark.parametrize("action", ["disable", "delete"])
    def test_an_unknown_table_is_a_404(self, queue, client, signed_in, action):
        response = client.post(
            f"/api/armory/nonsense/{action}", json={"ids": [1]}, headers=csrf(signed_in)
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("action", ["disable", "delete"])
    def test_a_reader_cannot(self, queue, client, normal_user, action):
        response = client.post(
            f"/api/armory/models/{action}", json={"ids": [1]}, headers=normal_user["headers"]
        )
        assert response.status_code == 403
