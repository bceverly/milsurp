"""Promoting one of a row's own spellings to be its name.

"IWI" and "Israel Weapon Industries" are the same firm, and which of them is
the *name* decides what gets written onto every listing the row matches. Doing
that by hand is two edits that have to happen together -- rename the row, then
swap the alias -- and between them the row either claims one spelling twice or
has stopped recognizing the other. This is the one-step version.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, Caliber, FirearmModel, Item, Manufacturer, Site
from app.services import armory


@pytest.fixture
def site(clean_db):
    row = Site(slug="primary", name="Primary", base_url="https://example.test/")
    clean_db.add(row)
    clean_db.commit()
    return row


@pytest.fixture
def maker(clean_db):
    row = Manufacturer(
        name="IWI",
        aliases="Israel Weapon Industries\nIMI",
        status=ArmoryStatus.APPROVED,
        country="Israel",
    )
    clean_db.add(row)
    clean_db.commit()
    armory.invalidate()
    yield row
    armory.invalidate()


def _item(session, site, **kwargs) -> Item:
    item = Item(
        site_id=site.id,
        external_key=f"k-{kwargs.get('title', 'x')}",
        url="https://example.test/x",
        title=kwargs.pop("title", "A rifle"),
        **kwargs,
    )
    session.add(item)
    session.flush()
    return item


class TestPromotingASpelling:
    def test_the_chosen_spelling_becomes_the_name(self, clean_db, maker):
        armory.set_primary(clean_db, Manufacturer, maker.id, "Israel Weapon Industries")
        assert maker.name == "Israel Weapon Industries"

    def test_the_old_name_is_kept_as_an_alias(self, clean_db, maker):
        """The important half. The old name is what dealers wrote and what the
        row was recognizing listings by; dropping it would silently stop
        matching the very text the row exists for."""
        armory.set_primary(clean_db, Manufacturer, maker.id, "Israel Weapon Industries")
        assert "IWI" in maker.spellings
        assert maker.spellings[0] == "Israel Weapon Industries"

    def test_the_other_aliases_survive(self, clean_db, maker):
        armory.set_primary(clean_db, Manufacturer, maker.id, "Israel Weapon Industries")
        assert "IMI" in maker.spellings

    def test_no_spelling_is_claimed_twice(self, clean_db, maker):
        armory.set_primary(clean_db, Manufacturer, maker.id, "IMI")
        lowered = [s.lower() for s in maker.spellings]
        assert len(lowered) == len(set(lowered))

    def test_listings_carrying_the_old_name_are_restamped(self, clean_db, site, maker):
        """Or the browse filter offers both spellings as separate firms, which
        is the same split the armory exists to prevent."""
        first = _item(clean_db, site, title="An IWI Tavor", manufacturer="IWI")
        second = _item(clean_db, site, title="Another IWI", manufacturer="IWI")
        other = _item(clean_db, site, title="A Glock", manufacturer="Glock")
        clean_db.commit()

        moved = armory.set_primary(clean_db, Manufacturer, maker.id, "Israel Weapon Industries")
        clean_db.commit()

        assert moved == 2
        assert first.manufacturer == "Israel Weapon Industries"
        assert second.manufacturer == "Israel Weapon Industries"
        assert other.manufacturer == "Glock"

    def test_the_row_still_matches_what_it_used_to(self, clean_db, maker):
        """The whole point of keeping the old name: a title saying "IWI" still
        finds this firm, and now answers with the fuller spelling."""
        from app.services import manufacturers

        armory.set_primary(clean_db, Manufacturer, maker.id, "Israel Weapon Industries")
        clean_db.commit()
        manufacturers.invalidate()

        assert manufacturers.extract(clean_db, "LEO IWI Zion Z15 rifle") == (
            "Israel Weapon Industries"
        )

    def test_choosing_the_name_it_already_has_does_nothing(self, clean_db, maker):
        before = maker.spellings
        assert armory.set_primary(clean_db, Manufacturer, maker.id, "IWI") == 0
        assert maker.spellings == before

    def test_it_is_case_insensitive_about_which_one_you_picked(self, clean_db, maker):
        armory.set_primary(clean_db, Manufacturer, maker.id, "israel weapon industries")
        # ...and keeps the row's own capitalization, not the caller's.
        assert maker.name == "Israel Weapon Industries"


class TestWhatItRefuses:
    def test_a_spelling_the_row_does_not_have(self, clean_db, maker):
        """Inventing a name here would be a rename in disguise, and a rename
        has to go through the duplicate check that stops two rows claiming one
        string."""
        with pytest.raises(armory.PrimaryNameError, match="not one of this row's spellings"):
            armory.set_primary(clean_db, Manufacturer, maker.id, "Israel Military Industries")

    def test_a_blank(self, clean_db, maker):
        with pytest.raises(armory.PrimaryNameError):
            armory.set_primary(clean_db, Manufacturer, maker.id, "   ")

    def test_a_row_that_is_not_there(self, clean_db):
        with pytest.raises(armory.PrimaryNameError):
            armory.set_primary(clean_db, Manufacturer, 9999, "Anything")


class TestTheOtherTwoTables:
    def test_a_caliber_restamps_its_listings(self, clean_db, site):
        row = Caliber(name="7.65 Parabellum", aliases=".30 Luger", status=ArmoryStatus.APPROVED)
        clean_db.add(row)
        clean_db.commit()
        item = _item(clean_db, site, title="A Luger", caliber="7.65 Parabellum")
        clean_db.commit()

        moved = armory.set_primary(clean_db, Caliber, row.id, ".30 Luger")
        clean_db.commit()

        assert (moved, row.name, item.caliber) == (1, ".30 Luger", ".30 Luger")
        assert "7.65 Parabellum" in row.spellings

    def test_a_model_has_nothing_to_restamp(self, clean_db, site):
        """A listing points at a model by id, not by name -- which is exactly
        why renaming a model was always safe and renaming the other two was
        not. See services/search.py, where the model filter is by id."""
        row = FirearmModel(
            name="Mosin-Nagant M91/30", aliases="M91/30", status=ArmoryStatus.APPROVED
        )
        clean_db.add(row)
        clean_db.commit()
        item = _item(clean_db, site, title="A Mosin", firearm_model_id=row.id)
        clean_db.commit()

        assert armory.set_primary(clean_db, FirearmModel, row.id, "M91/30") == 0
        assert row.name == "M91/30"
        assert item.firearm_model_id == row.id


class TestTheEndpoint:
    def _maker(self, client, admin_headers):
        return client.post(
            "/api/manufacturers",
            json={"name": "IWI", "aliases": "Israel Weapon Industries"},
            headers=admin_headers,
        ).json()["manufacturer"]

    def test_it_promotes(self, client, admin_headers, clean_db):
        row = self._maker(client, admin_headers)
        response = client.post(
            f"/api/armory/manufacturers/{row['id']}/primary",
            json={"name": "Israel Weapon Industries"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert "primary name" in response.json()["message"]

        listed = client.get("/api/manufacturers", headers=admin_headers).json()
        found = next(m for m in listed if m["id"] == row["id"])
        assert found["name"] == "Israel Weapon Industries"
        assert "IWI" in (found["aliases"] or "")

    def test_a_spelling_the_row_does_not_have_is_a_400(self, client, admin_headers, clean_db):
        row = self._maker(client, admin_headers)
        response = client.post(
            f"/api/armory/manufacturers/{row['id']}/primary",
            json={"name": "Something Else Entirely"},
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_an_unknown_table_is_a_404(self, client, admin_headers):
        assert (
            client.post(
                "/api/armory/sites/1/primary", json={"name": "x"}, headers=admin_headers
            ).status_code
            == 404
        )

    def test_a_normal_user_cannot(self, client, normal_user, admin_headers):
        row = self._maker(client, admin_headers)
        assert (
            client.post(
                f"/api/armory/manufacturers/{row['id']}/primary",
                json={"name": "Israel Weapon Industries"},
                headers=normal_user["headers"],
            ).status_code
            == 403
        )


class TestWhenTheAliasIsAlsoARow:
    """The common case, not the edge case.

    Aliases mostly arrive by *merging*: folding "7.62x51 NATO" into
    ".308 Winchester" moves its spelling onto the target and leaves the source
    behind as a tombstone pointing at it. Five of that row's nine aliases are
    merged rows of their own. So the spelling being promoted very often still
    belongs to another row, and taking the name without dealing with that
    violates the unique index -- which reached the page as HTTP 500 in the
    middle of a rename.
    """

    @pytest.fixture
    def merged_pair(self, clean_db):
        target = Caliber(name=".308 Winchester", status=ArmoryStatus.APPROVED)
        source = Caliber(name="7.62x51 NATO", status=ArmoryStatus.APPROVED)
        clean_db.add_all([target, source])
        clean_db.commit()
        armory.merge_calibers(clean_db, source.id, target.id)
        clean_db.commit()
        return target, source

    def test_the_two_rows_swap_names(self, clean_db, merged_pair):
        target, source = merged_pair
        assert "7.62x51 NATO" in target.spellings

        armory.set_primary(clean_db, Caliber, target.id, "7.62x51 NATO")
        clean_db.commit()

        assert target.name == "7.62x51 NATO"
        assert source.name == ".308 Winchester"

    def test_the_tombstone_survives_and_still_points_here(self, clean_db, merged_pair):
        """It is the record that these two spellings were ever unified, and
        afterwards it reads "the old name was merged into the new one" -- which
        is what happened, told in the naming that now applies."""
        target, source = merged_pair
        armory.set_primary(clean_db, Caliber, target.id, "7.62x51 NATO")
        clean_db.commit()

        assert source.status is ArmoryStatus.MERGED
        assert source.merged_into_id == target.id

    def test_the_old_name_is_still_a_spelling_of_the_live_row(self, clean_db, merged_pair):
        target, _ = merged_pair
        armory.set_primary(clean_db, Caliber, target.id, "7.62x51 NATO")
        clean_db.commit()
        assert ".308 Winchester" in target.spellings

    def test_listings_are_restamped_across_the_swap(self, clean_db, site, merged_pair):
        target, _ = merged_pair
        item = _item(clean_db, site, title="A rifle", caliber=".308 Winchester")
        clean_db.commit()

        moved = armory.set_primary(clean_db, Caliber, target.id, "7.62x51 NATO")
        clean_db.commit()

        assert (moved, item.caliber) == (1, "7.62x51 NATO")

    def test_an_unrelated_row_with_that_name_is_refused(self, clean_db):
        """Two *live* rows cannot swap names -- that is a merge, and it is a
        different decision with different consequences."""
        row = Caliber(name="9mm Luger", aliases="9x19mm", status=ArmoryStatus.APPROVED)
        other = Caliber(name="9x19mm", status=ArmoryStatus.APPROVED)
        clean_db.add_all([row, other])
        clean_db.commit()

        with pytest.raises(armory.PrimaryNameError, match="also a row of its own"):
            armory.set_primary(clean_db, Caliber, row.id, "9x19mm")

    def test_the_endpoint_reports_it_as_a_400_not_a_500(self, client, admin_headers, clean_db):
        row = Caliber(name="9mm Luger", aliases="9x19mm", status=ArmoryStatus.APPROVED)
        clean_db.add_all([row, Caliber(name="9x19mm", status=ArmoryStatus.APPROVED)])
        clean_db.commit()

        response = client.post(
            f"/api/armory/calibers/{row.id}/primary",
            json={"name": "9x19mm"},
            headers=admin_headers,
        )
        assert response.status_code == 400
        assert "also a row of its own" in response.json()["detail"]
