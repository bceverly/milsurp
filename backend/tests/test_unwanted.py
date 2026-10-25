"""Guns the catalog does not carry (app.services.unwanted), asked for on
2026-10-25: Heritage Rough Rider revolvers and any Hi-Point pistol.

The titles are production's, as distributors and shops wrote them.
"""

from __future__ import annotations

import cli
import pytest
from sqlalchemy import select
from test_scan_service import FakeScraper, listing
from test_scan_service import fake_site as fake_site_fixture

from app.models import Item, ScanRun, ScanStatus
from app.services import scan_service, unwanted

#: The scan tests' site and fake scraper, borrowed under the name the tests use.
fake_site = fake_site_fixture

ROUGH_RIDERS = [
    ("HER RR22NI4BW 22LR RR NI 4-3/4 6R BLK LA", "Heritage Mfg"),
    ("HER RGH RDR 22LR 4.75B BLK/BLK", "Heritage Mfg"),
    ("HTG ROUGH RIDER RANCHER 22LR 16 6RD LAM BH SGHT", "Colt"),
    ("USED Heritage Rough Rider 9 Shot 22WMR/22LR Revolver", None),
    ("Heritage Arms .22 LR Revolver \u2013 Burnt Bronze Cerakote, 6.5\u2033 Barrel", None),
    ('HERITAGE 22LR 6.5" FS NICKEL COCOBOLO GRIPS', "Heritage Mfg"),
    ("Heritage Arms 22LR Tac Cowboy Revolver 6.5\u2033", None),
    ('22LR BLUE 6.5" US FLAG FS', "Heritage Mfg"),
    ('HERITAGE BARKEEP 22LR 1" 6RD GRY PRL', "Heritage Mfg"),
]
NOT_ROUGH_RIDERS = [
    ('HERITAGE ROSCOE 38SPL 3" FIXED BLACK ROSEWOOD/PEARL', "Heritage Mfg"),
    ('HERITAGE RANCH HAND 45LC 12" 6RD BLACK/WOOD', "Heritage Mfg"),
    ("HER SML22LCH12 SETTLER MARES LG 22LR 12.5 10R CH", "Heritage Mfg"),
    ('HERITAGE 92 44MAG 18" 8RD PVD GOLD', "Heritage Mfg"),
    ("COLT Aztec MEXICAN HERITAGE 1911 SEMI-AUTOMATIC PISTOL 38 SUPER", "Colt"),
    ("Ruger Vaquero .45 Colt Rough Rider Edition", "Ruger"),
]


@pytest.mark.parametrize(("title", "maker"), ROUGH_RIDERS)
def test_a_rough_rider_in_any_of_its_spellings(title, maker):
    assert unwanted.is_heritage_rough_rider(title, maker)


@pytest.mark.parametrize(("title", "maker"), NOT_ROUGH_RIDERS)
def test_heritages_other_lines_and_other_makers_stay(title, maker):
    assert not unwanted.is_heritage_rough_rider(title, maker)


@pytest.mark.parametrize(
    ("title", "maker", "is_pistol", "model_kind"),
    [
        ("Hi-Point CF380HSP Home Security 380 ACP Pistol Package", "Ruger", True, None),
        ("HI-POINT 4595P .45 ACP Semi-Auto Pistol", "Hi-point", True, None),
        ("JHP GEN2 45ACP M81 CAMO 9+1 TB", "Hi-point", False, None),
        ("Hi-Point 995 9mm Pistol with M81 Brace", "Hi-point", True, None),
        ("Used Hi Point YC9 9mm", "Hi-point", False, "PISTOL"),
    ],
)
def test_a_hi_point_pistol(title, maker, is_pistol, model_kind):
    assert unwanted.is_hi_point_pistol(title, maker, is_pistol=is_pistol, model_kind=model_kind)


@pytest.mark.parametrize(
    ("title", "maker", "is_pistol"),
    [
        ("Hi-Point Firearms Model 995TS", "Hi-point", False),
        ("Hi-Point 4095TS Carbine .40 S&W", "Hi-point", False),
        ("Glock 19 Gen 5 9mm", "Glock", True),
    ],
)
def test_the_carbines_and_other_pistols_stay(title, maker, is_pistol):
    assert not unwanted.is_hi_point_pistol(title, maker, is_pistol=is_pistol, model_kind=None)


def _handgun(key, title):
    return listing(key, title=title, category="Handguns", description="A revolver.")


def test_a_scan_leaves_them_out(fake_site, clean_db):
    FakeScraper.payload = [
        _handgun("rr", "Heritage Rough Rider 22LR 6.5in Revolver"),
        _handgun("hp", "Hi-Point C9 9mm Pistol"),
        _handgun("keep", "Smith & Wesson Model 10 .38 Special Revolver"),
    ]
    run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
    assert run.status == ScanStatus.SUCCESS
    keys = set(clean_db.execute(select(Item.external_key)).scalars())
    assert keys == {"keep"}
    assert run.items_new == 1
    assert "Left out" in (run.log or "")

    # And on the next scan too, without de-listing anything.
    run = clean_db.get(ScanRun, scan_service.run_scan(fake_site.id))
    assert set(clean_db.execute(select(Item.external_key)).scalars()) == {"keep"}
    assert run.items_delisted == 0


def test_catch_up_deletes_the_stored_ones_once(fake_site, clean_db, capsys):
    for key, title in (
        ("rr", "Heritage Rough Rider 22LR Revolver"),
        ("hp", "Hi-Point JHP 45ACP Pistol"),
        ("keep", "Ruger Single Six .22 LR Revolver"),
    ):
        clean_db.add(
            Item(
                site_id=fake_site.id,
                external_key=key,
                url=f"https://fake.test/{key}",
                title=title,
                is_pistol=True,
            )
        )
    clean_db.commit()

    assert cli._catch_up_unwanted(dry_run=True) == 0
    assert clean_db.execute(select(Item)).scalars().all()  # nothing changed
    assert cli._catch_up_unwanted(dry_run=False) == 2
    clean_db.expire_all()
    assert set(clean_db.execute(select(Item.external_key)).scalars()) == {"keep"}
    assert cli._catch_up_unwanted(dry_run=False) == 0
    assert "none stored" in capsys.readouterr().out
