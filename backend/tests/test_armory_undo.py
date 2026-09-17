"""Putting an armory row back the way it was.

A merge has always reversed — it records what it took so it can be given back —
and an ordinary edit never did. That stopped being tolerable the day an edit
began reporting how many listings it moved: *412 listing(s) re-matched* under a
dialog somebody has just closed is exactly when they want the last five minutes
back.

The interesting case is the **delete**. Undoing one cannot give the row its old
id — the listings that pointed at it were unlinked when it went — and that turns
out not to matter, because the armory matches by spelling: re-creating the row
and re-reading the listings that mention it puts the count back where it was.
There is a test for precisely that, because it is the claim the feature rests on.
"""

from __future__ import annotations

import pytest

from app import sessions
from app.models import ArmoryStatus, AuditEvent, FirearmModel, Item, Site
from app.services import armoryundo


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
def stocked(clean_db, seeded):
    session = seeded
    site = Site(slug="undo", name="Undo", base_url="https://u.test/")
    session.add(site)
    session.flush()
    session.add_all(
        Item(
            site_id=site.id,
            external_key=f"k{index}",
            url=f"https://u.test/{index}",
            title="Swiss K31 straight-pull rifle",
            is_active=True,
            is_rifle=True,
        )
        for index in range(3)
    )
    session.add(FirearmModel(name="K31", status=ArmoryStatus.APPROVED))
    session.commit()

    # Link them, as promoting the row through the API would. The fixture builds
    # the model directly, so nothing has read the listings against it yet.
    from app.services import armory

    armory.invalidate()
    armory.reprocess(session, ["K31"])
    session.commit()
    return session


def last_event(session, action):
    return (
        session.query(AuditEvent)
        .filter(AuditEvent.action == action)
        .order_by(AuditEvent.id.desc())
        .first()
    )


class TestUndoingAnEdit:
    def test_the_old_values_come_back(self, stocked, client, admin_headers, signed_in):
        model = client.get("/api/armory/models", headers=admin_headers).json()[0]
        client.patch(
            f"/api/armory/models/{model['id']}",
            json={"name": "K31 (wrong)", "notes": "typed in haste"},
            headers=csrf(signed_in),
        )

        event = last_event(stocked, "armory.edited")
        assert event is not None
        response = client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))
        assert response.status_code == 200, response.text

        after = client.get("/api/armory/models", headers=admin_headers).json()[0]
        assert after["name"] == "K31"
        assert not after["notes"]

    def test_the_row_keeps_its_id(self, stocked, client, admin_headers, signed_in):
        """An edit leaves the row in place, so everything pointing at it still
        does and nothing needs re-linking."""
        model = client.get("/api/armory/models", headers=admin_headers).json()[0]
        client.patch(
            f"/api/armory/models/{model['id']}", json={"name": "Wrong"}, headers=csrf(signed_in)
        )
        event = last_event(stocked, "armory.edited")
        client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))

        after = client.get("/api/armory/models", headers=admin_headers).json()[0]
        assert after["id"] == model["id"]

    def test_the_undo_is_itself_logged(self, stocked, client, admin_headers, signed_in):
        """So undoing the undo is the same operation on a newer event, which is
        what somebody means by "actually, put it back again"."""
        model = client.get("/api/armory/models", headers=admin_headers).json()[0]
        client.patch(
            f"/api/armory/models/{model['id']}", json={"name": "Wrong"}, headers=csrf(signed_in)
        )
        event = last_event(stocked, "armory.edited")
        client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))

        assert last_event(stocked, "armory.reverted") is not None


class TestUndoingADelete:
    def test_the_row_comes_back(self, stocked, client, admin_headers, signed_in):
        model = client.get("/api/armory/models", headers=admin_headers).json()[0]
        client.delete(f"/api/armory/models/{model['id']}", headers=csrf(signed_in))
        assert client.get("/api/armory/models", headers=admin_headers).json() == []

        event = last_event(stocked, "armory.deleted")
        response = client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))
        assert response.status_code == 200, response.text

        restored = client.get("/api/armory/models", headers=admin_headers).json()
        assert [row["name"] for row in restored] == ["K31"]

    def test_and_the_listings_find_it_again(self, stocked, client, admin_headers, signed_in):
        """The claim the whole feature rests on. The restored row cannot have
        the old id, and does not need it: the armory matches by spelling, so
        re-reading the listings that mention the name links them to the new
        row and the count comes back."""
        model = client.get("/api/armory/models", headers=admin_headers).json()[0]
        assert model["item_count"] == 3

        removed = client.delete(f"/api/armory/models/{model['id']}", headers=csrf(signed_in))
        assert removed.json()["listings_changed"] == 3

        event = last_event(stocked, "armory.deleted")
        response = client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))
        assert response.json()["items_restamped"] == 3

        # The count is the claim, and the id deliberately is not asserted
        # either way: a restored row *may* be handed the same one back (SQLite
        # reuses the highest rowid of an emptied table) and may not. Whether it
        # does is the database's business, and the feature works regardless
        # precisely because nothing here depends on it.
        restored = client.get("/api/armory/models", headers=admin_headers).json()[0]
        assert restored["item_count"] == 3

    def test_its_status_comes_back_too(self, stocked, client, admin_headers, signed_in):
        """Restoring an approved row as pending would quietly un-approve it,
        and a pending row decides nothing."""
        model = client.get("/api/armory/models", headers=admin_headers).json()[0]
        client.delete(f"/api/armory/models/{model['id']}", headers=csrf(signed_in))
        event = last_event(stocked, "armory.deleted")
        client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))

        restored = client.get("/api/armory/models", headers=admin_headers).json()[0]
        assert restored["status"] == "approved"


class TestWhatItRefuses:
    def test_an_event_that_is_not_an_armory_change(self, stocked, client, admin_headers, signed_in):
        from app.services import audit

        event = audit.record(stocked, actor=None, action=audit.SITE_ENABLED, target_type="site")
        stocked.commit()
        response = client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))
        assert response.status_code == 400
        assert "armory edit" in response.json()["detail"]

    def test_an_event_from_before_the_state_was_recorded(
        self, stocked, client, admin_headers, signed_in
    ):
        """Every event written before migration 0032 has no `before_state`, and
        saying so plainly beats offering a button that does nothing."""
        from app.services import audit

        event = audit.record(
            stocked, actor=None, action=audit.ARMORY_EDITED, target_type="model", target_id=1
        )
        stocked.commit()
        response = client.post(f"/api/armory/revert/{event.id}", headers=csrf(signed_in))
        assert response.status_code == 400
        assert "nothing to put back" in response.json()["detail"]

    def test_an_event_that_does_not_exist(self, stocked, client, signed_in):
        assert client.post("/api/armory/revert/999999", headers=csrf(signed_in)).status_code == 404

    def test_a_normal_user_cannot_undo(self, stocked, client, normal_user):
        response = client.post("/api/armory/revert/1", headers=normal_user["headers"])
        assert response.status_code == 403


class TestTheSnapshot:
    def test_it_keeps_the_relationships_by_name(self, stocked):
        """Names, not ids: a delete-and-undo gives the row a new id, and an id
        recorded here would point at nothing afterwards."""
        model = stocked.query(FirearmModel).one()
        state = armoryundo.snapshot(model)
        assert "manufacturer_names" in state
        assert "caliber_names" in state

    def test_it_leaves_out_what_cannot_be_restored(self, stocked):
        """`id`, timestamps and derived counts: restoring them would either
        fail or lie."""
        state = armoryundo.snapshot(stocked.query(FirearmModel).one())
        assert "id" not in state
        assert "created_at" not in state
        assert "item_count" not in state
