"""The reference generation (app.services.refgen), added 2026-11-06.

A change made in one process -- the command line, a script -- has to reach
another's compiled armory. It did not: the alias taken off the Colt
Diamondback from the command line stayed in the running app, whose scans put
53 Diamondback Firearms revolvers back under Colt overnight.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select, update

from app.database import get_session_factory
from app.models import (
    ArmoryStatus,
    FirearmKind,
    FirearmModel,
    Manufacturer,
    ReferenceGeneration,
    firearm_model_manufacturers,
)
from app.services import armory, refgen


def _generation(session) -> int:
    session.expire_all()
    return session.execute(select(ReferenceGeneration.generation)).scalar_one()


@pytest.fixture
def fresh(clean_db):
    refgen.forget()
    armory.invalidate()
    yield clean_db
    refgen.forget()
    armory.invalidate()


def _approved(name, aliases=None):
    return FirearmModel(
        name=name, aliases=aliases, kind=FirearmKind.REVOLVER, status=ArmoryStatus.APPROVED
    )


class TestWhatMovesIt:
    def test_an_approved_row_added_or_edited(self, fresh):
        before = _generation(fresh)
        row = _approved("Colt Diamondback", "Diamondback")
        fresh.add(row)
        fresh.commit()
        assert _generation(fresh) == before + 1
        row.aliases = None
        fresh.commit()
        assert _generation(fresh) == before + 2

    def test_a_proposal_does_not(self, fresh):
        """Scans propose pending rows all day, and no cache reads them."""
        before = _generation(fresh)
        row = FirearmModel(name="GEN3", status=ArmoryStatus.PENDING)
        fresh.add(row)
        fresh.commit()
        row.aliases = "GEN 3"
        fresh.commit()
        assert _generation(fresh) == before

    def test_approving_one_or_sending_one_back_does(self, fresh):
        row = FirearmModel(name="TZ75", status=ArmoryStatus.PENDING)
        fresh.add(row)
        fresh.commit()
        before = _generation(fresh)
        row.status = ArmoryStatus.APPROVED
        fresh.commit()
        row.status = ArmoryStatus.PENDING
        fresh.commit()
        assert _generation(fresh) == before + 2

    def test_a_deletion_does(self, fresh):
        row = FirearmModel(name="USED 940", status=ArmoryStatus.PENDING)
        fresh.add(row)
        fresh.commit()
        before = _generation(fresh)
        fresh.delete(row)
        fresh.commit()
        assert _generation(fresh) == before + 1

    def test_a_maker_linked_to_a_model_does(self, fresh):
        row, maker = _approved("DB9"), Manufacturer(name="Diamondback Firearms")
        fresh.add_all([row, maker])
        fresh.commit()
        before = _generation(fresh)
        row.manufacturers.append(maker)
        fresh.commit()
        assert _generation(fresh) == before + 1

    def test_a_bulk_statement_does(self, fresh):
        fresh.add(_approved("XD-40"))
        fresh.commit()
        before = _generation(fresh)
        fresh.execute(update(FirearmModel).values(aliases="XD 40"))
        fresh.execute(delete(firearm_model_manufacturers))
        fresh.commit()
        assert _generation(fresh) == before + 2

    def test_a_rolled_back_change_does_not(self, fresh):
        before = _generation(fresh)
        fresh.add(_approved("Colt Python"))
        fresh.flush()
        fresh.rollback()
        assert _generation(fresh) == before


class TestAnotherProcesssEdit:
    def test_reaches_the_compiled_armory(self, fresh, monkeypatch):
        fresh.add(_approved("Colt Diamondback", "Diamondback"))
        fresh.commit()
        title = "Diamondback DB380 Gen IV .380 ACP Pistol"
        assert armory.match(fresh, title).model == "Colt Diamondback"

        # Another process: its own session, and no invalidate() reaching here.
        other = get_session_factory()()
        try:
            other.execute(update(FirearmModel).values(aliases=None))
            other.commit()
        finally:
            other.close()

        # Inside the interval the compiled copy stands; past it, it is rebuilt.
        assert armory.match(fresh, title).model == "Colt Diamondback"
        monkeypatch.setattr(refgen, "CHECK_SECONDS", 0.0)
        assert armory.match(fresh, title).model is None

    def test_this_processs_first_look_rebuilds_nothing(self, fresh, monkeypatch):
        monkeypatch.setattr(refgen, "CHECK_SECONDS", 0.0)
        called = []
        monkeypatch.setattr(refgen, "invalidate_all", lambda: called.append(1))
        refgen.check(fresh)
        refgen.check(fresh)
        assert called == []

    def test_a_failed_check_does_not_fail_the_read(self, fresh, monkeypatch):
        monkeypatch.setattr(refgen, "CHECK_SECONDS", 0.0)

        def broken(_session):
            raise RuntimeError("no table")

        monkeypatch.setattr(refgen, "_current", broken)
        refgen.check(fresh)
        refgen.check()
