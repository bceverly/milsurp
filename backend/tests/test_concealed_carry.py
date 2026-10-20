"""Concealed carry: the rule, and the Type it fills.

Asked for on 2026-10-08, with .32 ACP and .25 ACP added later the same day. The cases below are the guns the rule was measured on
against production's 6,856 handguns, and -- the half that matters as much --
the look-alikes it was caught taking on the way: a CZ Model 38, a PPS-43, an
S&W .38 Single Action from the 1870s, a Colt Peacemaker "Centennial".
"""

from __future__ import annotations

import inspect
import pathlib

import pytest
from sqlalchemy import func, select

from app.models import FirearmModel, Item, Site
from app.services import carry, hotdeals
from app.services.search import KINDS

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def carried(title, *, kind="pistol", caliber=None, model=None, is_pistol=True, is_rifle=False):
    return carry.is_concealed_carry(
        title, is_pistol=is_pistol, is_rifle=is_rifle, kind=kind, caliber=caliber, model=model
    )


class TestWhatIsCarry:
    @pytest.mark.parametrize(
        ("title", "kind", "caliber"),
        [
            ("GLOCK 19 Gen5 MOS 9mm Pistol (Used, Grade 2)", "pistol", "9mm Luger"),
            ("Glock 19V 250th Anniv of America 9mm", "pistol", "9mm Luger"),
            ("USED Glock 43 9mm Semi Auto Pistol", "pistol", "9mm Luger"),
            ("ANIB Sig Sauer P365X - w/ Sig Romeo-X Sight", None, None),
            ("Police Trade In Sig Sauer P320 Compact 9mm No Mag", "pistol", "9mm Luger"),
            ("Heckler & Koch P7 M13 9mm Pistol", "pistol", "9mm Luger"),
            ("SIG Sauer P6 9mm West German Police", "pistol", "9mm Luger"),
            ("S&W M&P9 Shield 9mm", "pistol", "9mm Luger"),
            ("USED Smith & Wesson M&P 40C Compact 40 S&W Pistol", "pistol", ".40 S&W"),
            ("Colt 1911 Officer's ACP .45", "pistol", ".45 ACP"),
            ("ANIB Walther PPK/S - .380 ACP", "pistol", ".380 ACP"),
            ("31985-SMITH & WESSON BODYGUARD .380 CAL. SEMI-AUTO PISTOL", "pistol", ".380 ACP"),
            # Revolvers: a J-frame, the small Rugers and Colts, a Charter.
            ("Smith & Wesson Model 642 Airweight .38 Special", "revolver", ".38 Special"),
            ("Used Smith & Wesson 642 Airweight 38 Special", None, ".38 Special"),
            ("Early Smith & Wesson Model 37 Flat Latch Chiefs Special", "revolver", None),
            ("USED Smith & Wesson 340 Snub Nose Hammerless 357 Mag Revolver", None, ".357 Magnum"),
            ("Ruger LCR .38 Special", "revolver", ".38 Special"),
            ("RUGER MODEL SP101 .357 MAGNUM 3” STAINLESS REVOLVER", "revolver", ".357 Magnum"),
            ("1958 Colt Detective Special Revolver - .38 Special", "revolver", ".38 Special"),
            ("Charter Arms Bulldog .44 Special", "revolver", None),
            # A revolver of any make whose barrel is three inches or less.
            ('Colt Police Positive .38 Special 2" Snub', "revolver", ".38 Special"),
            ('Colt Python .357 Magnum 3"', "revolver", ".357 Magnum"),
            ('S&W Model 19 .357 2.5"', "revolver", ".357 Magnum"),
            # The .32 and .25 pocket pistols, added the same day.
            ("Police Eagle/C Walther PPK - With Scarce Gray Grip", "pistol", ".32 ACP"),
            ("1942 Commercial Mauser HSC Rig", "pistol", ".32 ACP"),
            ("Colt M1903 Pocket Hammerless Rig - US Property", "pistol", ".32 ACP"),
            ("Walther Model 8 - .25 ACP (6.35 Browning) - First Variant", "pistol", ".25 ACP"),
            ("FN MODEL 1905 ENGRAVED", "pistol", ".25 ACP"),
            ("Beretta Tomcat 3032", "pistol", ".32 ACP"),
            # The brand before the model number, as Kittery Trading Post writes it.
            ("TAURUS 85 PRE OWNED (1144454)", None, None),
            # A pistol whose barrel the title states, as Greentop's all do.
            ('Used SIG SAUER 1911 45ACP 54A012011 3.25" STS G', None, ".45 ACP"),
            ('Used STEYR ARMS C9-A2 9X19 3211084 3.5" MATTE', None, "9mm Luger"),
        ],
    )
    def test_these_are(self, title, kind, caliber):
        assert carried(title, kind=kind, caliber=caliber)

    @pytest.mark.parametrize(
        ("title", "kind", "caliber"),
        [
            # Duty and target sizes.
            ("Glock 17 Gen 3 9mm", "pistol", "9mm Luger"),
            ("LEO Trade-In GLOCK 22 GEN 4 .40S&W Handgun", "pistol", ".40 S&W"),
            ("Smith & Wesson M&P 9 Full Size", "pistol", "9mm Luger"),
            ("Springfield 1911 Loaded Target .45 ACP", "pistol", ".45 ACP"),
            ("Beretta 92FS 9mm", "pistol", "9mm Luger"),
            ('Colt Python .357 Magnum 6"', "revolver", ".357 Magnum"),
            ("S&W Model 10 .38 Special 4 inch Police Trade In", "revolver", ".38 Special"),
            # Small, but not in a cartridge that was asked for.
            ("Makarov PM 9x18", "pistol", "9x18mm Makarov"),
            ("British Bulldog Revolver .442", "revolver", ".442 Webley"),
            # No cartridge at all.
            ("Colt 1860 Army Percussion", "percussion_revolver", ".44"),
            # Look-alikes the rule was caught taking.
            ("CZ Model 38 (FG46)", None, None),
            ("S&W 38 Single Action First Model Revolver", "revolver", None),
            ("Colt Peacemaker Centennial SAA", "revolver", None),
            ("VKT Lahti L-35 Officer Private-Purchase Pistol", "pistol", "9mm Luger"),
            # A compact in an unknown chambering may be a .22 or a .25.
            ("Tanfoglio Force Compact 919 - No Magazine", None, None),
            # A short barrel on a pistol-caliber carbine sold as a "pistol".
            ("(USED) Sig Sauer SIG MPX Copperhead, 9mm 3.5in Pistol", None, "9mm Luger"),
            ('Used RUGER SECURITY-9 9MM 387-77501 4" MATTE G', None, "9mm Luger"),
        ],
    )
    def test_these_are_not(self, title, kind, caliber):
        assert not carried(title, kind=kind, caliber=caliber)

    def test_the_armory_model_counts_as_part_of_the_name(self):
        assert carried("ANIB with Sig Romeo-X Sight", kind=None, model="P365X")
        # And a model name that merely starts the same way does not.
        assert not carried(
            "WW2 Polish Semi-Auto Submachine Gun", kind=None, caliber="9mm Luger", model="PPS-43"
        )

    def test_only_a_handgun_is_ever_carry(self):
        assert not carried("Glock 19 9mm", is_pistol=False)
        assert not carried("Glock 19 9mm", is_rifle=True)

    @pytest.mark.parametrize(
        ("title", "inches"),
        [('Colt Cobra 2" .38', 2.0), ("Model 36 1 7/8 inch", 1.875), ("2¼” barrel", 2.25)],
    )
    def test_the_barrel_is_read(self, title, inches):
        assert carry.barrel_inches(title) == pytest.approx(inches)


class TestBothPathsSetIt:
    """`is_police_surplus` was once derived and never stored, and once stored
    by the scan and not by `reclassify`. Both call the same function here."""

    def test_the_scan_does(self):
        from app.services import scan_service

        assert "_settle_last(session, item)" in inspect.getsource(scan_service._upsert_item)
        assert "carry.decide(session, item)" in inspect.getsource(scan_service._settle_last)

    def test_and_reclassify_does(self):
        assert "carry.decide(session, item)" in (BACKEND / "cli.py").read_text(encoding="utf-8")

    def test_decide_reads_the_stored_listing(self, clean_db):
        site = Site(slug="s", name="S", base_url="https://s.test/")
        model = FirearmModel(name="Glock 26")
        clean_db.add_all([site, model])
        clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key="a",
            url="https://s.test/a",
            title="Glock Gen 4 Police Trade-In",
            is_pistol=True,
            caliber="9mm Luger",
            firearm_model_id=model.id,
        )
        clean_db.add(item)
        clean_db.flush()
        assert carry.decide(clean_db, item)


class TestTheType:
    """A traded-in Glock 19 is counted once, and under Concealed carry."""

    @pytest.fixture
    def shelf(self, clean_db):
        site = Site(slug="s", name="S", base_url="https://s.test/")
        clean_db.add(site)
        clean_db.flush()
        rows = {
            "duty": dict(is_pistol=True),
            "carry": dict(is_pistol=True, is_concealed_carry=True),
            "traded_duty": dict(is_pistol=True, is_police_surplus=True),
            "traded_carry": dict(is_pistol=True, is_police_surplus=True, is_concealed_carry=True),
        }
        for key, flags in rows.items():
            clean_db.add(
                Item(site_id=site.id, external_key=key, url=f"https://s.test/{key}", title=key)
            )
            clean_db.flush()
            row = clean_db.execute(select(Item).where(Item.external_key == key)).scalar_one()
            for name, value in flags.items():
                setattr(row, name, value)
        clean_db.commit()
        return clean_db

    def keys(self, session, kind):
        return set(session.execute(select(Item.external_key).where(KINDS[kind])).scalars())

    def test_each_listing_lands_in_one_type(self, shelf):
        assert self.keys(shelf, "pistol") == {"duty"}
        assert self.keys(shelf, "concealed_carry") == {"carry", "traded_carry"}
        assert self.keys(shelf, "police_surplus") == {"traded_duty"}

    def test_and_the_types_still_add_up(self, shelf):
        total = shelf.execute(select(func.count(Item.id))).scalar_one()
        assert sum(len(self.keys(shelf, kind)) for kind in KINDS) == total

    def test_hot_deals_buckets_agree(self, shelf):
        rows = {row.external_key: row for row in shelf.execute(select(Item)).scalars()}
        assert hotdeals.bucket_of(rows["traded_carry"]) == "concealed_carry"
        assert hotdeals.bucket_of(rows["traded_duty"]) == "police_surplus"
        assert hotdeals.bucket_of(rows["duty"]) == "pistol"
        assert hotdeals.BUCKET_LABELS["concealed_carry"] == "Concealed carry"


class TestTenMillimeter:
    """10mm Auto counts at any size, asked for on 2026-10-11: of 33 10mm
    handguns for sale that day, the size rule had admitted none."""

    @pytest.mark.parametrize(
        "title",
        [
            "USED Glock 20 Gen 4 10mm Semi Auto Pistol",
            "COLT DELTA ELITE PRE OWNED (1139745)",
            'Used SIG SAUER P320XTEN 10MM 5" MATTE E GTO392881',
        ],
    )
    def test_a_full_size_ten_is_carry(self, title):
        assert carried(title, caliber="10mm Auto")

    @pytest.mark.parametrize(
        "title",
        ["Lefaucheux Pinfire", "LEFACHEUX PINFIRE REVOLVER", "Hi-Point 1095TS 10mm Carbine"],
    )
    def test_but_not_a_pinfire_or_a_carbine(self, title):
        assert not carried(title, kind=None, caliber="10mm Auto")

    def test_and_not_a_rifle(self):
        assert not carried("Something 10mm", caliber="10mm Auto", is_pistol=False, is_rifle=True)


class TestFiveSevenAndTwentyTwo:
    """5.7x28mm at any size, like 10mm; .22 LR under the size rule. Both asked
    for on 2026-10-11."""

    def test_a_full_size_five_seven_is_carry(self):
        assert carried("FN Five-seveN MK2 5.7x28mm Pistol", caliber="5.7x28mm")
        assert carried("Ruger-57 Pistol", caliber="5.7x28mm")

    def test_but_not_a_ps90(self):
        assert not carried("FN PS90 5.7x28mm", kind=None, caliber="5.7x28mm")

    def test_a_small_twenty_two_is_carry_and_a_target_pistol_is_not(self):
        assert (
            carried('Heritage Rough Rider .22 LR 3.75" Revolver', kind="revolver", caliber=".22 LR")
            is False
        )
        assert carried(
            'Smith & Wesson Model 317 Airweight .22 LR 1 7/8"', kind="revolver", caliber=".22 LR"
        )
        # A pocket .22 is what was asked for: the .22 PPK/S and the Bobcat.
        assert carried("Walther PPK/S .22 LR", caliber=".22 LR")
        assert carried("Beretta 21A Bobcat .22 LR", caliber=".22 LR", model="Beretta 21A Bobcat")
        assert not carried('Browning Buck Mark Target 22 LR 5.5"', caliber=".22 LR")


@pytest.mark.parametrize(
    ("caliber", "is_carry"),
    [
        (".357 SIG", True),
        (".44 Magnum", True),
        (".44 Rem Mag", True),
        (".45 Colt", True),
        (".45 Long Colt", True),
        (".22 WMR", True),
        (".22 Magnum", True),
        (".32 S&W Long", True),
        (".45 ACP", True),
        (".25 ACP", True),
        (".22 LR", True),
        ("9mm Makarov", False),
        (".32 S&W", False),
        (".30-06 Springfield", False),
    ],
)
def test_one_list_with_the_carry_shops(caliber, is_carry):
    """2026-10-20: the calibers the carry shops' scrapers read."""
    assert carry.is_carry_caliber(caliber) is is_carry
