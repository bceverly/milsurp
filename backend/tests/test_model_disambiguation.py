"""Two models with the same designation, told apart by who built them.

A designation is not unique, and the armory already knew it: `_contradicted`
exists because "Model 1917" is a Colt revolver and an Enfield rifle, and it
settles that pair by asking what *kind* the listing says it is.

What it cannot settle is two rows of the *same* kind. A Mauser Model 1910 and
an FN Model 1910 are both pocket pistols, so the kind test passes on both and
whichever sorts first wins -- taking its caliber, its country and its maker
with it. This is the second discriminator, and it asks the other question a
title can answer: which firm.

Measured when it was written, 219 approved rows are named by nothing but a
bare designation -- "Model 1910", "Type 53", "Model 1" -- and exactly three
spellings were claimed twice, all three being one gun under two names. So the
guard fires on nothing in today's catalog. It is built for the collision that
219 bare designations and a discovery queue make inevitable.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmKind, FirearmModel, Manufacturer
from app.services import armory, manufacturers


@pytest.fixture
def rival_tens(clean_db):
    """Two pocket pistols, both "Model 1910", built by different firms.

    Same kind on purpose: a fixture where the kinds differ would pass on
    `_contradicted` alone and prove nothing about this rule.
    """
    mauser = Manufacturer(name="Mauser", status=ArmoryStatus.APPROVED, country="Germany")
    fn = Manufacturer(name="Fabrique Nationale", aliases="FN", status=ArmoryStatus.APPROVED)
    clean_db.add_all([mauser, fn])
    clean_db.flush()

    theirs = FirearmModel(
        name="Mauser Model 1910",
        aliases="Model 1910",
        kind=FirearmKind.PISTOL,
        country="Germany",
        status=ArmoryStatus.APPROVED,
        manufacturers=[mauser],
    )
    belgian = FirearmModel(
        name="FN Model 1910",
        aliases="Model 1910",
        kind=FirearmKind.PISTOL,
        country="Belgium",
        status=ArmoryStatus.APPROVED,
        manufacturers=[fn],
    )
    clean_db.add_all([theirs, belgian])
    clean_db.commit()
    armory.invalidate()
    manufacturers.invalidate()
    yield theirs, belgian
    armory.invalidate()
    manufacturers.invalidate()


class TestTheMakerInTheTitleDecides:
    def test_the_german_one(self, clean_db, rival_tens):
        german, _belgian = rival_tens
        found = armory.match(clean_db, "Mauser Model 1910 7.65mm Pocket Pistol")
        assert found.model_id == german.id
        assert found.country == "Germany"

    def test_and_the_belgian_one(self, clean_db, rival_tens):
        _german, belgian = rival_tens
        found = armory.match(clean_db, "FN Model 1910 .380 Browning")
        assert found.model_id == belgian.id
        assert found.country == "Belgium"

    def test_an_alias_of_the_maker_counts_too(self, clean_db, rival_tens):
        """ "FN" is an alias of Fabrique Nationale, and the guard is built from
        every spelling of a firm rather than its canonical name."""
        _german, belgian = rival_tens
        found = armory.match(clean_db, "Fabrique Nationale Model 1910 Pistol")
        assert found.model_id == belgian.id


class TestWhenTheTitleCannotSay:
    def test_a_bare_designation_still_matches_something(self, clean_db, rival_tens):
        """Naming no maker is not evidence against either row, so the ordinary
        order decides and the listing still gets a model. Refusing to answer
        would be a regression: a bare "Model 1910" is better served by one of
        two plausible rows than by nothing."""
        found = armory.match(clean_db, "Model 1910 Pocket Pistol .32 ACP")
        assert found.model_id in {row.id for row in rival_tens}

    @pytest.mark.parametrize(
        ("title", "winner"),
        [
            ("FN Model 1910 in 7.65mm Mauser trim", "belgian"),
            ("Mauser Model 1910 in .380 FN Browning", "german"),
        ],
    )
    def test_the_maker_standing_next_to_it_wins(self, clean_db, rival_tens, title, winner):
        """Both names appear, and only distance separates them.

        This is the Astra case and its mirror. "Astra Model 900 7.63x25mm
        Mauser" is an Astra, because the maker registry reads Mauser out of the
        *cartridge* -- and the same sentence shape occurs with the firms the
        other way round. A rule that asked only *whether* each name appears
        cannot tell these apart: each title names a rival and its own, so
        neither row is vetoed and whichever sorts first takes both. Half the
        answers would be wrong, and the wrong half is silent.
        """
        german, belgian = rival_tens
        expected = german if winner == "german" else belgian
        assert armory.match(clean_db, title).model_id == expected.id


class TestItStaysOutOfTheWayOtherwise:
    def test_a_designation_nobody_contests_gets_no_guard(self, clean_db):
        """The restraint that makes this safe to ship. A row nobody competes
        with carries no maker patterns at all, so the veto cannot fire on it --
        which matters because a maker named in a title is a noisy signal: it
        may be a cartridge, and a model row may simply not list the firm that
        built it yet.
        """
        clean_db.add(
            FirearmModel(
                name="Karabiner 98k",
                aliases="K98k",
                kind=FirearmKind.RIFLE,
                status=ArmoryStatus.APPROVED,
            )
        )
        clean_db.commit()
        armory.invalidate()

        rules = armory.model_registry(clean_db).rules
        assert len(rules) == 1
        assert rules[0].rivals is None
        assert armory.match(clean_db, "Russian Capture K98k 8mm").model == "Karabiner 98k"

    def test_two_rows_sharing_a_maker_are_not_rivals(self, clean_db):
        """A firm on both rows tells them apart not at all, so it is removed
        from the rival set -- and with nothing left, no guard is built. This is
        the shape of the three collisions the live catalog actually had: one
        gun under two names, both pointing at the same firm.
        """
        firm = Manufacturer(name="Izhevsk", status=ArmoryStatus.APPROVED)
        clean_db.add(firm)
        clean_db.flush()
        for name in ("M44", "Mosin-Nagant M44"):
            clean_db.add(
                FirearmModel(
                    name=name,
                    aliases="M44",
                    kind=FirearmKind.CARBINE,
                    status=ArmoryStatus.APPROVED,
                    manufacturers=[firm],
                )
            )
        clean_db.commit()
        armory.invalidate()

        assert all(rule.rivals is None for rule in armory.model_registry(clean_db).rules)
