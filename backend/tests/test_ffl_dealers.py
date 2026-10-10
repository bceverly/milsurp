"""A reader's FFL dealers, and the delivered price at the cheapest of them.

Asked for on 2026-10-09 in place of the one transfer fee: each dealer's name,
address, website and fee entered by hand, and every calculation using the
lowest fee on the list.
"""

from __future__ import annotations

import pytest


def _add(client, headers, **dealer):
    response = client.post("/api/dealers", json=dealer, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestTheList:
    def test_a_dealer_is_kept_as_typed(self, client, normal_user):
        headers = normal_user["headers"]
        [dealer] = _add(
            client,
            headers,
            name="  Corner Guns ",
            address="12 Main St, Springfield",
            url="cornerguns.example",
            transfer_fee=25,
        )
        assert dealer["name"] == "Corner Guns"
        assert dealer["address"] == "12 Main St, Springfield"
        # No scheme typed is taken as the web.
        assert dealer["url"] == "https://cornerguns.example"
        assert (dealer["transfer_fee"], dealer["lowest"]) == (25.0, True)

    def test_the_cheapest_is_marked_and_priced_in(self, client, normal_user):
        headers = normal_user["headers"]
        _add(client, headers, name="Dear", transfer_fee=50)
        dealers = _add(client, headers, name="Cheap", transfer_fee=15)
        assert [(d["name"], d["lowest"]) for d in dealers] == [("Dear", False), ("Cheap", True)]
        costs = client.get("/api/preferences/costs", headers=headers).json()
        assert costs["ffl_transfer_fee"] == 15.0

    def test_a_change_and_a_delete_move_the_lowest(self, client, normal_user):
        headers = normal_user["headers"]
        _add(client, headers, name="Dear", transfer_fee=50)
        cheap = _add(client, headers, name="Cheap", transfer_fee=15)[1]
        changed = client.put(
            f"/api/dealers/{cheap['id']}",
            json={"name": "Cheap", "transfer_fee": 75},
            headers=headers,
        ).json()
        assert [d["name"] for d in changed if d["lowest"]] == ["Dear"]
        left = client.delete(f"/api/dealers/{cheap['id']}", headers=headers).json()
        assert [d["name"] for d in left] == ["Dear"]
        client.delete(f"/api/dealers/{left[0]['id']}", headers=headers)
        costs = client.get("/api/preferences/costs", headers=headers).json()
        assert costs["ffl_transfer_fee"] is None

    @pytest.mark.parametrize(
        "dealer",
        [
            {"name": "", "transfer_fee": 25},
            {"name": "   ", "transfer_fee": 25},
            {"name": "A", "transfer_fee": -1},
            {"name": "A"},
            {"name": "A", "transfer_fee": 25, "url": "javascript:alert(1)"},
            {"name": "A", "transfer_fee": 25, "url": "corner guns.example"},
        ],
    )
    def test_nonsense_is_refused(self, client, normal_user, dealer):
        response = client.post("/api/dealers", json=dealer, headers=normal_user["headers"])
        assert response.status_code == 422

    def test_another_readers_dealers_are_not_yours(self, client, normal_user, admin_headers):
        [theirs] = _add(client, admin_headers, name="Admin's", transfer_fee=10)
        headers = normal_user["headers"]
        assert client.get("/api/dealers", headers=headers).json() == []
        assert client.delete(f"/api/dealers/{theirs['id']}", headers=headers).status_code == 404
        assert (
            client.put(
                f"/api/dealers/{theirs['id']}",
                json={"name": "Mine now", "transfer_fee": 0},
                headers=headers,
            ).status_code
            == 404
        )


class TestTheListingSaysWhose:
    def test_the_delivered_price_names_the_dealer(self, client, normal_user, clean_db):
        from app.models import Item, Site

        site = Site(slug="d1", name="Shop D", base_url="https://d1.test/", shipping_long_gun=30.0)
        clean_db.add(site)
        clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key="k",
            url="https://d1.test/k",
            title="Swiss K31",
            current_price=400.0,
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.commit()
        headers = normal_user["headers"]
        _add(client, headers, name="Dear", transfer_fee=50)
        _add(client, headers, name="Cheap", transfer_fee=15)
        shown = client.get(f"/api/items/{item.id}", headers=headers).json()
        assert (shown["transfer_fee"], shown["transfer_dealer"]) == (15.0, "Cheap")
        assert shown["delivered_price"] == 445.0
