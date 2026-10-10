"""A cartridge is recognized however a dealer spaces or dots it.

"357 mag", "45acp", "40 S&W", "10 MM": the same cartridges as ".357 Magnum",
".45 ACP", ".40 S&W" and "10mm", and until 2026-09-28 none of them was read.
Measured on production's 12,367 active listings, the classifier found a caliber
for 225 more and lost none.
"""

from __future__ import annotations

import pytest
import yaml

from app.services import armory
from app.services.classify import extract_caliber


class TestTheClassifierForgivesTheMissingDot:
    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            ("Colt Python 357 Mag 6in Stainless", ".357 Magnum"),
            ("USED EAA Girsan 1911 Untouchable 45ACP Pistol", ".45 ACP"),
            ("Used Police Trade Glock 21 SF 45 Auto 2-13 rd Mags", ".45 ACP"),
            ("PD Trade | Glock 27 Gen4 | 40 S&W | Night Sights", ".40 S&W"),
            ("USED Walther PPS 40S&W Semi Auto Compact Pistol", ".40 S&W"),
            ("Used Smith & Wesson 642 Airweight 38 Special", ".38 Special"),
            ("USED Ruger New Model Super Blackhawk 44 Mag Revolver", ".44 Magnum"),
            ("Ruger American Generation II 308 Winchester", ".308 Winchester"),
            ("Awesome Ruger Blackhawk Revolver Rare 3 Screw 30 Carbine 1970", ".30 Carbine"),
            ("Henry Big Boy X Model 45 (Long) Colt Blued/Black", ".45 Colt"),
            ("Enfield No.2 Revolver .38-200 (05160)", ".38 S&W"),
            ("DWM LUGER P08 1900 COMMERCIAL .30 LUGER SEMI AUTO PISTOL", ".30 Luger"),
        ],
    )
    def test_the_spellings_that_were_missed(self, title, wanted):
        assert extract_caliber(title) == wanted

    def test_a_dot_may_follow_a_letter(self):
        """With the dot there, nothing before it matters."""
        assert extract_caliber("Savage Impulse Hog Hunter.308win") == ".308 Winchester"

    def test_but_a_hyphen_rules_the_bare_number_out(self):
        """The "30-30" of a Winchester 94 is no .30 Carbine."""
        assert extract_caliber("Winchester Model 94 Lever Action 30-30 Carbine") == (
            ".30-30 Winchester"
        )

    def test_as_does_a_letter(self):
        assert extract_caliber("Colt M1940 Special Edition") != ".40 S&W"

    def test_and_45_auto_rim_is_its_own_cartridge(self):
        assert extract_caliber("S&W 1917 Revolver 45 Auto Rim") != ".45 ACP"


class TestTheArmoryForgivesSpacing:
    def test_a_space_where_a_number_meets_letters_is_optional(self):
        pattern = armory.caliber_pattern(["10mm Auto", "10mm"])
        assert all(pattern.search(text) for text in ("10 MM", "10mm", "10 mm auto"))
        assert not any(pattern.search(text) for text in ("110mm", "10mmX"))

    def test_the_leading_dot_is_optional_before_a_name(self):
        pattern = armory.caliber_pattern([".357 Magnum", ".357 Mag"])
        assert pattern.search("357 mag") and pattern.search("357MAG")

    def test_but_not_on_a_bare_number(self):
        """Without its dot, ".45" is a price or a year."""
        pattern = armory.caliber_pattern([".45"])
        assert pattern.search(".45") and not pattern.search("45")

    def test_nor_inside_a_longer_number(self):
        """It used to read "5.4mm" as a 4mm cartridge, and "13.5mm" as 5mm."""
        assert not armory.caliber_pattern(["4mm"]).search("5.4mm")
        assert not armory.caliber_pattern(["5mm"]).search("13.5mm")


class TestAnExactSpellingBelongsToItsRow:
    def registry(self):
        rows = [
            (".40", [".40", "40 Caliber"]),
            (".40 S&W", [".40 S&W", ".40S&W"]),
            (".32 ACP", [".32 ACP", "7.65mm Browning", "7.65mm"]),
            ("7.65 MM", ["7.65 MM"]),
        ]
        ordered = sorted(rows, key=lambda row: max(len(s) for s in row[1]))
        exact = {s.lower(): name for name, spellings in ordered for s in spellings}
        rules = [(name, armory.caliber_pattern(spellings)) for name, spellings in reversed(ordered)]
        return armory.CaliberRegistry(rules, exact)

    def test_40_sw_is_not_a_bare_40(self):
        """The alias "40 Caliber" on ".40" is the longer spelling, so its row was
        tried first, and its pattern matched inside ".40 S&W": 110 police
        trade-in Glocks and Sigs were filed under a bare .40."""
        assert self.registry().canonical(".40 S&W") == ".40 S&W"

    def test_a_row_of_its_own_keeps_its_string(self):
        """The ".32 ACP" row also reads "7.65 MM" now that spacing is forgiven, and
        "7.65 MM" is a row kept apart because it does not say which 7.65."""
        assert self.registry().canonical("7.65 MM") == "7.65 MM"

    def test_spacing_still_finds_the_row(self):
        assert self.registry().canonical("7.65 mm browning") == ".32 ACP"


class TestABoreStatedInWords:
    """561 production rifles and pistols had no caliber on 2026-09-29, and about
    230 of them stated one in words. 356 listings found a caliber this way and
    none lost one."""

    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            ("U.S. Caswell and Dodge Model 1798 Contract Flintlock Musket .69 Caliber", ".69"),
            ("A. WURFELEIN .40CAL OVERCOAT PERCUSSION PISTOL, ANTIQUE", ".40"),
            ("USED Remington 700 50 Cal Muzzle Loader", ".50"),
            ("Original British 18 Bore Single Barrel Percussion Fowling Piece", "18 Gauge"),
            ("Antique Parker Bros 10 GA GH Dbl Hammerless Grade 2 Shotgun 1889", "10 Gauge"),
            ("Original U.S. Springfield Trapdoor 32 gauge Saddle Ring Carbine", "32 Gauge"),
            ("Belgian Model 1844/1860 civil War imported Musket .72 caliber", ".72"),
            ("SHARPS Model 1851 BOX LOCK SADDLE RING CARBINE .52 Percussion", ".52"),
        ],
    )
    def test_the_ways_it_is_written(self, title, wanted):
        assert extract_caliber(title) == wanted

    @pytest.mark.parametrize(
        "title",
        [
            "Original Belgian Double Barrel 16 Bore Percussion Fowling Piece",
            "SPANISH MIQUELET SPORTING FLINTLOCK OF ABOUT 16 BORE",
            "J. COOPER 16-BORE PERCUSSION SHOTGUN",
        ],
    )
    def test_bore_and_gauge_are_one_measure(self, title):
        """Balls of the barrel's diameter to the pound, whichever word is used:
        a 16 bore fowler is a 16 gauge gun. ("16 gauge" itself is spelled
        "16-gauge" by the cartridge table, an alias of the same armory row.)"""
        assert extract_caliber(title) == "16 Gauge"

    def test_the_06_of_30_06_is_not_a_bore(self):
        assert extract_caliber("M1 Garand Rifle, Semi-Auto, 30-06 caliber") == ".30-06"

    def test_nor_is_a_bore_condition_grade(self):
        """ "9/10 bore" is how good the bore is, not how big."""
        assert extract_caliber("Unmarked rifle", "Bore shows light frosting, 9/10 bore.") is None

    def test_a_black_powder_cartridge_is_read_as_written(self):
        """ ".40-60-260" is a Colt Lightning cartridge no rule names; the
        description's passing ".40" had been the answer."""
        title = "Original U.S. Colt Large Frame Express Lightning .40-60-260 Pump Action Rifle"
        assert extract_caliber(title) == ".40-60"

    def test_but_a_range_of_years_is_not_one(self):
        assert extract_caliber("Civil War Era Carbine 1861-1865") is None


class TestTheVictorianCartridges:
    """The antique shops added in October 2026 had a caliber on three guns in
    four, against 98 in a hundred elsewhere. Most of the gap was rimfires and
    Winchester's old names for its centerfires -- "IN CALIBER 41 RF", "38 WCF"
    -- which nothing read, and Merz's habit of putting the word first."""

    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            ("COLT THIRD MODEL DERRINGER IN CALIBER 41 RF", ".41 RF"),
            ("Colt New Line .41 RF", ".41 RF"),
            ("S&W No. 2 Old Model Army 32 Rimfire, Possible Civil War", ".32 RF"),
            ("REMINGTON BEALS SINGLE SHOT RIFLE IN 32 LONG RF", ".32 RF"),
            ("Tycoon 5 Shot 38 Rimfire Spur Trigger Revolver", ".38 RF"),
            ("Remington Smoot #1 30 Rimfire Made 1876", ".30 RF"),
            ("SPORTERIZED BALLARD MILITARY RIFLE CHAMBERED IN 44 RF", ".44 RF"),
            ("FIRST GENERATION COLT SAA IN CALIBER 38 WCF", ".38-40 Winchester"),
            ("Winchester 1873 44 WCF", ".44-40 Winchester"),
            ("MARLIN MODEL 336SC SERIAL NUMBER 25091344 CALIBER 35 REMINGTON", ".35 Remington"),
            ("COLT MODEL 1860 ARMY PERCUSSION REVOLVER IN CALIBER 44", ".44"),
        ],
    )
    def test_the_ways_they_are_written(self, title, wanted):
        assert extract_caliber(title) == wanted

    def test_a_22_rimfire_is_left_alone(self):
        """On a Victorian revolver "22 RF" is a .22 Short more often than not,
        and the bare-.22 rule would have called it Long Rifle."""
        assert extract_caliber("S&W Model No. 1 Third Issue 22 RF Revolver") is None

    @pytest.mark.parametrize(
        "title",
        ["Springfield caliber 30-06 rifle", "Model 1903 cal. 7.62x39"],
    )
    def test_the_word_first_does_not_take_half_a_cartridge(self, title):
        assert extract_caliber(title) not in {".30", ".7"}

    def test_every_answer_is_a_row_in_the_shipped_armory(self):
        """A caliber the classifier names that the armory has no row for would
        be proposed as a new one on every scan."""
        shipped = yaml.safe_load(armory.SEED_FILE.read_text(encoding="utf-8"))
        names = {row["name"] for row in shipped["calibers"]}
        for name in (".30 RF", ".32 RF", ".38 RF", ".41 RF", ".44 RF", ".35 Remington"):
            assert name in names


class TestTheSixTheRecomputeGotWrong:
    """Six listings on 2026-09-29 where re-reading gave a different cartridge
    of the same bore: rules the classifier was missing."""

    def test_8x56mmr_with_the_mm_in_it(self):
        title = "FEG Budapest M95/30 Straight-Pull Bolt Action Carbine 8x56mmR (L2026-10888)"
        assert extract_caliber(title, "chambered in 8x50mmR") == "8x56mmR"

    def test_and_8x50_without_its_r(self):
        assert extract_caliber("B GRADE M95 STEYR MANNLICHER RIFLE 8X50") == "8x50mmR"

    def test_but_not_a_binocular(self):
        assert extract_caliber("Military 8x50 binoculars with case") != "8x50mmR"

    def test_gp90_is_7_5x53_5(self):
        description = (
            "chambered in GP90 (7.5×53.5 Swiss). IT IS NOT SAFE TO ATTEMPT TO FIRE GP11 "
            "(7.5×55 Swiss)."
        )
        assert extract_caliber("Swiss Model 1893 Cavalry Carbine", description) == "7.5x53.5mm"

    def test_the_442_in_the_title_beats_the_455_the_description_rules_out(self):
        title = "Original British Victorian Prototype .442 Centerfire Double Action Revolver"
        description = "too long for both .476 Enfield or .455 Webley, so we assume .442 Webley"
        assert extract_caliber(title, description) == ".442 Webley"

    def test_a_police_marking_is_no_cartridge(self):
        assert extract_caliber("MAUSER 1914 POLICE", "L.K.476 police marking") != ".476 Enfield"

    def test_41_magnum_is_its_own(self):
        assert extract_caliber("Smith & Wesson Model 57 .41 Magnum N-Frame") == ".41 Magnum"

    def test_the_martini_henry_is_one_cartridge(self):
        assert extract_caliber("1887 Zulu War British Martini Henry .577-450") == (
            ".577/450 Martini-Henry"
        )


class TestAMeasurementIsNotACaliber:
    """``12.25"`` is a barrel length. The table's ``.25`` read it as a .25 ACP
    on an 18th-century Danish flintlock pistol (2026-10-09)."""

    @pytest.mark.parametrize(
        "text",
        ['approx. 12.25" round 69 caliber barrel', "a 14.22 inch barrel", "weighs 10.38 lbs"],
    )
    def test_a_decimal_number_names_no_cartridge(self, text):
        assert extract_caliber("Antique flintlock", text) in (None, ".69")

    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            ("Bayard .25 pocket pistol", ".25 ACP"),
            ("Colt Police Positive .38 Special", ".38 Special"),
            ("Lee-Enfield No. 4, cal .303", ".303 British"),
            ("FN 1910 6.35mm", ".25 ACP"),
        ],
    )
    def test_while_a_written_caliber_still_reads(self, title, wanted):
        assert extract_caliber(title) == wanted
