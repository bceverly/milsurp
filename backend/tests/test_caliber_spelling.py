"""A cartridge is recognized however a dealer spaces or dots it.

"357 mag", "45acp", "40 S&W", "10 MM": the same cartridges as ".357 Magnum",
".45 ACP", ".40 S&W" and "10mm", and until 2026-09-28 none of them was read.
Measured on production's 12,367 active listings, the classifier found a caliber
for 225 more and lost none.
"""

from __future__ import annotations

import pytest

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
