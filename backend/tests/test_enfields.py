"""The M1917 is a .30-06 and the P14 a .303 British.

One rifle in two cartridges: the Pattern 1914 was designed for Britain in .303
and rechambered in .30-06 by the American factories as the Model of 1917. The
word "Enfield" alone used to decide, and "CMP M1917 Enfield Service Grade" was
stored as a .303 British -- four listings on production, 2026-10-04.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, Caliber, FirearmModel, Item, Site
from app.services import classify, enfields, provenance


class TestReadingIt:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("CMP M1917 Enfield Service Grade (RM1917SG)", ".30-06"),
            ("EDDYSTONE MODEL OF 1917", ".30-06"),
            ("Remington Model 1917 rifle", ".30-06"),
            ("American Enfield rifle", ".30-06"),
            ("REMINGTON PATTERN 14 ENFIELD", ".303 British"),
            ("British Eddystone P14 w/ Volley Sights", ".303 British"),
            # Not a rifle: no Enfield and none of its factories, or a revolver.
            ("Para Ordnance P14-45 pistol", None),
            ("Colt M1917 revolver, shipped to Winchester", None),
        ],
    )
    def test_the_designation(self, title, expected):
        assert classify.extract_caliber(title) == expected

    def test_the_one_mentioned_first_decides(self):
        """Each rifle's history names the other; the title comes first."""
        m1917 = "M1917 Enfield, the American modification of the Pattern 1914 Enfield (P14)"
        p14 = "Remington P14 Enfield rifle. The same factory later built the Model of 1917"
        assert classify.extract_caliber(m1917) == ".30-06"
        assert classify.extract_caliber(p14) == ".303 British"

    def test_a_stated_cartridge_still_wins(self):
        assert classify.extract_caliber("M1917 Enfield rebarreled to 8mm Mauser") == "8mm Mauser"

    def test_enfield_alone_is_still_a_303(self):
        assert classify.extract_caliber("Enfield rifle, good bore") == ".303 British"


@pytest.fixture
def stored(clean_db):
    """Listings stored before the classifier knew, against a small armory."""
    s = clean_db
    us = Caliber(name=".30-06 Springfield", aliases=".30-06", status=ArmoryStatus.APPROVED)
    british = Caliber(name=".303 British", status=ArmoryStatus.APPROVED)
    s.add_all([us, british])
    m1917 = FirearmModel(name="M1917 Enfield", status=ArmoryStatus.APPROVED)
    m1917.calibers = [us]
    s.add(m1917)
    site = Site(slug="enf", name="Enf", base_url="https://e.test/")
    s.add(site)
    s.flush()

    def item(key, title, caliber, source=provenance.DERIVED, model=None):
        row = Item(
            site_id=site.id,
            external_key=key,
            url=f"https://e.test/{key}",
            title=title,
            caliber=caliber,
            caliber_source=source,
            firearm_model_id=model.id if model else None,
        )
        s.add(row)
        return row

    rows = {
        "cmp": item("cmp", "CMP M1917 Enfield Service Grade", ".303 British", model=m1917),
        "catalog": item(
            "cat", "M1917 Enfield stock", ".303 British", provenance.CATALOG, model=m1917
        ),
        "no_model": item("nm", "Eddystone Model 1917 rifle", ".303 British"),
        "p14": item("p14", "Remington P14 Enfield", ".30-06 Springfield"),
        "vendor": item("v", "CMP M1917 Enfield", ".303 British", provenance.VENDOR, model=m1917),
        "person": item("o", "CMP M1917 Enfield", ".303 British", provenance.OVERRIDE, model=m1917),
        "unknown": item("u", "CMP M1917 Enfield", ".303 British", None, model=m1917),
        "stated": item("st", "M1917 Enfield .303 British conversion", ".303 British", model=m1917),
        "lee": item("lee", "Lee-Enfield No.4 Mk1", ".303 British"),
    }
    s.commit()
    return rows


class TestPuttingRightWhatWasStored:
    def test_a_guess_is_corrected(self, clean_db, stored):
        assert enfields.recalibrate(clean_db.connection()) == 4
        clean_db.commit()
        clean_db.expire_all()
        for key in ("cmp", "catalog", "no_model"):
            assert stored[key].caliber == ".30-06 Springfield", key
        assert stored["p14"].caliber == ".303 British"

    def test_a_vendor_a_person_an_unknown_origin_or_a_stated_cartridge_is_kept(
        self, clean_db, stored
    ):
        enfields.recalibrate(clean_db.connection())
        clean_db.commit()
        clean_db.expire_all()
        for key in ("vendor", "person", "unknown", "stated", "lee"):
            assert stored[key].caliber == ".303 British", key

    def test_a_second_run_changes_nothing(self, clean_db, stored):
        enfields.recalibrate(clean_db.connection())
        clean_db.commit()
        assert enfields.recalibrate(clean_db.connection()) == 0
