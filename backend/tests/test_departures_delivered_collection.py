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

    def test_the_fee_is_the_cheapest_dealers(self, client, normal_user):
        headers = normal_user["headers"]
        assert client.get("/api/preferences/costs", headers=headers).json() == {
            "ffl_transfer_fee": None,
            "has_cr_license": False,
        }
        client.post("/api/dealers", json={"name": "A", "transfer_fee": 30}, headers=headers)
        client.post("/api/dealers", json={"name": "B", "transfer_fee": 20}, headers=headers)
        assert client.get("/api/preferences/costs", headers=headers).json() == {
            "ffl_transfer_fee": 20.0,
            "has_cr_license": False,
        }

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


class TestComparables:
    """What the value was drawn from, chosen by the same rules as the value."""

    def test_the_departures_and_the_shelf_behind_a_value(self, owner):
        session, shops, k31, user = owner
        for index in range(5):
            _gun(session, shops[0], f"g{index}", 450 + index, model=k31, left_days_ago=1 + index)
            _gun(session, shops[1], f"live{index}", 600 - index, model=k31)
        _gun(session, shops[1], "bayonet", 40, model=k31, is_rifle=False, is_bayonet=True)
        row = CollectionItem(user_id=user.id, title="My K31", firearm_model_id=k31.id)
        session.add(row)
        session.commit()

        found = collection.comparables(session, row)
        assert found.valuation.estimate == 452
        assert [item.current_price for item in found.departed] == [450, 451, 452, 453, 454]
        # Cheapest first on the shelf, and no bayonet among the guns.
        assert [item.current_price for item in found.shelf] == [596, 597, 598, 599, 600]
        assert found.grade is None

    def test_narrowed_to_the_condition_when_the_value_was(self, owner):
        session, shops, k31, user = owner
        for index in range(5):
            _gun(session, shops[1], f"vg{index}", 700, model=k31, condition_grade="very_good")
            _gun(session, shops[1], f"f{index}", 350, model=k31, condition_grade="fair")
        row = CollectionItem(
            user_id=user.id, title="K31", firearm_model_id=k31.id, condition_grade="very_good"
        )
        session.add(row)
        session.commit()
        found = collection.comparables(session, row)
        assert found.grade == "very_good"
        assert {item.condition_grade for item in found.shelf} == {"very_good"}

    def test_but_not_when_too_few_share_it(self, owner):
        session, shops, k31, user = owner
        for index in range(5):
            _gun(session, shops[1], f"g{index}", 500, model=k31, condition_grade="good")
        row = CollectionItem(
            user_id=user.id, title="K31", firearm_model_id=k31.id, condition_grade="excellent"
        )
        session.add(row)
        session.commit()
        found = collection.comparables(session, row)
        assert found.grade is None
        assert len(found.shelf) == 5

    def test_no_model_nothing_to_compare(self, owner):
        session, _shops, _k31, user = owner
        row = CollectionItem(user_id=user.id, title="Something")
        session.add(row)
        session.commit()
        found = collection.comparables(session, row)
        assert (found.valuation, found.departed, found.shelf) == (None, [], [])

    def test_the_api_is_the_owners_only(self, client, normal_user, admin_headers):
        row = client.post(
            "/api/collection", json={"title": "Swiss K31"}, headers=normal_user["headers"]
        ).json()
        mine = client.get(
            f"/api/collection/{row['id']}/comparables", headers=normal_user["headers"]
        )
        assert mine.status_code == 200, mine.text
        assert set(mine.json()) >= {"departed", "shelf", "valuation", "limit"}
        theirs = client.get(f"/api/collection/{row['id']}/comparables", headers=admin_headers)
        assert theirs.status_code == 404


class TestTheLinkToTheComparables:
    """The collection links each value to a browse search. That search has to
    return the listings the value was drawn from, or the link is a different
    answer to the same question."""

    def test_the_search_is_the_same_listings_on_the_shelf_and_off_it(self, owner):
        from sqlalchemy import select

        from app.services import search

        session, shops, k31, user = owner
        for index in range(5):
            _gun(session, shops[0], f"g{index}", 450, model=k31, left_days_ago=1)
            _gun(session, shops[1], f"live{index}", 600, model=k31)
        _gun(session, shops[1], "kit", 90, model=k31, is_parts_kit=True)
        _gun(session, shops[1], "unpriced", 0, model=k31)
        ghost = _gun(session, shops[0], "ghost", 400, model=k31, left_days_ago=1)
        ghost.first_seen_at = ghost.delisted_at
        row = CollectionItem(user_id=user.id, title="K31", firearm_model_id=k31.id)
        session.add(row)
        session.commit()
        found = collection.comparables(session, row)

        def browse(query):
            parsed = search.parse_query(query)
            statement = search.apply_filters(select(Item.id), **parsed.filters)
            return set(session.execute(statement).scalars())

        base = f"model={k31.id}&guns_only=true"
        assert browse(base) == {item.id for item in found.shelf}
        assert browse(f"{base}&availability=left") == {item.id for item in found.departed}


class TestChoosingTheModel:
    """The owner says what the gun is, rather than guessing the armory's words.

    "Carcano Carbine" is a fair name for a Moschetto and matched no model, and
    the only way to a valuation was rewording the title until something did.
    """

    @pytest.fixture
    def models(self, seeded):
        from app.models import ArmoryStatus

        moschetto = FirearmModel(
            name="Carcano M91 Cavalry Carbine",
            aliases="Moschetto 91",
            status=ArmoryStatus.APPROVED,
        )
        rifle = FirearmModel(name="Carcano M91", status=ArmoryStatus.APPROVED)
        pending = FirearmModel(name="Carcano Something", status=ArmoryStatus.PENDING)
        seeded.add_all([moschetto, rifle, pending])
        seeded.commit()
        return moschetto, rifle, pending

    def test_the_search_finds_names_and_spellings_starts_first(self, client, normal_user, models):
        headers = normal_user["headers"]
        found = client.get("/api/collection/models?search=carcano", headers=headers).json()
        names = [row["name"] for row in found]
        assert "Carcano Something" not in names
        assert set(names) >= {"Carcano M91", "Carcano M91 Cavalry Carbine"}
        by_alias = client.get("/api/collection/models?search=moschetto", headers=headers).json()
        assert [row["name"] for row in by_alias] == ["Carcano M91 Cavalry Carbine"]

    def test_a_chosen_model_stays_through_a_new_title(self, client, normal_user, models):
        moschetto, _rifle, _pending = models
        headers = normal_user["headers"]
        row = client.post(
            "/api/collection",
            json={"title": "Carcano Carbine", "firearm_model_id": moschetto.id},
            headers=headers,
        ).json()
        assert row["model"] == "Carcano M91 Cavalry Carbine"
        renamed = client.patch(
            f"/api/collection/{row['id']}", json={"title": "My cavalry carbine"}, headers=headers
        ).json()
        assert renamed["firearm_model_id"] == moschetto.id

    def test_choosing_and_clearing_through_an_edit(self, client, normal_user, models):
        moschetto, _rifle, pending = models
        headers = normal_user["headers"]
        row = client.post(
            "/api/collection", json={"title": "Carcano Carbine"}, headers=headers
        ).json()
        chosen = client.patch(
            f"/api/collection/{row['id']}", json={"firearm_model_id": moschetto.id}, headers=headers
        ).json()
        assert (chosen["model"], chosen["model_declined"]) == ("Carcano M91 Cavalry Carbine", False)

        refused = client.patch(
            f"/api/collection/{row['id']}", json={"firearm_model_id": pending.id}, headers=headers
        )
        assert refused.status_code == 400

        cleared = client.patch(
            f"/api/collection/{row['id']}", json={"firearm_model_id": None}, headers=headers
        ).json()
        assert (cleared["firearm_model_id"], cleared["model_declined"]) == (None, True)


class TestArmorySpellingsOnTheForm:
    """The collection form offers the armory's calibers and makers by name or
    by any spelling -- approved and switched on only, as the model picker."""

    @pytest.fixture
    def armory_rows(self, seeded):
        from app.models import ArmoryStatus, Caliber, Manufacturer

        seeded.add_all(
            [
                Caliber(
                    name="6.5x52mm Carcano",
                    aliases="6.5 Carcano\n6.5mm Carcano",
                    status=ArmoryStatus.APPROVED,
                ),
                Caliber(name="6.5x55mm Swedish", status=ArmoryStatus.APPROVED),
                Caliber(name="6.5 Unheard Of", status=ArmoryStatus.PENDING),
                Manufacturer(
                    name="Terni Arsenal",
                    aliases="Terni",
                    status=ArmoryStatus.APPROVED,
                    country="Italy",
                ),
                Manufacturer(name="Terni Off", status=ArmoryStatus.APPROVED, enabled=False),
            ]
        )
        seeded.commit()

    def test_calibers_by_name_and_spelling(self, client, normal_user, armory_rows):
        headers = normal_user["headers"]
        names = [
            row["name"]
            for row in client.get("/api/collection/calibers?search=6.5", headers=headers).json()
        ]
        assert "6.5x52mm Carcano" in names and "6.5x55mm Swedish" in names
        assert "6.5 Unheard Of" not in names
        by_alias = client.get("/api/collection/calibers?search=carcano", headers=headers).json()
        assert [row["name"] for row in by_alias] == ["6.5x52mm Carcano"]

    def test_makers_with_their_country(self, client, normal_user, armory_rows):
        found = client.get(
            "/api/collection/makers?search=terni", headers=normal_user["headers"]
        ).json()
        assert found == [{"name": "Terni Arsenal", "country": "Italy"}]
