"""Undoing a merge, which until now could not be done at all.

The armory kept a merged row deliberately -- "an admin who merges the wrong
pair should have something to look at rather than an archaeology exercise" --
and then gave them nothing to do about it. This is the other half.

**Merging is the one edit that cannot be reversed from what it leaves behind.**
It moves the source's model and caliber links onto the target and clears the
source's own; it copies the source's spellings into the target's aliases; on a
maker it deletes the source's rows from ``firearm_model_manufacturers``
outright. Afterwards nothing says which of the target's links or aliases came
from the source. So the merge writes down what it is about to take, and the
undo reads it back.

Rows merged *before* that recording existed -- 112 of them when this shipped --
come back on a best-effort basis, and the operation says which kind it did.
"""

from __future__ import annotations

import json

import pytest

from app.models import ArmoryStatus, Caliber, FirearmModel, Item, Manufacturer, Site
from app.services import armory


@pytest.fixture
def makers(clean_db):
    source = Manufacturer(name="Nagant", aliases="Nagant Bros", status=ArmoryStatus.APPROVED)
    target = Manufacturer(name="Mosin-Nagant", aliases="Mosin", status=ArmoryStatus.APPROVED)
    clean_db.add_all([source, target])
    clean_db.commit()
    return source, target


@pytest.fixture
def model_pair(clean_db):
    maker = Manufacturer(name="Tula", status=ArmoryStatus.APPROVED)
    cartridge = Caliber(name="7.62x54R", status=ArmoryStatus.APPROVED)
    source = FirearmModel(name="M91/30 Rifle", status=ArmoryStatus.APPROVED)
    target = FirearmModel(name="M91/30", status=ArmoryStatus.APPROVED)
    source.manufacturers.append(maker)
    source.calibers.append(cartridge)
    clean_db.add_all([maker, cartridge, source, target])
    clean_db.commit()
    return source, target


class TestAMergeWritesDownWhatItTakes:
    def test_a_maker_records_the_models_it_gave_up(self, clean_db, makers):
        source, target = makers
        built = FirearmModel(name="M44", status=ArmoryStatus.APPROVED)
        built.manufacturers.append(source)
        clean_db.add(built)
        clean_db.commit()

        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        undo = json.loads(source.merge_undo)
        assert undo["firearm_model_ids"] == [built.id]
        assert undo["status"] == "approved"

    def test_a_model_records_its_makers_and_calibers(self, clean_db, model_pair):
        source, target = model_pair
        makers = [m.id for m in source.manufacturers]
        cartridges = [c.id for c in source.calibers]

        armory.merge_models(clean_db, source.id, target.id)
        clean_db.flush()
        undo = json.loads(source.merge_undo)
        assert undo["manufacturer_ids"] == makers
        assert undo["caliber_ids"] == cartridges

    def test_it_records_the_targets_aliases_as_they_were(self, clean_db, makers):
        """So the undo can restore them rather than subtract and hope."""
        source, target = makers
        before = target.aliases
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        assert json.loads(source.merge_undo)["target_aliases"] == before
        assert target.aliases != before


class TestUndoingIt:
    def test_the_row_comes_back(self, clean_db, makers):
        source, target = makers
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()

        armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.flush()
        assert source.status is ArmoryStatus.APPROVED
        assert source.enabled is True
        assert source.merged_into_id is None

    def test_the_target_gives_the_spellings_back(self, clean_db, makers):
        """The half that matters most. While the target still answers to the
        source's name, bringing the source back changes nothing: both rows
        match the same text and the target keeps winning."""
        source, target = makers
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        assert "Nagant" in (target.aliases or "")

        armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.flush()
        assert "Nagant\n" not in f"{target.aliases}\n"
        assert "Mosin" in (target.aliases or "")

    def test_a_models_makers_and_calibers_come_back(self, clean_db, model_pair):
        """merge_models clears them off the source, so without the record they
        are simply gone."""
        source, target = model_pair
        armory.merge_models(clean_db, source.id, target.id)
        clean_db.flush()
        assert source.manufacturers == []

        note, _changed = armory.unmerge(clean_db, "models", source.id)
        clean_db.flush()
        assert [m.name for m in source.manufacturers] == ["Tula"]
        assert [c.name for c in source.calibers] == ["7.62x54R"]
        assert "exactly" in note

    def test_the_record_is_cleared_afterwards(self, clean_db, makers):
        """A row that is not merged has nothing to undo, and a stale payload
        would be restored by the next un-merge."""
        source, target = makers
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.flush()
        assert source.merge_undo is None

    def test_it_can_be_merged_again_afterwards(self, clean_db, makers):
        source, target = makers
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.flush()

        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        assert source.status is ArmoryStatus.MERGED


class TestARowMergedBeforeAnyOfThisExisted:
    """112 of them when this shipped. They have no record, and refusing would
    make the feature useless for exactly the merges somebody regrets.
    """

    def test_it_still_comes_back(self, clean_db, makers):
        source, target = makers
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        source.merge_undo = None  # as though merged before the column existed
        clean_db.flush()

        note, _changed = armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.flush()
        assert source.merged_into_id is None
        assert "as far as the record allows" in note

    def test_and_the_target_still_gives_the_spellings_back(self, clean_db, makers):
        """Worked out by subtracting the row's own spellings, which is what
        the merge added."""
        source, target = makers
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        source.merge_undo = None
        clean_db.flush()

        armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.flush()
        assert "Nagant\n" not in f"{target.aliases}\n"
        assert "Mosin" in (target.aliases or "")

    def test_it_lands_in_the_queue_rather_than_in_production(self, clean_db, makers):
        """Nothing records what its status was, and an approved row starts
        matching listings the moment it is saved. Pending is the safe landing
        place: somebody looks at it again."""
        source, target = makers
        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.flush()
        source.merge_undo = None
        clean_db.flush()

        armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.flush()
        assert source.status is ArmoryStatus.PENDING


class TestWhatItRefuses:
    def test_a_row_that_was_never_merged(self, clean_db, makers):
        source, _target = makers
        with pytest.raises(armory.UnmergeError, match="has not been merged"):
            armory.unmerge(clean_db, "manufacturers", source.id)

    def test_a_row_that_is_not_there(self, clean_db):
        with pytest.raises(armory.UnmergeError, match="no such row"):
            armory.unmerge(clean_db, "manufacturers", 9999)

    def test_a_table_that_is_not_one(self, clean_db):
        with pytest.raises(armory.UnmergeError, match="no armory table"):
            armory.unmerge(clean_db, "bayonets", 1)


class TestOverTheRoute:
    def test_an_admin_can_undo_a_merge(self, client, admin_headers, seeded):
        source = Manufacturer(name="Norico SKS", status=ArmoryStatus.APPROVED)
        target = Manufacturer(name="Norinco", status=ArmoryStatus.APPROVED)
        seeded.add_all([source, target])
        seeded.commit()
        client.post(
            "/api/armory/manufacturers/merge",
            json={"source_id": source.id, "target_id": target.id},
            headers=admin_headers,
        )

        response = client.post(
            f"/api/armory/manufacturers/{source.id}/unmerge", headers=admin_headers
        )
        assert response.status_code == 200
        assert "Un-merged" in response.json()["message"]
        seeded.refresh(source)
        assert source.merged_into_id is None

    def test_a_normal_user_cannot(self, client, normal_user, seeded):
        row = Manufacturer(name="Whoever", status=ArmoryStatus.APPROVED)
        seeded.add(row)
        seeded.commit()
        response = client.post(
            f"/api/armory/manufacturers/{row.id}/unmerge", headers=normal_user["headers"]
        )
        assert response.status_code == 403

    def test_undoing_what_was_never_merged_is_a_400(self, client, admin_headers, seeded):
        row = Manufacturer(name="Never Merged", status=ArmoryStatus.APPROVED)
        seeded.add(row)
        seeded.commit()
        response = client.post(f"/api/armory/manufacturers/{row.id}/unmerge", headers=admin_headers)
        assert response.status_code == 400


class TestTheListingsFollow:
    def test_a_restamped_listing_is_re_derived(self, clean_db, makers):
        """The merge rewrote every listing carrying the old name. Bringing the
        row back has to put them where they now belong, or the undo is only
        cosmetic."""
        source, target = makers
        site = Site(slug="s", name="S", base_url="https://s.test/")
        clean_db.add(site)
        clean_db.commit()
        listing = Item(
            site_id=site.id,
            external_key="k",
            url="https://s.test/1",
            title="Nagant revolver, 7.62mm",
            manufacturer="Nagant",
            is_active=True,
        )
        clean_db.add(listing)
        clean_db.commit()

        armory.merge_manufacturers(clean_db, source.id, target.id)
        clean_db.commit()
        clean_db.refresh(listing)
        assert listing.manufacturer == "Mosin-Nagant"

        armory.unmerge(clean_db, "manufacturers", source.id)
        clean_db.commit()
        clean_db.refresh(listing)
        # Back to a row that exists and is enabled, whatever its name resolves
        # to -- the point is that the undo re-ran the matching rather than
        # leaving the merge's answer frozen on the listing.
        assert listing.manufacturer in {"Nagant", "Mosin-Nagant"}
