"""Rejected suggestions travel with the armory file (2026-10-13).

Asked: should the "no"s be exported too, so a fresh install is not offered
again what was decided here -- "yes in all cases". The Wikipedia articles
turned down for makers, models and calibers, and the manufacturer pages
turned down for models, go out with their rows and come back on a load.
"""

from __future__ import annotations

import yaml

from app.models import ArmoryStatus, Caliber, FirearmModel, Manufacturer, ReferenceProposal
from app.services import armory

GLOCK_PAGE = "https://us.glock.com/en/products/law-enforcement/pistols/g19"
WRONG_ARTICLE = "https://en.wikipedia.org/wiki/Cartridge_(firearms)"


def _rows(session):
    glock = Manufacturer(name="Glock", status=ArmoryStatus.APPROVED)
    g19 = FirearmModel(name="Glock 19", status=ArmoryStatus.APPROVED)
    g19.manufacturers = [glock]
    vague = Caliber(name=".36 Test", status=ArmoryStatus.APPROVED)
    session.add_all([glock, g19, vague])
    session.flush()
    session.add_all(
        [
            ReferenceProposal(
                field="maker_page",
                target_type="model",
                target_id=g19.id,
                url=GLOCK_PAGE,
                title="g19",
                status="rejected",
            ),
            ReferenceProposal(
                field="wikipedia",
                target_type="caliber",
                target_id=vague.id,
                url=WRONG_ARTICLE,
                title="Cartridge (firearms)",
                status="rejected",
            ),
            # Pending is a question, not a decision, and is not exported.
            ReferenceProposal(
                field="wikipedia",
                target_type="model",
                target_id=g19.id,
                url="https://en.wikipedia.org/wiki/Glock",
                title="Glock",
            ),
        ]
    )
    session.commit()
    return g19, vague


class TestRejectionsTravel:
    def test_they_are_exported_with_their_rows(self, clean_db):
        _rows(clean_db)
        data = armory.export_armory(clean_db)
        g19 = next(row for row in data["models"] if row["name"] == "Glock 19")
        vague = next(row for row in data["calibers"] if row["name"] == ".36 Test")
        assert g19["rejected_maker_pages"] == [GLOCK_PAGE]
        assert "rejected_wikipedia" not in g19
        assert vague["rejected_wikipedia"] == [WRONG_ARTICLE]

    def test_a_load_brings_them_back_and_overrules_nothing(self, clean_db, tmp_path):
        _g19, vague = _rows(clean_db)
        path = tmp_path / "armory.yaml"
        path.write_text(yaml.safe_dump(armory.export_armory(clean_db)), encoding="utf-8")
        # A fresh install: the rows are there, the decisions are not -- except
        # one this install made the other way, which must stand.
        clean_db.query(ReferenceProposal).delete()
        clean_db.add(
            ReferenceProposal(
                field="wikipedia",
                target_type="caliber",
                target_id=vague.id,
                url=WRONG_ARTICLE,
                title="Cartridge (firearms)",
                status="accepted",
            )
        )
        clean_db.commit()
        assert armory.restore_rejections(clean_db, yaml.safe_load(path.read_text())) == 1
        clean_db.commit()
        decided = {
            (p.target_type, p.field, p.url): p.status
            for p in clean_db.query(ReferenceProposal).all()
        }
        assert decided == {
            ("model", "maker_page", GLOCK_PAGE): "rejected",
            ("caliber", "wikipedia", WRONG_ARTICLE): "accepted",
        }
        # And a second load adds nothing.
        assert armory.restore_rejections(clean_db, yaml.safe_load(path.read_text())) == 0
