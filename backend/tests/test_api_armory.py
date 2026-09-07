"""The catalog admin routes: reading, editing, the approval gate and merging.

Every route is admin-only, which is the first thing tested, because the whole
value of the table is that a person vouched for it.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, Caliber, Manufacturer


@pytest.fixture
def cartridge(seeded):
    row = Caliber(name=".32 ACP", aliases="7.65mm Browning", status=ArmoryStatus.APPROVED)
    seeded.add(row)
    seeded.commit()
    return row


@pytest.fixture
def makers(seeded):
    rows = [Manufacturer(name=name) for name in ("Inland", "Rock-Ola", "IBM")]
    seeded.add_all(rows)
    seeded.commit()
    return rows


class TestOnlyAnAdmin:
    @pytest.mark.parametrize(
        "path", ["/api/armory/models", "/api/armory/calibers", "/api/armory/summary"]
    )
    def test_a_normal_user_cannot_read_it(self, client, normal_user, path):
        assert client.get(path, headers=normal_user["headers"]).status_code == 403

    def test_nor_write_it(self, client, normal_user):
        response = client.post(
            "/api/armory/models", json={"name": "M1 Carbine"}, headers=normal_user["headers"]
        )
        assert response.status_code == 403

    def test_nor_promote(self, client, normal_user):
        response = client.post(
            "/api/armory/models/promote", json={"ids": [1]}, headers=normal_user["headers"]
        )
        assert response.status_code == 403


class TestCreatingAModel:
    def test_it_arrives_awaiting_approval(self, client, admin_headers, cartridge, makers):
        """Even one an admin typed. Filling a form in is not the same as
        having checked it, and the promote button is one click away."""
        response = client.post(
            "/api/armory/models",
            json={
                "name": "M1 Carbine",
                "aliases": "US M1 Carbine",
                "kind": "carbine",
                "caliber_ids": [cartridge.id],
                "manufacturer_ids": [maker.id for maker in makers],
                "wikipedia_url": "https://en.wikipedia.org/wiki/M1_carbine",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["kind"] == "carbine"
        assert body["calibers"] == [".32 ACP"]
        assert sorted(body["manufacturers"]) == ["IBM", "Inland", "Rock-Ola"]

    def test_one_model_carries_all_of_its_makers(self, client, admin_headers, makers):
        """The M1 Carbine had nine and there must not be nine M1 Carbines."""
        client.post(
            "/api/armory/models",
            json={"name": "M1 Carbine", "manufacturer_ids": [m.id for m in makers]},
            headers=admin_headers,
        )
        rows = client.get("/api/armory/models", headers=admin_headers).json()
        assert len(rows) == 1
        assert len(rows[0]["manufacturers"]) == 3

    def test_several_calibers_on_one_model(self, client, admin_headers, seeded):
        """A Steyr M95 is 8x50mmR or 8x56mmR, and that is one row."""
        rounds = [
            Caliber(name="8x50mmR Mannlicher", status=ArmoryStatus.APPROVED),
            Caliber(name="8x56mmR Hungarian", status=ArmoryStatus.APPROVED),
        ]
        seeded.add_all(rounds)
        seeded.commit()
        body = client.post(
            "/api/armory/models",
            json={"name": "Steyr M95", "caliber_ids": [r.id for r in rounds]},
            headers=admin_headers,
        ).json()
        assert sorted(body["calibers"]) == ["8x50mmR Mannlicher", "8x56mmR Hungarian"]

    def test_an_unknown_caliber_is_refused(self, client, admin_headers):
        response = client.post(
            "/api/armory/models",
            json={"name": "Steyr M95", "caliber_ids": [99999]},
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_the_reference_link_is_stored_and_editable(self, client, admin_headers):
        created = client.post(
            "/api/armory/models",
            json={"name": "M1 Garand", "wikipedia_url": "https://example.test/wrong"},
            headers=admin_headers,
        ).json()
        updated = client.patch(
            f"/api/armory/models/{created['id']}",
            json={"wikipedia_url": "https://en.wikipedia.org/wiki/M1_Garand"},
            headers=admin_headers,
        ).json()
        assert updated["wikipedia_url"] == "https://en.wikipedia.org/wiki/M1_Garand"

    def test_a_duplicate_name_is_refused_with_advice(self, client, admin_headers):
        client.post("/api/armory/models", json={"name": "M1 Garand"}, headers=admin_headers)
        response = client.post(
            "/api/armory/models", json={"name": "m1 garand"}, headers=admin_headers
        )
        assert response.status_code == 409
        assert "Merge into it" in response.json()["detail"]

    def test_an_unknown_maker_is_refused(self, client, admin_headers):
        response = client.post(
            "/api/armory/models",
            json={"name": "M1 Carbine", "manufacturer_ids": [99999]},
            headers=admin_headers,
        )
        assert response.status_code == 400


class TestThePromotionGate:
    def test_promoting_moves_it_into_production(self, client, admin_headers):
        created = client.post(
            "/api/armory/models", json={"name": "M1 Garand"}, headers=admin_headers
        ).json()
        response = client.post(
            "/api/armory/models/promote", json={"ids": [created["id"]]}, headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["changed"] == 1
        rows = client.get("/api/armory/models?status=approved", headers=admin_headers).json()
        assert [row["name"] for row in rows] == ["M1 Garand"]

    def test_and_sending_it_back_returns_it(self, client, admin_headers):
        created = client.post(
            "/api/armory/models", json={"name": "M1 Garand"}, headers=admin_headers
        ).json()
        client.post(
            "/api/armory/models/promote", json={"ids": [created["id"]]}, headers=admin_headers
        )
        response = client.post(
            "/api/armory/models/send-back", json={"ids": [created["id"]]}, headers=admin_headers
        )
        assert response.json()["changed"] == 1

    def test_an_unknown_catalog_is_a_404(self, client, admin_headers):
        response = client.post(
            "/api/armory/nonsense/promote", json={"ids": [1]}, headers=admin_headers
        )
        assert response.status_code == 404


class TestMerging:
    def test_mosin_folds_into_mosin_nagant(self, client, admin_headers, seeded):
        source = Manufacturer(name="Mosin")
        target = Manufacturer(name="Mosin-Nagant")
        seeded.add_all([source, target])
        seeded.commit()

        response = client.post(
            "/api/armory/manufacturers/merge",
            json={"source_id": source.id, "target_id": target.id},
            headers=admin_headers,
        )
        assert response.status_code == 200
        seeded.refresh(target)
        assert "Mosin" in target.spellings

    def test_merging_a_row_into_itself_is_refused(self, client, admin_headers, cartridge):
        response = client.post(
            "/api/armory/calibers/merge",
            json={"source_id": cartridge.id, "target_id": cartridge.id},
            headers=admin_headers,
        )
        assert response.status_code == 400


class TestTheRestOfThePage:
    def test_the_summary_is_what_the_badge_counts(self, client, admin_headers):
        client.post("/api/armory/models", json={"name": "M1 Garand"}, headers=admin_headers)
        body = client.get("/api/armory/summary", headers=admin_headers).json()
        assert body["models"] == 1

    def test_the_kinds_come_from_the_backend(self, client, admin_headers):
        """Held server-side so the labels and the enum cannot drift apart."""
        kinds = client.get("/api/armory/kinds", headers=admin_headers).json()
        values = {kind["value"]: kind["is_handgun"] for kind in kinds}
        assert values["carbine"] is False
        assert values["percussion_revolver"] is True
        assert "flintlock_pistol" in values

    def test_search_matches_the_spellings_too(self, client, admin_headers):
        client.post(
            "/api/armory/calibers",
            json={"name": ".32 ACP", "aliases": "7.65mm Browning"},
            headers=admin_headers,
        )
        rows = client.get("/api/armory/calibers?search=7.65mm", headers=admin_headers).json()
        assert [row["name"] for row in rows] == [".32 ACP"]

    def test_seeding_reports_what_it_added(self, client, admin_headers):
        first = client.post("/api/armory/seed", headers=admin_headers).json()
        assert first["changed"] > 0
        assert "awaiting approval" in first["message"]
        assert client.post("/api/armory/seed", headers=admin_headers).json()["changed"] == 0

    def test_deleting(self, client, admin_headers):
        created = client.post(
            "/api/armory/calibers", json={"name": ".45-70"}, headers=admin_headers
        ).json()
        assert (
            client.delete(f"/api/armory/calibers/{created['id']}", headers=admin_headers)
        ).status_code == 204
        assert client.get("/api/armory/calibers", headers=admin_headers).json() == []
