"""Every change to the armory leaves a line in the audit log.

Until 2026-10-01 only edits, deletions and reverts did. A Colt Police Positive
was added and approved and the log said nothing, because creating a row and
moving it into production were never recorded -- nor were sending one back,
merging, un-merging, choosing a primary name, loading the shipped armory, or
anything at all done to a manufacturer. Each of those is held here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func

from app.models import AuditEvent


@pytest.fixture
def since(seeded):
    """The newest event before the test: audit events outlive a test's other
    rows, so each test reads only what it caused."""
    return seeded.query(func.max(AuditEvent.id)).scalar() or 0


def _events(session, action, since):
    session.expire_all()
    return (
        session.query(AuditEvent)
        .filter(AuditEvent.action == action, AuditEvent.id > since)
        .order_by(AuditEvent.id)
        .all()
    )


def test_adding_and_approving_a_model(client, admin_headers, seeded, since):
    created = client.post(
        "/api/armory/models",
        json={"name": "Police Positive", "aliases": "Colt Police Positive"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    (event,) = _events(seeded, "armory.created", since)
    assert (event.target_type, event.target_label, event.actor_name) == (
        "model",
        "Police Positive",
        "admin",
    )
    assert event.detail == "awaiting approval"

    approved = client.post(
        "/api/armory/models/promote", json={"ids": [model_id]}, headers=admin_headers
    )
    assert approved.status_code == 200
    assert [e.target_label for e in _events(seeded, "armory.approved", since)] == [
        "Police Positive"
    ]

    # Approving it again moves nothing, and so says nothing.
    client.post("/api/armory/models/promote", json={"ids": [model_id]}, headers=admin_headers)
    assert len(_events(seeded, "armory.approved", since)) == 1

    client.post("/api/armory/models/send-back", json={"ids": [model_id]}, headers=admin_headers)
    assert [e.target_label for e in _events(seeded, "armory.sent_back", since)] == [
        "Police Positive"
    ]

    renamed = client.post(
        f"/api/armory/models/{model_id}/primary",
        json={"name": "Colt Police Positive"},
        headers=admin_headers,
    )
    assert renamed.status_code == 200, renamed.text
    (event,) = _events(seeded, "armory.renamed", since)
    assert event.target_label == "Colt Police Positive"
    assert event.detail.startswith("was Police Positive")


def test_a_caliber_added_merged_and_unmerged(client, admin_headers, seeded, since):
    first = client.post("/api/armory/calibers", json={"name": ".38 S&W"}, headers=admin_headers)
    second = client.post(
        "/api/armory/calibers", json={"name": ".38 Smith & Wesson"}, headers=admin_headers
    )
    assert [e.target_label for e in _events(seeded, "armory.created", since)] == [
        ".38 S&W",
        ".38 Smith & Wesson",
    ]
    merged = client.post(
        "/api/armory/calibers/merge",
        json={"source_id": second.json()["id"], "target_id": first.json()["id"]},
        headers=admin_headers,
    )
    assert merged.status_code == 200, merged.text
    (event,) = _events(seeded, "armory.merged", since)
    assert event.target_label == ".38 S&W"
    assert ".38 Smith & Wesson merged into it" in event.detail

    unmerged = client.post(
        f"/api/armory/calibers/{second.json()['id']}/unmerge", headers=admin_headers
    )
    assert unmerged.status_code == 200, unmerged.text
    assert len(_events(seeded, "armory.unmerged", since)) == 1


def test_a_manufacturer_from_start_to_finish_and_an_edit_undone(
    client, admin_headers, seeded, since
):
    created = client.post(
        "/api/manufacturers", json={"name": "Colt Patent Fire Arms"}, headers=admin_headers
    )
    assert created.status_code == 201, created.text
    maker_id = created.json()["manufacturer"]["id"]
    assert [e.target_type for e in _events(seeded, "armory.created", since)] == ["manufacturer"]

    client.patch(
        f"/api/manufacturers/{maker_id}", json={"country": "United States"}, headers=admin_headers
    )
    (edit,) = _events(seeded, "armory.edited", since)
    assert edit.detail == "country"
    log = client.get("/api/audit?action=armory.edited", headers=admin_headers).json()
    assert log[0]["revertible"] is True

    undone = client.post(f"/api/armory/revert/{edit.id}", headers=admin_headers)
    assert undone.status_code == 200, undone.text

    client.delete(f"/api/manufacturers/{maker_id}", headers=admin_headers)
    (deleted,) = _events(seeded, "armory.deleted", since)
    assert deleted.target_label == "Colt Patent Fire Arms"


def test_loading_the_shipped_armory_is_one_line(client, admin_headers, seeded, since):
    loaded = client.post("/api/armory/seed", headers=admin_headers)
    assert loaded.status_code == 200
    (event,) = _events(seeded, "armory.seeded", since)
    assert "model(s) added" in event.detail
    # Nothing new the second time, and nothing said.
    client.post("/api/armory/seed", headers=admin_headers)
    assert len(_events(seeded, "armory.seeded", since)) == 1
