"""Making a bare designation say who built it: "M44" -> "Mosin-Nagant M44".

399 of 892 approved rows were named by nothing but a designation, and the
trouble with all of them is the same: "Model 1910" is a Mauser, an FN and a
Winchester, so the name settles nothing — not on the page, where a curator is
deciding whether the row is worth keeping, and not in a match, where two rows
claiming one spelling are told apart by kind and by maker and by nothing else.

The safety argument is that **nothing here is inferred**. The firm is already
on the row and already vouched for; this only moves it into the name.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmKind, FirearmModel, Manufacturer
from app.services import armory
from app.services.classify import extract_country


@pytest.fixture
def firm(clean_db):
    row = Manufacturer(name="Ruger", status=ArmoryStatus.APPROVED)
    clean_db.add(row)
    clean_db.flush()
    return row


def _model(session, name, *, makers=(), status=ArmoryStatus.APPROVED, aliases=None):
    row = FirearmModel(
        name=name,
        aliases=aliases,
        kind=FirearmKind.RIFLE,
        status=status,
        manufacturers=list(makers),
    )
    session.add(row)
    session.commit()
    armory.invalidate()
    return row


class TestWhatGetsRenamed:
    def test_a_bare_designation_with_one_maker(self, clean_db, firm):
        _model(clean_db, "10/22", makers=[firm])
        assert [(r.was, r.now) for r in armory.plan_qualify(clean_db)] == [("10/22", "Ruger 10/22")]

    @pytest.mark.parametrize(
        "name", ["M44", "Model 1910", "Type 53", "Mle 1874", "06/24", "M1935S", "Model 62A"]
    )
    def test_the_shapes_a_designation_comes_in(self, clean_db, firm, name):
        _model(clean_db, name, makers=[firm])
        assert len(armory.plan_qualify(clean_db)) == 1

    @pytest.mark.parametrize("name", ["Karabiner 98k", "M1 Carbine", "Luger P08", "AR-15"])
    def test_but_a_name_that_already_says_something_is_left_alone(self, clean_db, firm, name):
        _model(clean_db, name, makers=[firm])
        assert armory.plan_qualify(clean_db) == []


class TestWhatIsRefused:
    def test_a_row_with_several_makers(self, clean_db):
        """Nine firms built the M1 Carbine. "Inland M1 Carbine" would be a lie
        about the other eight, so picking one is not on offer."""
        makers = [Manufacturer(name=n, status=ArmoryStatus.APPROVED) for n in ("Inland", "IBM")]
        clean_db.add_all(makers)
        clean_db.flush()
        _model(clean_db, "M1", makers=makers)
        assert armory.plan_qualify(clean_db) == []

    def test_a_row_with_none(self, clean_db):
        _model(clean_db, "Model 1910")
        assert armory.plan_qualify(clean_db) == []

    def test_a_row_nobody_has_vouched_for(self, clean_db, firm):
        """Discovery proposes bare designations on every scan. Renaming rows in
        the pending queue would churn the list somebody is trying to read."""
        _model(clean_db, "10/22", makers=[firm], status=ArmoryStatus.PENDING)
        assert armory.plan_qualify(clean_db) == []

    def test_a_name_the_better_row_already_has(self, clean_db, firm):
        """firearm_models.name is unique, and a row already carrying the good
        name is the happy case: leave the bare one to be merged by hand."""
        _model(clean_db, "Ruger 10/22", makers=[firm])
        _model(clean_db, "10/22", makers=[firm])
        assert armory.plan_qualify(clean_db) == []

    @pytest.mark.parametrize(
        ("status", "enabled"),
        [(ArmoryStatus.PENDING, True), (ArmoryStatus.APPROVED, False)],
    )
    def test_a_firm_not_in_production(self, clean_db, status, enabled):
        """The rule that would have caught "CO" on its own merits rather than
        by its spelling: it was approved and *disabled*, dealt with by hand and
        still attached to two models. Disabled is a decision about a row, and
        writing a retired firm into a model's name would quietly undo it.
        """
        maker = Manufacturer(name="Cugir", status=status, enabled=enabled)
        clean_db.add(maker)
        clean_db.flush()
        _model(clean_db, "M1864", makers=[maker])
        assert armory.plan_qualify(clean_db) == []

    @pytest.mark.parametrize("junk", ["CO", "Co.", "Inc", "& Sons", "GmbH"])
    def test_a_firm_that_is_only_a_legal_suffix(self, clean_db, junk):
        """ "CO" sits in the maker table as an approved firm with eight
        listings, read out of "SPENCER REPEATING RIFLE CO M1865". Junk in a
        column nobody reads twice is survivable; junk in a model's *name* is
        what the page shows and what the matcher compiles.
        """
        maker = Manufacturer(name=junk, status=ArmoryStatus.APPROVED)
        clean_db.add(maker)
        clean_db.flush()
        _model(clean_db, "M1865", makers=[maker])
        assert armory.plan_qualify(clean_db) == []


class TestCarryingItOut:
    def test_the_old_name_becomes_an_alias(self, clean_db, firm):
        """What makes this safe against a live catalog: a listing saying only
        "10/22" still matches, so a rename can only widen what the row answers
        to, never narrow it."""
        row = _model(clean_db, "10/22", makers=[firm])
        armory.apply_qualify(clean_db, armory.plan_qualify(clean_db))
        clean_db.refresh(row)
        assert row.name == "Ruger 10/22"
        assert "10/22" in row.spellings
        assert armory.match(clean_db, "Nice 10/22 carbine .22LR").model_id == row.id
        assert armory.match(clean_db, "Ruger 10/22 rifle").model_id == row.id

    def test_an_existing_alias_is_kept(self, clean_db, firm):
        row = _model(clean_db, "10/22", makers=[firm], aliases="1022\nTen Twenty-Two")
        armory.apply_qualify(clean_db, armory.plan_qualify(clean_db))
        clean_db.refresh(row)
        assert set(row.spellings) == {"Ruger 10/22", "10/22", "1022", "Ten Twenty-Two"}

    def test_running_it_twice_does_nothing_the_second_time(self, clean_db, firm):
        _model(clean_db, "10/22", makers=[firm])
        assert armory.apply_qualify(clean_db, armory.plan_qualify(clean_db)) == 1
        assert armory.plan_qualify(clean_db) == []

    def test_a_row_that_moved_under_us_is_skipped(self, clean_db, firm):
        """The plan is printed, read and only then applied, so a name may have
        changed in between. Matching on the old name is what makes that safe."""
        row = _model(clean_db, "10/22", makers=[firm])
        plan = armory.plan_qualify(clean_db)
        row.name = "Something Else"
        clean_db.commit()
        assert armory.apply_qualify(clean_db, plan) == 0


class TestTheCountryWhenThereIsNoFirm:
    """178 of 280 bare designations named a country and no maker at all.

    A nationality says less than a firm — "Swedish Model 1896" narrows less
    than "Ruger 10/22" — and far more than nothing, and it is the same bargain
    either way: the fact is already on the row, and this only moves it into the
    name.
    """

    def _row(self, session, name, country, **kwargs):
        row = FirearmModel(name=name, country=country, status=ArmoryStatus.APPROVED, **kwargs)
        session.add(row)
        session.commit()
        armory.invalidate()
        return row

    def test_a_country_only_row_gets_its_nationality(self, clean_db):
        self._row(clean_db, "Model 1896", "Sweden")
        assert [(r.was, r.now) for r in armory.plan_qualify(clean_db)] == [
            ("Model 1896", "Swedish Model 1896")
        ]

    def test_a_country_with_no_adjective_is_left_alone(self, clean_db):
        """The map is deliberately not exhaustive. A country with no entry keeps
        its bare designation, the same refusal a row with several makers gets:
        the pass says nothing rather than guessing."""
        self._row(clean_db, "Model 1896", "Ruritania")
        assert armory.plan_qualify(clean_db) == []

    def test_and_a_row_with_neither(self, clean_db):
        self._row(clean_db, "Model 1896", None)
        assert armory.plan_qualify(clean_db) == []

    def test_the_firm_wins_when_there_is_one(self, clean_db, firm):
        """ "Ruger 10/22" says more than "U.S. 10/22"."""
        self._row(clean_db, "10/22", "United States", manufacturers=[firm])
        assert armory.plan_qualify(clean_db)[0].now == "Ruger 10/22"

    def test_several_makers_fall_through_to_the_country(self, clean_db):
        """Nine firms built the M1 Carbine, so naming one is out — but where
        the pattern comes from is still a fact, and still worth saying."""
        makers = [Manufacturer(name=n, status=ArmoryStatus.APPROVED) for n in ("Inland", "IBM")]
        clean_db.add_all(makers)
        clean_db.flush()
        self._row(clean_db, "M1", "United States", manufacturers=makers)
        assert armory.plan_qualify(clean_db)[0].now == "U.S. M1"

    def test_an_unusable_firm_falls_through_too(self, clean_db):
        """ "CO" was approved, disabled and attached to M1864 and M1865. A
        country is a poorer answer than a firm and a better one than nothing,
        and a row whose only firm is unusable is where that trade pays."""
        junk = Manufacturer(name="CO", status=ArmoryStatus.APPROVED, enabled=False)
        clean_db.add(junk)
        clean_db.flush()
        self._row(clean_db, "M1865", "United States", manufacturers=[junk])
        assert armory.plan_qualify(clean_db)[0].now == "U.S. M1865"


class TestEveryAdjectiveReadsBackAsItsOwnCountry:
    """The property that makes writing a nationality into a name safe at all.

    The classifier reads titles for a country, and after this pass a model name
    *is* a title it will meet. An adjective it does not recognize -- or
    recognizes as somewhere else -- would be a row teaching the classifier the
    wrong thing about itself. So the map is not trusted, it is checked.
    """

    @pytest.mark.parametrize(("country", "adjective"), sorted(armory._COUNTRY_ADJECTIVE.items()))
    def test_round_trip(self, country, adjective):
        assert extract_country(f"{adjective} Model 1896 Rifle") == country
