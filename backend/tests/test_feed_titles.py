"""Titles from the wholesale feeds, and the shelf they are filed on.

DeLeon, Locked & Loaded, Florida Guns, Frisco and G4G title their new guns
from distributors' catalogs: "GLK 17CG5V 9MM PST 17RD FS TL", "Smith & Wesson
150712 686 Plus Deluxe", "CENTURY AP5SD 9MM NATO PISTOL". The armory knew the
Glock 17, the 686 and the AP5 and matched none of them, and their 19,500
listings took the share of guns matched to a model from 83% to 61%
(2026-11-03). These pin the fallback pass that reads them, the units it must
not swallow, and the rule that keeps it from changing any match that already
works.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmKind, FirearmModel
from app.services import armory, classify, manufacturers
from app.services.classify import finer_kind, form_in_section


def _model(name: str, aliases: str | None, kind: FirearmKind) -> FirearmModel:
    return FirearmModel(name=name, aliases=aliases, kind=kind, status=ArmoryStatus.APPROVED)


@pytest.fixture
def catalog(clean_db):
    rows = {
        "glock17": _model("Glock 17", "Glock G17", FirearmKind.PISTOL),
        "glock19": _model("Glock 19", "Glock G19", FirearmKind.PISTOL),
        "glock19x": _model("Glock 19X", None, FirearmKind.PISTOL),
        "ap5": _model("Century Arms AP5", "AP5", FirearmKind.PISTOL),
        "686": _model("Smith & Wesson Model 686", "Smith & Wesson 686", FirearmKind.REVOLVER),
        "python": _model("Colt Python", None, FirearmKind.REVOLVER),
        "rhino": _model("Chiappa Rhino", "Rhino", FirearmKind.REVOLVER),
        "duty": _model("Tisas Arms 1911", "DUTY 9", FirearmKind.PISTOL),
        "sar9": _model("SAR9", "SAR 9", FirearmKind.PISTOL),
    }
    clean_db.add_all(rows.values())
    clean_db.commit()
    armory.invalidate()
    manufacturers.invalidate()
    yield rows
    armory.invalidate()
    manufacturers.invalidate()


def _matched(session, title: str) -> str | None:
    return armory.match(session, title).model


class TestTheLoosenedTitle:
    def test_an_abbreviated_maker_is_spelled_out(self):
        assert armory.loosened("CLT PYTHON 357MAG 6 SS") == "Colt PYTHON 357MAG 6 SS"
        assert armory.loosened("GLK 17CG5V 9MM PST").startswith("Glock 17CG5V")

    def test_only_as_the_first_word(self):
        """A bare "CA" elsewhere is a state, not Charter Arms."""
        assert armory.loosened("Glock 19 CA Compliant") == "Glock 19 CA Compliant"

    def test_the_company_word_and_the_stock_number_go(self):
        assert armory.loosened("Chiappa Firearms 340285 Rhino 30DS 357 Mag") == (
            "Chiappa Rhino 30DS 357 Mag"
        )
        assert armory.loosened("Colt Mfg O1082RGCCU Government 9mm") == "Colt Government 9mm"

    def test_a_model_number_is_not_a_stock_number(self):
        """Fewer than four digits, or under five characters: "P365XL",
        "1911" and "M&P9" are what the gun is called."""
        for word in ("P365XL", "1911", "M&P9", "VP9A1X"):
            assert not armory._is_stock_number(word)
        for word in ("150712", "O1082RGCCU", "2942031UL"):
            assert armory._is_stock_number(word)

    def test_nothing_to_forgive_leaves_it_alone(self):
        assert armory.loosened("Glock 19 Gen 5 9mm") == "Glock 19 Gen 5 9mm"


class TestMatchingFeedTitles:
    def test_a_stock_number_between_maker_and_model(self, clean_db, catalog):
        assert _matched(clean_db, "Smith & Wesson 150712 686 Plus Deluxe 357 Magnum") == (
            "Smith & Wesson Model 686"
        )

    def test_an_abbreviated_maker(self, clean_db, catalog):
        assert _matched(clean_db, "CLT PYTHON 357MAG 2.5 MATTE SS") == "Colt Python"

    def test_letters_run_onto_the_model_number(self, clean_db, catalog):
        assert _matched(clean_db, "CENTURY AP5SD 9MM NATO PISTOL") == "Century Arms AP5"
        assert _matched(clean_db, "GLK 17CG5V 9MM PST 17RD FS TL") == "Glock 17"

    def test_but_not_a_unit_or_a_cartridge(self, clean_db, catalog):
        """ "DUTY 9" is a Tisas spelling, and "Duty 9mm" is a Ruger's title.
        Letting "mm" count as a variant code filed the Ruger as a Tisas."""
        assert _matched(clean_db, "Ruger 8638 American Pistol Duty 9mm Luger") is None

    def test_an_exact_match_still_wins(self, clean_db, catalog):
        """The fallback only fills blanks: a Glock 19X the armory knows is a
        19X, not a Glock 19 with an X run on."""
        assert _matched(clean_db, "Glock 19X 9mm Coyote") == "Glock 19X"
        assert _matched(clean_db, "Glock 19 Gen 5 9mm") == "Glock 19"


class TestTheSar9IsAPistol:
    def test_it_is_not_read_as_a_rifle(self):
        """ "sar-?\\d" was written for the Romanian SAR-1/2/3 and took the SAR9
        too, which then contradicted its own model."""
        assert classify.stated_kind("SAR9 9mm") != "rifle"
        assert classify.stated_kind("Romanian Cugir SAR-1 AKM 7.62x39") == "rifle"

    def test_and_so_it_matches(self, clean_db, catalog):
        assert _matched(clean_db, "SAR SAR9 SOCOM HGA 9MM 5.2 IN THREADED B") == "SAR9"


class TestTheShelfSaysTheForm:
    def test_pistols_and_revolvers(self):
        assert form_in_section("Pistols", is_pistol=True) == "pistol"
        assert form_in_section("Revolvers", is_pistol=True) == "revolver"
        assert form_in_section("Semi-Auto Handguns", is_pistol=True) == "pistol"
        assert form_in_section("Derringers", is_pistol=True) == "pistol"

    def test_a_section_naming_both_or_neither_says_nothing(self):
        assert form_in_section("Pistols & Revolvers", is_pistol=True) is None
        assert form_in_section("Handguns", is_pistol=True) is None

    def test_the_coarse_flags_must_agree(self):
        """A rifle filed under "Pistols" is a mistake on the shelf."""
        assert form_in_section("Pistols", is_rifle=True) is None

    def test_the_titles_ignition_still_applies(self):
        assert form_in_section("Black Powder Pistols", "Flintlock Pistol .54", is_pistol=True) == (
            "flintlock_pistol"
        )

    def test_it_ranks_last(self):
        """The title's own word beats the shelf; the shelf fills a blank."""
        assert finer_kind(None, None, "revolver", "pistol") == "revolver"
        assert finer_kind(None, None, None, "revolver") == "revolver"
        assert finer_kind(FirearmKind.PERCUSSION_REVOLVER, None, None, "pistol") == (
            "percussion_revolver"
        )


@pytest.fixture
def spaced(clean_db):
    rows = {
        "p15": _model("Kel-Tec P-15", "P-15", FirearmKind.PISTOL),
        "security9": _model("Ruger Security-9", "Security-9", FirearmKind.PISTOL),
        "xd40": _model("XD-40", "XD 40", FirearmKind.PISTOL),
        "tpr9": _model("Bersa TPR9", "TPR9", FirearmKind.PISTOL),
        "tactical": _model("XD40 Tactical", None, FirearmKind.PISTOL),
        "mod2": _model("U.S. MOD 2", "MOD 2", FirearmKind.PISTOL),
        "mp5": _model("MP5", None, FirearmKind.PISTOL),
        "mc9": _model("MC9", None, FirearmKind.PISTOL),
    }
    rows["tactical"].position = 1  # tried before the XD-40
    clean_db.add_all(rows.values())
    clean_db.commit()
    armory.invalidate()
    yield rows
    armory.invalidate()


class TestTheGapBetweenLettersAndNumber:
    """ "XD-40", "XD40" and "XD 40" are one pistol (2026-11-05): 152 of
    production's unmatched guns matched once the gap was optional."""

    def test_a_hyphen_or_space_may_be_missing(self, clean_db, spaced):
        assert _matched(clean_db, "KEL P15 9MM 4 TAN/BLK POLY 15RD OPTIC") == "Kel-Tec P-15"
        assert _matched(clean_db, "Ruger 3819 Security9 9mm Luger DAO") == "Ruger Security-9"
        assert _matched(clean_db, "Used Springfield XD40 .40 S&W") == "XD-40"

    def test_or_present_where_the_spelling_has_none(self, clean_db, spaced):
        assert _matched(clean_db, "Bersa TPR-9 9mm 17rd") == "Bersa TPR9"

    def test_with_the_suffix_pass_too(self, clean_db, spaced):
        assert _matched(clean_db, "Kel-Tec P15BLKOPTIC Compact 9mm") == "Kel-Tec P-15"

    def test_generic_letters_keep_their_spacing(self, clean_db, spaced):
        assert _matched(clean_db, "XD-S MOD2 45ACP 3.3in 5+1 OSP") is None

    def test_the_number_does_not_run_into_a_cartridge(self, clean_db, spaced):
        assert _matched(clean_db, "S&W MP 5.7 5 22R FDE OR NTS TB") is None
        assert _matched(clean_db, "Used GIRSAN REGARD MC 9X19 4.7in GOLD") is None

    def test_an_exact_match_still_wins(self, clean_db, spaced):
        """The spaced pass runs last. "XD40 Tactical" is tried first and would
        take this title spaced, but the XD-40 matches it exactly."""
        assert _matched(clean_db, "XD-40 Tactical .40 S&W") == "XD-40"
        assert _matched(clean_db, "XD40 Tactical .40 S&W") == "XD40 Tactical"

    def test_a_row_with_nothing_to_loosen_has_no_spaced_pattern(self):
        assert armory._spaced_pattern(["Garand", "M1 Garand"]).pattern  # M|1 loosens
        assert armory._spaced_pattern(["Garand"]) is None
        assert armory._spaced_pattern(["MOD 2"]) is None
        assert armory._spaced_pattern(["M1867", "M-1849"]) is None
