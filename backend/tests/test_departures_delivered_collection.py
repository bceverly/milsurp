"""Three answers about money: what guns went for, what one costs delivered, and
what the ones you own are worth.

**Departures.** The last asking price of firearms that left the shelf -- the
nearest thing to a sale price the catalog has. A listing already gone when it
was first seen is left out: we never saw it for sale.

**Delivered.** The shelf price plus the shop's stated firearm shipping and the
reader's own transfer fee, for firearms only -- and marked incomplete, never
silently free, where either is unknown.

**The collection.** A reader's own guns, valued against the same model's
departures first and its shelf second, like with like on condition where the
sample allows, and never from a caliber.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import CollectionItem, FirearmModel, Item, Site, User, UserRole, utcnow
from app.security import hash_password
from app.services import collection, delivered, market


@pytest.fixture
def world(clean_db):
    shops = [Site(slug=f"d{n}", name=f"Shop {n}", base_url=f"https://d{n}.test/") for n in (1, 2)]
    k31 = FirearmModel(name="Swiss K31")
    clean_db.add_all([*shops, k31])
    clean_db.commit()
    return clean_db, shops, k31


def _gun(session, site, key, price, *, model=None, left_days_ago=None, sold=False, **kwargs):
    seen = utcnow() - timedelta(days=30)
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"{site.base_url}{key}",
        title=kwargs.pop("title", "Swiss K31 carbine"),
        caliber=kwargs.pop("caliber", "7.5x55mm Swiss"),
        current_price=float(price),
        is_rifle=kwargs.pop("is_rifle", True),
        first_seen_at=seen,
        firearm_model_id=model.id if model else None,
        **kwargs,
    )
    if left_days_ago is not None:
        left = utcnow() - timedelta(days=left_days_ago)
        item.is_active = False
        if sold:
            item.is_sold, item.sold_at = True, left
        else:
            item.delisted_at = left
    session.add(item)
    session.flush()
    return item


class TestDepartures:
    def test_the_last_asking_price_of_what_left(self, world):
        session, shops, k31 = world
        for index, price in enumerate([400, 420, 440, 460, 480]):
            _gun(session, shops[index % 2], f"g{index}", price, model=k31, left_days_ago=2)
        _gun(session, shops[0], "live", 999, model=k31)
        session.commit()
        result = market.departures(session, "model")
        band = result.bands[0]
        assert (band.value, band.listings, band.median) == ("Swiss K31", 5, 440)
        assert band.sites == 2

    def test_marked_sold_and_taken_down_both_count_and_are_told_apart(self, world):
        session, shops, k31 = world
        for index in range(5):
            _gun(session, shops[0], f"g{index}", 400, model=k31, left_days_ago=1, sold=index < 2)
        session.commit()
        result = market.departures(session, "model")
        assert (result.measured, result.marked_sold) == (5, 2)

    def test_one_already_gone_when_first_seen_is_left_out(self, world):
        session, shops, k31 = world
        item = _gun(session, shops[0], "ghost", 400, model=k31, left_days_ago=1)
        item.first_seen_at = item.delisted_at
        session.commit()
        assert market.departures(session, "model").measured == 0

    def test_too_few_is_counted_not_shown(self, world):
        session, shops, k31 = world
        for index in range(3):
            _gun(session, shops[0], f"g{index}", 400, model=k31, left_days_ago=1)
        session.commit()
        result = market.departures(session, "model")
        assert result.bands == []
        assert (result.thin_groups, result.thin_listings) == (1, 3)

    def test_a_listing_page_gets_its_models_figure(self, world):
        session, shops, k31 = world
        for index in range(5):
            _gun(session, shops[0], f"g{index}", 500 + index, model=k31, left_days_ago=1)
        here = _gun(session, shops[1], "here", 450, model=k31)
        session.commit()
        band = market.departures_for(session, here)
        assert band is not None and band.median == 502

    def test_and_a_bayonet_gets_none(self, world):
        session, shops, k31 = world
        for index in range(5):
            _gun(session, shops[0], f"g{index}", 500, model=k31, left_days_ago=1)
        bayonet = _gun(session, shops[1], "b", 50, model=k31, is_rifle=False, is_bayonet=True)
        session.commit()
        assert market.departures_for(session, bayonet) is None

    def test_the_api(self, client, normal_user):
        response = client.get("/api/market/departures?by=caliber", headers=normal_user["headers"])
        assert response.status_code == 200
        assert (
            client.get("/api/market/departures?by=nope", headers=normal_user["headers"]).status_code
            == 422
        )


class TestDelivered:
    def _costs(self, site, *, long_gun=None, handgun=None, fee=None):
        return delivered.Costs(
            by_site={site.id: delivered.Shipping(long_gun=long_gun, handgun=handgun)},
            transfer_fee=fee,
        )

    def test_price_shipping_and_fee_added_up(self, world):
        session, shops, _k31 = world
        item = _gun(session, shops[0], "r", 400)
        landed = self._costs(shops[0], long_gun=35, fee=25).delivered(item)
        assert (landed.total, landed.complete) == (460, True)

    def test_a_handgun_ships_at_the_handgun_rate(self, world):
        session, shops, _k31 = world
        pistol = _gun(session, shops[0], "p", 300, is_rifle=False, is_pistol=True)
        landed = self._costs(shops[0], long_gun=35, handgun=25, fee=0).delivered(pistol)
        assert landed.shipping == 25

    def test_unknown_shipping_is_a_floor_not_free(self, world):
        session, shops, _k31 = world
        item = _gun(session, shops[0], "r", 400)
        landed = self._costs(shops[0], fee=25).delivered(item)
        assert (landed.total, landed.complete, landed.shipping) == (425, False, None)

    def test_an_accessory_has_no_delivered_price(self, world):
        session, shops, _k31 = world
        sling = _gun(session, shops[0], "s", 30, is_rifle=False)
        assert self._costs(shops[0], long_gun=35, fee=25).delivered(sling) is None

    def test_an_administrators_figure_outranks_the_scrapers(self, world):
        _session, shops, _k31 = world
        shops[0].shipping_handgun = 19.0
        rates = delivered.shipping_for_site(shops[0])
        assert (rates.handgun, rates.overridden) == (19.0, True)

    def test_the_fee_is_saved_and_priced_in(self, client, normal_user):
        headers = normal_user["headers"]
        assert client.get("/api/preferences/costs", headers=headers).json() == {
            "ffl_transfer_fee": None
        }
        saved = client.put("/api/preferences/costs", json={"ffl_transfer_fee": 30}, headers=headers)
        assert saved.json() == {"ffl_transfer_fee": 30.0}
        assert (
            client.put(
                "/api/preferences/costs", json={"ffl_transfer_fee": -1}, headers=headers
            ).status_code
            == 422
        )

    def test_an_administrator_can_override_and_clear_a_sites_shipping(self, client, admin_headers):
        site_id = client.get("/api/sites", headers=admin_headers).json()[0]["id"]
        changed = client.patch(
            f"/api/sites/{site_id}", json={"shipping_long_gun": 40}, headers=admin_headers
        ).json()
        assert (changed["shipping_long_gun"], changed["shipping_overridden"]) == (40, True)
        cleared = client.patch(
            f"/api/sites/{site_id}", json={"shipping_long_gun": None}, headers=admin_headers
        ).json()
        assert cleared["shipping_overridden"] is False


@pytest.fixture
def owner(world):
    session, shops, k31 = world
    user = User(
        username="owner",
        email="owner@example.test",
        password_hash=hash_password("x" * 16),
        role=UserRole.NORMAL,
    )
    session.add(user)
    session.commit()
    return session, shops, k31, user


class TestTheCollection:
    def test_valued_by_what_the_model_left_the_shelf_at(self, owner):
        session, shops, k31, user = owner
        for index in range(5):
            _gun(session, shops[0], f"g{index}", 450, model=k31, left_days_ago=1)
            _gun(session, shops[1], f"live{index}", 600, model=k31)
        row = CollectionItem(user_id=user.id, title="My K31", firearm_model_id=k31.id, paid=300)
        session.add(row)
        session.commit()
        found = collection.value(session, row)
        assert (found.estimate, found.basis) == (450, "left")
        assert found.shelf.median == 600

    def test_the_shelf_when_nothing_has_left(self, owner):
        session, shops, k31, user = owner
        for index in range(5):
            _gun(session, shops[1], f"live{index}", 600, model=k31)
        row = CollectionItem(user_id=user.id, title="My K31", firearm_model_id=k31.id)
        session.add(row)
        session.commit()
        found = collection.value(session, row)
        assert (found.estimate, found.basis) == (600, "shelf")

    def test_like_with_like_on_condition_where_there_are_enough(self, owner):
        session, shops, k31, user = owner
        for index in range(5):
            _gun(session, shops[1], f"vg{index}", 700, model=k31, condition_grade="very_good")
            _gun(session, shops[1], f"f{index}", 350, model=k31, condition_grade="fair")
        row = CollectionItem(
            user_id=user.id, title="K31", firearm_model_id=k31.id, condition_grade="very_good"
        )
        session.add(row)
        session.commit()
        found = collection.value(session, row)
        assert (found.estimate, found.like_for_like) == (700, True)

    def test_no_model_no_number(self, owner):
        session, _shops, _k31, user = owner
        row = CollectionItem(user_id=user.id, title="Something in 7.62x54R", caliber="7.62x54R")
        session.add(row)
        session.commit()
        assert collection.value(session, row) is None

    def test_gain_is_measured_over_the_same_guns(self, owner):
        _session, _shops, _k31, user = owner
        rows = [
            CollectionItem(user_id=user.id, title="a", paid=300),
            CollectionItem(user_id=user.id, title="b", paid=500),
        ]
        valued = [
            (rows[0], collection.Valuation(450, "left", False, None, None)),
            (rows[1], None),
        ]
        totals = collection.totals(valued)
        assert (totals.paid, totals.value) == (800, 450)
        assert (totals.compared_paid, totals.compared_value) == (300, 450)


class TestTheCollectionApi:
    def test_add_list_edit_export_delete(self, client, normal_user):
        headers = normal_user["headers"]
        created = client.post(
            "/api/collection",
            json={"title": "Swiss K31", "paid": 325, "condition_grade": "very_good"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        row = created.json()
        assert row["condition_grade_label"] == "Very good"

        listed = client.get("/api/collection", headers=headers).json()
        assert listed["totals"]["count"] == 1
        assert listed["totals"]["paid"] == 325

        edited = client.patch(
            f"/api/collection/{row['id']}", json={"paid": None, "notes": "Dad's"}, headers=headers
        ).json()
        assert (edited["paid"], edited["notes"]) == (None, "Dad's")

        export = client.get("/api/collection/export", headers=headers)
        assert export.status_code == 200
        assert "Swiss K31" in export.text

        assert client.delete(f"/api/collection/{row['id']}", headers=headers).status_code == 204
        assert client.get("/api/collection", headers=headers).json()["items"] == []

    def test_somebody_elses_row_is_not_found(self, client, normal_user, admin_headers):
        row = client.post("/api/collection", json={"title": "Mine"}, headers=admin_headers).json()
        response = client.patch(
            f"/api/collection/{row['id']}", json={"notes": "x"}, headers=normal_user["headers"]
        )
        assert response.status_code == 404

    def test_bought_this_fills_it_in_from_the_listing(self, client, normal_user, seeded):
        site = seeded.query(Site).order_by(Site.id).first()
        item = Item(
            site_id=site.id,
            external_key="bought",
            url=f"{site.base_url}bought",
            title="Swiss K31 carbine, very good",
            current_price=399.0,
            is_rifle=True,
        )
        seeded.add(item)
        seeded.commit()
        response = client.post(
            f"/api/collection/from-item/{item.id}", headers=normal_user["headers"]
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert (body["title"], body["paid"], body["item_id"]) == (
            item.title[:200],
            item.current_price,
            item.id,
        )
        assert body["acquired_from"]

    def test_declining_the_model_keeps_it_declined(self, client, normal_user):
        headers = normal_user["headers"]
        row = client.post("/api/collection", json={"title": "Thing"}, headers=headers).json()
        declined = client.patch(
            f"/api/collection/{row['id']}", json={"model_declined": True}, headers=headers
        ).json()
        assert (declined["model_declined"], declined["firearm_model_id"]) == (True, None)
