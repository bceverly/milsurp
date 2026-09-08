"""The maker list over HTTP: admin-only, and it re-files listings as it goes."""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmModel, Item, Manufacturer, Site, utcnow


@pytest.fixture
def site(seeded):
    return seeded.query(Site).order_by(Site.id).first()


@pytest.fixture
def maker(seeded):
    row = Manufacturer(name="Mauser", position=10)
    seeded.add(row)
    seeded.commit()
    return row


def add_listing(session, site, key, title, description=None, manufacturer=None):
    session.add(
        Item(
            site_id=site.id,
            external_key=key,
            url=f"https://example.test/{key}",
            title=title,
            description=description,
            manufacturer=manufacturer,
            is_active=True,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
        )
    )
    session.commit()


class TestAccess:
    def test_a_normal_user_cannot_read_the_list(self, client, normal_user):
        assert client.get("/api/manufacturers", headers=normal_user["headers"]).status_code == 403

    def test_a_normal_user_cannot_add_one(self, client, normal_user):
        response = client.post(
            "/api/manufacturers", json={"name": "Husqvarna"}, headers=normal_user["headers"]
        )
        assert response.status_code == 403

    def test_a_signed_out_visitor_gets_nowhere(self, client):
        assert client.get("/api/manufacturers").status_code == 401


class TestListing:
    def test_it_comes_back_in_the_order_the_rules_are_tried(self, client, admin_headers, seeded):
        seeded.add_all(
            [
                Manufacturer(name="Nagant", position=90),
                Manufacturer(name="Mosin-Nagant", position=10),
            ]
        )
        seeded.commit()

        names = [
            row["name"] for row in client.get("/api/manufacturers", headers=admin_headers).json()
        ]
        assert names == ["Mosin-Nagant", "Nagant"]

    def test_it_says_how_many_listings_each_one_holds(
        self, client, admin_headers, seeded, site, maker
    ):
        add_listing(seeded, site, "a", "K98 rifle", manufacturer="Mauser")
        add_listing(seeded, site, "b", "M48 rifle", manufacturer="Mauser")

        row = client.get("/api/manufacturers", headers=admin_headers).json()[0]
        assert row["item_count"] == 2


class TestTheApprovalStateIsVisible:
    """Reported from the running site: every maker in the Manufacturers tab
    drew the "Awaiting approval" chip, and approving them changed nothing.

    Two bugs, and the second hid the first. ManufacturerOut carried no
    ``status`` at all, so the page read ``undefined`` and fell through to the
    chip it shows for a status it does not recognize -- while the database
    said all fifty-one were approved. And the list endpoint took no ``status``
    filter, so the tab returned every row whatever the page was set to.
    """

    def test_the_status_comes_back(self, client, admin_headers, seeded):
        seeded.add(Manufacturer(name="Mauser", status=ArmoryStatus.APPROVED))
        seeded.commit()
        row = client.get("/api/manufacturers", headers=admin_headers).json()[0]
        assert row["status"] == "approved"

    def test_a_pending_one_says_so(self, client, admin_headers, seeded):
        seeded.add(Manufacturer(name="Norinco", status=ArmoryStatus.PENDING))
        seeded.commit()
        row = client.get("/api/manufacturers", headers=admin_headers).json()[0]
        assert row["status"] == "pending"

    def test_the_list_can_be_filtered_by_it(self, client, admin_headers, seeded):
        seeded.add_all(
            [
                Manufacturer(name="Mauser", status=ArmoryStatus.APPROVED),
                Manufacturer(name="Norinco", status=ArmoryStatus.PENDING),
            ]
        )
        seeded.commit()
        pending = client.get("/api/manufacturers?status=pending", headers=admin_headers).json()
        assert [row["name"] for row in pending] == ["Norinco"]
        approved = client.get("/api/manufacturers?status=approved", headers=admin_headers).json()
        assert [row["name"] for row in approved] == ["Mauser"]

    def test_and_searched(self, client, admin_headers, seeded):
        seeded.add_all(
            [
                Manufacturer(name="Mauser", aliases="Mauser-Werke"),
                Manufacturer(name="Norinco"),
            ]
        )
        seeded.commit()
        found = client.get("/api/manufacturers?search=werke", headers=admin_headers).json()
        assert [row["name"] for row in found] == ["Mauser"]

    def test_promoting_one_is_visible_in_the_next_payload(self, client, admin_headers, seeded):
        """The half that made it look like nothing happened."""
        seeded.add(Manufacturer(name="Norinco", status=ArmoryStatus.PENDING))
        seeded.commit()
        row_id = client.get("/api/manufacturers", headers=admin_headers).json()[0]["id"]
        client.post(
            "/api/armory/manufacturers/promote", json={"ids": [row_id]}, headers=admin_headers
        )
        row = client.get("/api/manufacturers", headers=admin_headers).json()[0]
        assert row["status"] == "approved"

    def test_a_maker_typed_by_hand_is_production_at_once(self, client, admin_headers, seeded):
        """Deliberately unlike a model or a caliber. Saving a maker re-files
        every listing it can reach, which is the point of the page, and a
        pending maker matches nothing."""
        body = client.post(
            "/api/manufacturers", json={"name": "Husqvarna"}, headers=admin_headers
        ).json()
        row = seeded.query(Manufacturer).filter_by(name="Husqvarna").one()
        assert row.status is ArmoryStatus.APPROVED
        assert "listings_changed" in body


class TestAdding:
    def test_it_files_the_listings_that_name_it(self, client, admin_headers, seeded, site):
        add_listing(seeded, site, "a", "Husqvarna M38 Swedish rifle")
        add_listing(seeded, site, "b", "GERMAN K98 rifle")

        response = client.post(
            "/api/manufacturers",
            json={"name": "Husqvarna", "position": 5},
            headers=admin_headers,
        )

        assert response.status_code == 201
        assert response.json()["listings_changed"] == 1
        seeded.expire_all()
        filed = {item.title: item.manufacturer for item in seeded.query(Item)}
        assert filed["Husqvarna M38 Swedish rifle"] == "Husqvarna"
        assert filed["GERMAN K98 rifle"] is None

    def test_aliases_are_matched_too(self, client, admin_headers, seeded, site):
        add_listing(seeded, site, "a", "a S&W Model 10 revolver")

        response = client.post(
            "/api/manufacturers",
            json={"name": "Smith & Wesson", "aliases": "S&W", "position": 5},
            headers=admin_headers,
        )

        assert response.json()["listings_changed"] == 1
        seeded.expire_all()
        assert seeded.query(Item).one().manufacturer == "Smith & Wesson"

    def test_two_makers_cannot_share_a_name(self, client, admin_headers, maker):
        response = client.post("/api/manufacturers", json={"name": "mauser"}, headers=admin_headers)
        assert response.status_code == 409


class TestEditing:
    def test_an_added_alias_picks_up_more_listings(
        self, client, admin_headers, seeded, site, maker
    ):
        add_listing(seeded, site, "a", "GERMAN K98 Mauser", manufacturer="Mauser")
        add_listing(seeded, site, "b", "Karabiner 98k, matching")

        response = client.patch(
            f"/api/manufacturers/{maker.id}",
            json={"aliases": "Karabiner 98k"},
            headers=admin_headers,
        )

        assert response.json()["listings_changed"] == 1
        seeded.expire_all()
        assert {item.manufacturer for item in seeded.query(Item)} == {"Mauser"}

    def test_a_removed_alias_lets_its_listings_go(self, client, admin_headers, seeded, site):
        """The half that is easy to forget: an edit has to look at what the
        rule *used* to match, or its old answer is left behind."""
        seeded.add(Manufacturer(name="Mauser", aliases="Karabiner 98k", position=10))
        seeded.commit()
        add_listing(seeded, site, "b", "Karabiner 98k, matching", manufacturer="Mauser")

        row = seeded.query(Manufacturer).one()
        response = client.patch(
            f"/api/manufacturers/{row.id}", json={"aliases": ""}, headers=admin_headers
        )

        assert response.json()["listings_changed"] == 1
        seeded.expire_all()
        assert seeded.query(Item).one().manufacturer is None

    def test_renaming_moves_the_listings_with_it(self, client, admin_headers, seeded, site, maker):
        add_listing(seeded, site, "a", "GERMAN K98 Mauser", manufacturer="Mauser")

        response = client.patch(
            f"/api/manufacturers/{maker.id}",
            json={"name": "Mauser-Werke", "aliases": "Mauser"},
            headers=admin_headers,
        )

        assert response.status_code == 200
        seeded.expire_all()
        assert seeded.query(Item).one().manufacturer == "Mauser-Werke"

    def test_turning_a_rule_off_stops_it_matching(self, client, admin_headers, seeded, site, maker):
        add_listing(seeded, site, "a", "GERMAN K98 Mauser", manufacturer="Mauser")

        client.patch(
            f"/api/manufacturers/{maker.id}", json={"enabled": False}, headers=admin_headers
        )

        seeded.expire_all()
        assert seeded.query(Item).one().manufacturer is None

    def test_editing_one_that_is_not_there(self, client, admin_headers):
        response = client.patch(
            "/api/manufacturers/9999", json={"name": "Nobody"}, headers=admin_headers
        )
        assert response.status_code == 404


class TestDeleting:
    def test_its_listings_are_re_checked_against_what_is_left(
        self, client, admin_headers, seeded, site, maker
    ):
        add_listing(seeded, site, "a", "GERMAN K98 Mauser", manufacturer="Mauser")

        response = client.delete(f"/api/manufacturers/{maker.id}", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["listings_changed"] == 1
        seeded.expire_all()
        assert seeded.query(Item).one().manufacturer is None

    def test_a_listing_another_rule_still_matches_keeps_a_maker(
        self, client, admin_headers, seeded, site
    ):
        seeded.add_all(
            [
                Manufacturer(name="Mauser", position=10),
                Manufacturer(name="Husqvarna", position=20),
            ]
        )
        seeded.commit()
        add_listing(seeded, site, "a", "Husqvarna Mauser M38", manufacturer="Mauser")

        mauser = seeded.query(Manufacturer).filter_by(name="Mauser").one()
        client.delete(f"/api/manufacturers/{mauser.id}", headers=admin_headers)

        seeded.expire_all()
        assert seeded.query(Item).one().manufacturer == "Husqvarna"

    def test_the_listings_themselves_survive(self, client, admin_headers, seeded, site, maker):
        add_listing(seeded, site, "a", "GERMAN K98 Mauser", manufacturer="Mauser")

        client.delete(f"/api/manufacturers/{maker.id}", headers=admin_headers)

        assert seeded.query(Item).count() == 1


class TestModelsAreNoLongerEditedHere:
    """They moved to the armory, and the maker dialog is simpler for it.

    A maker used to carry its models as a block of text, which could only say
    "this firm made something called M44" — so a designation two firms both
    made had to be dropped from matching, because a flat list per firm cannot
    express one thing built by two. The armory keeps one row per model with
    all of its makers on it, and this page reports the tally.
    """

    def test_a_maker_reports_how_many_models_the_armory_gives_it(
        self, client, admin_headers, seeded
    ):
        created = client.post(
            "/api/manufacturers",
            json={"name": "Mosin-Nagant", "position": 5},
            headers=admin_headers,
        ).json()["manufacturer"]
        assert created["model_count"] == 0

        maker = seeded.query(Manufacturer).filter_by(name="Mosin-Nagant").one()
        for name in ("M44", "M91/30"):
            row = FirearmModel(name=name, status=ArmoryStatus.APPROVED)
            row.manufacturers.append(maker)
            seeded.add(row)
        seeded.commit()

        listed = client.get("/api/manufacturers", headers=admin_headers).json()
        entry = next(row for row in listed if row["name"] == "Mosin-Nagant")
        assert entry["model_count"] == 2

    def test_the_flat_models_field_is_gone(self, client, admin_headers, seeded):
        """Sending it is simply ignored rather than quietly writing a second,
        divergent list of models beside the armory's."""
        created = client.post(
            "/api/manufacturers",
            json={"name": "CZ", "models": "ZB37\nZB26", "position": 5},
            headers=admin_headers,
        )
        assert created.status_code == 201
        assert "models" not in created.json()["manufacturer"]

    def test_a_model_the_armory_gives_one_maker_files_its_listings(
        self, client, admin_headers, seeded, site
    ):
        add_listing(seeded, site, "a", "RUSSIAN M44 CARBINES")
        maker = Manufacturer(name="Mosin-Nagant", position=5)
        row = FirearmModel(name="M44", status=ArmoryStatus.APPROVED)
        seeded.add_all([maker, row])
        row.manufacturers.append(maker)
        seeded.commit()

        # An edit to the maker re-derives what it can reach.
        response = client.patch(
            f"/api/manufacturers/{maker.id}", json={"notes": "checked"}, headers=admin_headers
        )
        assert response.status_code == 200
        seeded.expire_all()
        assert seeded.query(Item).one().manufacturer == "Mosin-Nagant"
