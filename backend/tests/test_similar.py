"""Other listings worth looking at, and the order they are offered in.

The price spectrum stops one step short: it says "cheaper than 8% of them" and
gives no way to reach the them, so a reader told their rifle is dear has to
retype the model into the search box. This is that step, and the thing worth
pinning is the *grading* — one list where every row can say why it is there.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmKind, FirearmModel, Item, Site
from app.services import similar


@pytest.fixture
def shelf(clean_db):
    sites = [Site(slug=f"s{n}", name=f"Shop {n}", base_url=f"https://s{n}.test/") for n in range(3)]
    clean_db.add_all(sites)
    k98 = FirearmModel(name="Karabiner 98k", kind=FirearmKind.RIFLE, status=ArmoryStatus.APPROVED)
    vz24 = FirearmModel(name="VZ-24", kind=FirearmKind.RIFLE, status=ArmoryStatus.APPROVED)
    clean_db.add_all([k98, vz24])
    clean_db.flush()
    return sites, k98, vz24


def _item(
    session,
    site,
    *,
    title,
    model=None,
    caliber=None,
    country=None,
    price=None,
    rifle=True,
    pistol=False,
    active=True,
):
    row = Item(
        site_id=site.id,
        external_key=title,
        url=f"https://e.test/{title}",
        title=title,
        firearm_model_id=model.id if model else None,
        caliber=caliber,
        country=country,
        current_price=price,
        is_rifle=rifle,
        is_pistol=pistol,
        is_active=active,
    )
    session.add(row)
    session.flush()
    return row


class TestTheOrderTheyComeIn:
    def test_the_same_gun_first_and_cheapest_first(self, clean_db, shelf):
        """The question somebody actually has on a detail page is "can I get
        this cheaper", so the same gun leads and price orders it."""
        sites, k98, _vz = shelf
        mine = _item(
            clean_db,
            sites[0],
            title="K98k mine",
            model=k98,
            caliber="8mm Mauser",
            country="Germany",
            price=900,
        )
        _item(clean_db, sites[1], title="K98k dear", model=k98, caliber="8mm Mauser", price=1200)
        _item(clean_db, sites[2], title="K98k cheap", model=k98, caliber="8mm Mauser", price=700)
        clean_db.commit()

        found = similar.find(clean_db, mine)
        assert [f.item.title for f in found[:2]] == ["K98k cheap", "K98k dear"]
        assert {f.rung.key for f in found[:2]} == {"same_gun"}

    def test_then_the_same_model_in_another_cartridge(self, clean_db, shelf):
        sites, k98, _vz = shelf
        mine = _item(
            clean_db,
            sites[0],
            title="K98k mine",
            model=k98,
            caliber="8mm Mauser",
            country="Germany",
            price=900,
        )
        _item(
            clean_db,
            sites[1],
            title="K98k in .308",
            model=k98,
            caliber=".308 Winchester",
            price=800,
        )
        clean_db.commit()

        found = similar.find(clean_db, mine)
        assert [(f.item.title, f.rung.key) for f in found] == [("K98k in .308", "same_model")]

    def test_then_the_same_cartridge_from_the_same_country(self, clean_db, shelf):
        sites, k98, vz = shelf
        mine = _item(
            clean_db,
            sites[0],
            title="K98k mine",
            model=k98,
            caliber="8mm Mauser",
            country="Germany",
            price=900,
        )
        _item(
            clean_db,
            sites[1],
            title="VZ-24 German",
            model=vz,
            caliber="8mm Mauser",
            country="Germany",
            price=600,
        )
        _item(
            clean_db,
            sites[2],
            title="M48 Yugo",
            model=vz,
            caliber="8mm Mauser",
            country="Yugoslavia",
            price=500,
        )
        clean_db.commit()

        found = similar.find(clean_db, mine)
        assert [(f.item.title, f.rung.key) for f in found] == [
            ("VZ-24 German", "same_round_and_place"),
            ("M48 Yugo", "same_round"),
        ]

    def test_a_listing_appears_once_on_its_closest_rung(self, clean_db, shelf):
        """The same rifle at another vendor must not come back further down as
        "same cartridge" -- the list would read as two recommendations."""
        sites, k98, _vz = shelf
        mine = _item(
            clean_db,
            sites[0],
            title="K98k mine",
            model=k98,
            caliber="8mm Mauser",
            country="Germany",
            price=900,
        )
        _item(
            clean_db,
            sites[1],
            title="K98k other",
            model=k98,
            caliber="8mm Mauser",
            country="Germany",
            price=700,
        )
        clean_db.commit()

        found = similar.find(clean_db, mine)
        assert [f.item.title for f in found] == ["K98k other"]


class TestWhatItRefuses:
    def test_a_listing_with_nothing_stated(self, clean_db, shelf):
        """No model and no cartridge is nothing to be similar to. Filling the
        space with whatever shares a vendor would be noise dressed as advice."""
        sites, _k98, _vz = shelf
        mine = _item(clean_db, sites[0], title="Unknown rifle", price=400)
        _item(clean_db, sites[1], title="Another rifle", caliber="8mm Mauser", price=300)
        clean_db.commit()

        assert similar.find(clean_db, mine) == []

    def test_an_accessory(self, clean_db, shelf):
        """A bayonet that fits an 8mm Mauser is not an alternative to the
        rifle, and the cartridge on it is the rifle's anyway -- see
        armory.fill_in."""
        sites, k98, _vz = shelf
        mine = _item(
            clean_db,
            sites[0],
            title="K98k bayonet",
            model=k98,
            caliber="8mm Mauser",
            price=80,
            rifle=False,
            pistol=False,
        )
        _item(clean_db, sites[1], title="K98k rifle", model=k98, caliber="8mm Mauser", price=900)
        clean_db.commit()

        assert similar.find(clean_db, mine) == []

    def test_a_pistol_is_never_offered_beside_a_rifle(self, clean_db, shelf):
        sites, _k98, _vz = shelf
        mine = _item(
            clean_db, sites[0], title="A rifle in 7.62", caliber="7.62x25mm Tokarev", price=500
        )
        _item(
            clean_db,
            sites[1],
            title="A pistol in 7.62",
            caliber="7.62x25mm Tokarev",
            price=300,
            rifle=False,
            pistol=True,
        )
        clean_db.commit()

        assert similar.find(clean_db, mine) == []

    def test_a_de_listed_one(self, clean_db, shelf):
        sites, k98, _vz = shelf
        mine = _item(
            clean_db, sites[0], title="K98k mine", model=k98, caliber="8mm Mauser", price=900
        )
        _item(
            clean_db,
            sites[1],
            title="K98k gone",
            model=k98,
            caliber="8mm Mauser",
            price=100,
            active=False,
        )
        clean_db.commit()

        assert similar.find(clean_db, mine) == []

    def test_and_itself(self, clean_db, shelf):
        sites, k98, _vz = shelf
        mine = _item(
            clean_db, sites[0], title="K98k mine", model=k98, caliber="8mm Mauser", price=900
        )
        clean_db.commit()

        assert similar.find(clean_db, mine) == []


class TestRoomIsKeptForTheWiderBands:
    """46% of active firearms sit in a model-and-cartridge group of nine or
    more, so without this the list is *entirely* the same gun on nearly half
    the catalog -- useful, and not the only thing worth saying.
    """

    def test_the_closest_band_gives_up_its_last_slots(self, clean_db, shelf):
        sites, k98, vz = shelf
        mine = _item(
            clean_db,
            sites[0],
            title="K98k mine",
            model=k98,
            caliber="8mm Mauser",
            country="Germany",
            price=900,
        )
        for n in range(12):
            _item(
                clean_db,
                sites[1],
                title=f"K98k #{n}",
                model=k98,
                caliber="8mm Mauser",
                country="Germany",
                price=100 + n,
            )
        _item(
            clean_db,
            sites[2],
            title="VZ-24",
            model=vz,
            caliber="8mm Mauser",
            country="Germany",
            price=600,
        )
        clean_db.commit()

        found = similar.find(clean_db, mine, limit=8)
        assert len(found) == 8
        assert sum(1 for f in found if f.rung.key == "same_gun") == 7
        assert found[-1].item.title == "VZ-24"

    def test_but_not_when_nothing_wider_exists(self, clean_db, shelf):
        """A gun nothing else resembles still gets a full list."""
        sites, k98, _vz = shelf
        mine = _item(
            clean_db,
            sites[0],
            title="K98k mine",
            model=k98,
            caliber="8mm Mauser",
            country="Germany",
            price=900,
        )
        for n in range(12):
            _item(
                clean_db,
                sites[1],
                title=f"K98k #{n}",
                model=k98,
                caliber="8mm Mauser",
                country="Germany",
                price=100 + n,
            )
        clean_db.commit()

        found = similar.find(clean_db, mine, limit=8)
        assert len(found) == 8
        assert all(f.rung.key == "same_gun" for f in found)
