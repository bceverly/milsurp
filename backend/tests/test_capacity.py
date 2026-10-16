"""How many rounds a gun holds (app.services.capacity), and searching by it
and by frame size.

Asked for on 2026-10-16. The phrases are production's, from its 16,912 gun
listings that day; each exclusion is one a first draft misread.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmModel, Item, Site
from app.services import capacity, search, variants


def held(title, description=None, *, kind="handgun", revolver=False):
    return capacity.read(title, description, kind=kind, revolver=revolver)[0]


class TestWhatAListingSays:
    @pytest.mark.parametrize(
        ("title", "description", "expected"),
        [
            ("PD Trade | Glock 17 Gen5 | 9mm | Bold Night Sights | 17rd Pistol", None, 17),
            ("Glock 22", "Pistols come with one 15rd magazine and factory box.", 15),
            ("Pistol", "Each pistol includes one 17-round magazine and a factory box.", 17),
            ("Pistol", "Model: MP-25 * Caliber: 25 ACP * Capacity: 6 Rounds", 6),
            ("Pistol", "action Striker magazine capacity (incl) (1) 17rd sights", 17),
            ("Pistol", "CAPACITY 17+1 Rounds", 17),
            ("Shield Plus", '9mm 10/13 round capacity 3.1" barrel', 13),
            ("Mauser C96 Model 712 with 20rnd and 10rnd Magazines", None, 20),
        ],
    )
    def test_a_handgun(self, title, description, expected):
        assert held(title, description) == expected

    def test_a_revolver_and_a_long_gun(self):
        assert held("Smith & Wesson 64-5 | 38 Special | 6 Shot Revolver", revolver=True) == 6
        assert held("Springfield 1903, 5 Rd Bolt Action, 30/06 Cal", kind="long") == 5
        assert held("Mossberg 590", "magazine capacity 7+1 ffl YES", kind="long") == 7

    @pytest.mark.parametrize(
        ("title", "description"),
        [
            ("Glock 22", "Jefferson County Sheriff Office Trade in 3rd generation Glock"),
            ("DWM Navy Luger 3rd Variation 9mm", None),
            ("Pistol", '17 round capacity 4.25" barrel'),  # 17, never the 4
            ("Beretta 1934", '3.7" Barrel 7+1 Capacity 1lb 7oz'),  # 7, never the 1
            ("Norinco Type 54", "8 Round Capacity 1 8 Round Magazine"),  # 8, never the 1
            ("Rifle", "I put 200 rounds through it"),
            ("Shotgun", "Shoots #4 shot well"),
        ],
    )
    def test_not_misread(self, title, description):
        found = held(title, description, kind="long" if "Rifle" in title else "handgun")
        assert found not in (1, 3, 4, 200)

    def test_more_than_the_kind_holds_is_not_a_capacity(self):
        assert held("Revolver", "comes with a 50 round box of ammunition", revolver=True) is None


class TestAModelsStandardCapacity:
    def test_the_most_common_where_two_agree(self):
        assert capacity.standard([15, 15, 17]) == 15
        assert capacity.standard([8]) is None

    def test_the_restricted_ten_gives_way(self):
        """A Glock 17's listings say 17 and 10; its capacity is 17."""
        assert capacity.standard([10, 10, 10, 10, 17, 17]) == 17
        # A Ruger 10/22's say 10: its capacity is 10.
        assert capacity.standard([10, 10, 10, 25]) == 10


@pytest.fixture
def glocks(clean_db):
    model = FirearmModel(name="Glock 17", status=ArmoryStatus.APPROVED, modern_production=True)
    site = Site(slug="cp", name="Shop CP", base_url="https://cp.test/")
    clean_db.add_all([model, site])
    clean_db.commit()
    return clean_db, model, site


def listing(session, model, site, key, title, description=None, **kwargs):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"https://cp.test/{key}",
        title=title,
        description=description,
        is_pistol=True,
        kind="pistol",
        firearm_model_id=model.id,
        is_active=True,
        is_sold=False,
        **kwargs,
    )
    session.add(item)
    session.flush()
    variants.settle(session, item)
    session.commit()
    return item


class TestStoredOnTheListing:
    def test_its_own_words_or_its_models(self, glocks):
        session, model, site = glocks
        stated = listing(session, model, site, "a", "Glock 17 | 9mm | 17rd Pistol")
        assert (stated.capacity, stated.capacity_quote) == (17, "17rd Pistol")
        model.capacity = 17
        session.commit()
        silent = listing(session, model, site, "b", "Glock 17 Gen 4 PRE OWNED")
        assert (silent.capacity, silent.capacity_quote) == (17, None)

    def test_the_backfill_gives_models_their_standard(self, glocks):
        session, model, site = glocks
        for key, title in (("a", "Glock 17 | 17rd Pistol"), ("b", "Glock 17 | 17rd Pistol")):
            listing(session, model, site, key, title)
        silent = listing(session, model, site, "c", "Glock 17 Gen 4 PRE OWNED")
        assert silent.capacity is None
        counts = capacity.backfill(session)
        session.commit()
        session.refresh(model)
        session.refresh(silent)
        assert (counts["stated"], counts["models"], model.capacity, silent.capacity) == (
            2,
            1,
            17,
            17,
        )


class TestSearching:
    def test_by_capacity_and_frame_size(self, glocks):
        session, model, site = glocks
        full = listing(session, model, site, "a", "Glock 17 FS | 17rd Pistol")
        listing(session, model, site, "b", "Glock 43 | Subcompact | 6rd Pistol")

        def found(**filters):
            stmt = search.apply_filters(
                session.query(Item).statement,
                site_ids=None,
                categories=None,
                calibers=None,
                countries=None,
                manufacturers=None,
                models=None,
                forms=None,
                kinds=None,
                curio_states=None,
                availability="all",
                search=None,
                min_price=None,
                max_price=None,
                new_since_hours=None,
                price_drops_only=False,
                **filters,
            )
            return {row.external_key for row in session.execute(stmt).scalars()}

        assert full.frame_size == "Full size"
        assert found(capacity_min=15) == {"a"}
        assert found(capacity_min=6, capacity_max=6) == {"b"}
        assert found(frames=["Full size"]) == {"a"}
        assert found(frames=["Full size", "Subcompact"]) == {"a", "b"}

    def test_a_saved_search_keeps_them_and_refuses_a_size_it_does_not_know(self):
        query = search.parse_query("frame=Compact&frame=K-frame&capacity_min=15")
        assert "capacity_min=15" in query.as_query_string()
        with pytest.raises(search.BadQuery):
            search.parse_query("frame=Enormous")

    def test_the_api(self, glocks, client, admin_headers):
        session, model, site = glocks
        listing(session, model, site, "a", "Glock 17 FS | 17rd Pistol")
        page = client.get(
            "/api/items", params={"capacity_min": 17, "availability": "all"}, headers=admin_headers
        ).json()
        assert [row["capacity"] for row in page["items"]] == [17]
        assert {f["value"] for f in page["facets"]["frames"]} == {"Full size"}
        refused = client.get("/api/items", params={"frame": "Huge"}, headers=admin_headers)
        assert refused.status_code == 400


class TestTheArmory:
    def test_typed_on_the_model_and_its_listings_follow(self, glocks, client, admin_headers):
        session, model, site = glocks
        item = listing(session, model, site, "a", "Glock 17 PRE OWNED")
        assert item.capacity is None
        response = client.patch(
            f"/api/armory/models/{model.id}", json={"capacity": 17}, headers=admin_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["model"]["capacity"] == 17
        session.expire_all()
        assert session.get(Item, item.id).capacity == 17
        refused = client.patch(
            f"/api/armory/models/{model.id}", json={"capacity": 500}, headers=admin_headers
        )
        assert refused.status_code == 422
