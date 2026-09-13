"""Filling a row from its own listings, and switching off one that says nothing.

The residue of approving a discovery queue wholesale: approved rows with no
kind, no country, no maker and no cartridge. Some of them hold listings and can
be answered from those; the rest hold nothing and can only ever take a match
away from a better row.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmKind, FirearmModel, Item, Site
from app.services import armory


@pytest.fixture
def site(clean_db):
    row = Site(slug="s", name="S", base_url="https://e.test/")
    clean_db.add(row)
    clean_db.flush()
    return row


def _model(session, name, **kwargs):
    kwargs.setdefault("status", ArmoryStatus.APPROVED)
    row = FirearmModel(name=name, **kwargs)
    session.add(row)
    session.flush()
    return row


def _listing(session, site, model, *, title="A rifle", country=None, kind=None):
    session.add(
        Item(
            site_id=site.id,
            external_key=f"k{title}{country}{kind}",
            url="https://e.test/x",
            title=title,
            firearm_model_id=model.id if model else None,
            country=country,
            kind=kind,
            is_rifle=True,
        )
    )


class TestFillingFromItsOwnListings:
    def test_a_country_two_listings_agree_on(self, clean_db, site):
        model = _model(clean_db, "M1896")
        for n in range(2):
            _listing(
                clean_db,
                site,
                model,
                title=f"Swedish Mauser M1896 #{n}",
                country="Sweden",
                kind="rifle",
            )
        clean_db.commit()
        armory.invalidate()

        armory.apply_tidy(clean_db, armory.plan_tidy(clean_db))
        clean_db.refresh(model)
        assert model.country == "Sweden"

    def test_but_never_the_kind(self, clean_db, site):
        """It looks as fillable as the country and is not. The shipped file
        takes a kind as the marker of a row somebody has judged -- "it cannot
        be guessed from a title" -- and requires a country beside it on that
        basis. A machine writing kinds falsifies the premise: six rows gained
        one, none could gain a country, and the file then carried six
        judged-looking models that name nowhere.
        """
        model = _model(clean_db, "M1896")
        for n in range(4):
            _listing(clean_db, site, model, title=f"M1896 #{n}", kind="rifle")
        clean_db.commit()
        armory.invalidate()

        armory.apply_tidy(clean_db, armory.plan_tidy(clean_db))
        clean_db.refresh(model)
        assert model.kind is None

    def test_but_never_from_a_single_listing(self, clean_db, site):
        """With one listing "they all agree" is true by construction.

        Both failures this floor exists for were singletons. "SOHN 38H" -- a
        truncation of "J.P. Sauer & Sohn 38H" -- would have learned it was
        Swiss from one listing whose country came through "Sauer"; the firm is
        German. "X400" is a Surefire weaponlight, and its one listing is a
        rifle sold *with* one, which would have made the row a Swiss rifle.
        """
        model = _model(clean_db, "SOHN 38H")
        _listing(clean_db, site, model, title="JP SAUER & SOHN 38H", country="Switzerland")
        clean_db.commit()
        armory.invalidate()

        assert armory.plan_tidy(clean_db) == []

    def test_nor_where_the_listings_disagree(self, clean_db, site):
        model = _model(clean_db, "Model 1910")
        _listing(clean_db, site, model, title="German Model 1910", country="Germany")
        _listing(clean_db, site, model, title="Belgian Model 1910", country="Belgium")
        clean_db.commit()
        armory.invalidate()

        assert armory.plan_tidy(clean_db) == []

    def test_and_a_fact_already_on_the_row_is_left_alone(self, clean_db, site):
        """This fills blanks. A curated answer outranks a tally of listings."""
        model = _model(clean_db, "M24/47", country="Germany")
        for n in range(3):
            _listing(clean_db, site, model, title=f"Yugo M24/47 #{n}", country="Yugoslavia")
        clean_db.commit()
        armory.invalidate()

        armory.apply_tidy(clean_db, armory.plan_tidy(clean_db))
        clean_db.refresh(model)
        assert model.country == "Germany"

    def test_the_maker_is_deliberately_not_filled(self, clean_db, site):
        """64 listings would have taught "CARL GUSTAF 1896" that its maker is
        Mauser, which designed the pattern and did not build the rifle. No rule
        available here separates a designer from a builder, so the column is
        left to a human."""
        model = _model(clean_db, "Carl Gustaf 1896")
        for n in range(4):
            _listing(clean_db, site, model, title=f"Swedish Mauser #{n}", country="Sweden")
        clean_db.commit()
        armory.invalidate()

        armory.apply_tidy(clean_db, armory.plan_tidy(clean_db))
        clean_db.refresh(model)
        assert model.manufacturers == []


class TestRetiringOneThatSaysNothing:
    def test_a_silent_row_nothing_matches_is_switched_off(self, clean_db):
        model = _model(clean_db, "M14", first_seen_in="Some M14 listing")
        clean_db.commit()
        armory.invalidate()

        armory.apply_tidy(clean_db, armory.plan_tidy(clean_db))
        clean_db.refresh(model)
        assert model.enabled is False

    def test_switched_off_rather_than_deleted(self, clean_db):
        """propose_model looks a name up regardless of status, so a surviving
        row is a tombstone that stops the name coming back and a deleted one
        returns the next time a scan meets it. The page says the same on its
        trashcan -- see comesBack() in Armory.jsx."""
        model = _model(clean_db, "M14", first_seen_in="Some M14 listing")
        clean_db.commit()
        armory.invalidate()

        armory.apply_tidy(clean_db, armory.plan_tidy(clean_db))
        assert clean_db.get(FirearmModel, model.id) is not None

    def test_a_row_from_the_shipped_file_is_left_alone(self, clean_db):
        """No first_seen_in means nobody's scan proposed it: it came from the
        armory file, and switching it off would fight `armory seed`."""
        _model(clean_db, "M14")
        clean_db.commit()
        armory.invalidate()

        assert armory.plan_tidy(clean_db) == []

    def test_nor_one_that_answers_for_a_listing(self, clean_db, site):
        """A row holding even one listing is doing something."""
        model = _model(clean_db, "M14", first_seen_in="Some M14 listing")
        _listing(clean_db, site, model, title="An M14")
        clean_db.commit()
        armory.invalidate()

        assert [e.action for e in armory.plan_tidy(clean_db)] == []

    def test_nor_one_that_still_says_something(self, clean_db):
        model = _model(clean_db, "M14", kind=FirearmKind.RIFLE, first_seen_in="An M14")
        clean_db.commit()
        armory.invalidate()

        assert armory.plan_tidy(clean_db) == []
        clean_db.refresh(model)
        assert model.enabled is True


class TestItSettles:
    def test_a_second_run_finds_nothing(self, clean_db, site):
        model = _model(clean_db, "M1896")
        for n in range(2):
            _listing(clean_db, site, model, title=f"Swedish Mauser #{n}", country="Sweden")
        _model(clean_db, "M14", first_seen_in="An M14")
        clean_db.commit()
        armory.invalidate()

        assert armory.apply_tidy(clean_db, armory.plan_tidy(clean_db)) == (1, 1)
        assert armory.plan_tidy(clean_db) == []


class TestARetiredRowIsLeftAlone:
    def test_qualify_skips_it(self, clean_db):
        """56 of the bare designations were already switched off by hand.
        Renaming those is busywork, and it also makes the armory look like it
        has more live problems than it does -- which is exactly how "91
        unqualifiable rows" got reported when the real number was 34."""
        from app.models import Manufacturer

        firm = Manufacturer(name="Ruger", status=ArmoryStatus.APPROVED)
        clean_db.add(firm)
        clean_db.flush()
        _model(clean_db, "10/22", manufacturers=[firm], enabled=False)
        clean_db.commit()
        armory.invalidate()

        assert armory.plan_qualify(clean_db) == []
