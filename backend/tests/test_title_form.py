"""What a listing's own title says the firearm is.

The third source of Item.kind, after the armory model and the vendor's own
category, and the one that was missing: 1,548 active firearms carried no kind
while 835 of them said "Revolver", "Carbine" or "Rifle" in plain text. Nothing
read the title, because finer_kind only ever consulted the curated model and
the vendor's category column.

It is deliberately last. Where the title disagrees with the other two it is
usually the loose one -- "German K98 8mm Rifle" is a Karabiner, and the model
row knows that -- so this fills blanks and never overrules.
"""

from __future__ import annotations

import pytest

from app.models import FirearmKind
from app.services.classify import _COMBINED_KINDS, finer_kind, form_in_title


class TestTheWordInTheTitle:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("First Model Remington Beals M1857 Revolver - .31 Cal", "revolver"),
            ("CZ75BD Pistol 9mm Luger with FREE holster", "pistol"),
            ("ALPINE MODEL CUSTOM HUNTING RIFLE, CAL. 30-06", "rifle"),
            ("Hungarian 48.M Bolt Action Carbine 7.62x54R", "carbine"),
            ("Original British 13 Bore Double Barrel Shotgun", "shotgun"),
            ("North African Moroccan Musket", "rifle"),
        ],
    )
    def test_a_title_naming_one_form_answers_with_it(self, title, expected):
        assert form_in_title(title, is_rifle=True) == expected

    def test_a_title_naming_no_form_says_nothing(self):
        """ "Romanian Tokarev Stripped Frame" needs model knowledge, which is
        the armory's job, not this function's."""
        assert form_in_title("Romanian Tokarev Stripped Frame", is_rifle=True) is None
        assert form_in_title(None) is None
        assert form_in_title("") is None


class TestTheMoreSpecificWordWins:
    def test_carbine_beats_rifle(self):
        """Both are long guns, and a carbine is not a short rifle -- a Trapdoor
        Carbine and a Trapdoor Rifle are different guns. See FirearmKind."""
        title = "PD Trade | Colt M4 Carbine | LE6920 | 5.56 Nato | Rifle"
        assert form_in_title(title, is_rifle=True) == "carbine"

    def test_revolver_beats_pistol(self):
        assert form_in_title("Colt Python Revolver Pistol", is_pistol=True) == "revolver"


class TestThirtyCarbineIsACartridge:
    """The trap the whole rule turns on.

    ".30 Carbine" is a cartridge, and stripping the word wherever it appears
    would be wrong in the commonest direction: an M1 Carbine chambered in it is
    still a carbine. Only an occurrence a number introduces is discounted.
    """

    def test_a_revolver_in_thirty_carbine_is_still_a_revolver(self):
        title = "Awesome Ruger Blackhawk Revolver Rare 3 Screw 30 Carbine 1968"
        assert form_in_title(title, is_pistol=True) == "revolver"

    def test_but_a_carbine_in_thirty_carbine_is_still_a_carbine(self):
        assert form_in_title("US M1 Carbine .30 Carbine WWII", is_rifle=True) == "carbine"

    def test_and_the_cartridge_alone_answers_nothing(self):
        assert form_in_title("Winchester .30 Carbine ammunition tin", is_rifle=True) is None


class TestAWordFromEachFamily:
    """A title naming a long gun and a handgun is not an answer by itself."""

    def test_the_coarse_flags_break_the_tie(self):
        title = "Rare c1855 Smith & Wesson VOLCANIC No. 1 Pistol .31 Rifle"
        assert form_in_title(title, is_pistol=True, is_rifle=False) == "pistol"
        assert form_in_title(title, is_rifle=True, is_pistol=False) == "rifle"

    def test_but_with_both_flags_set_it_stays_quiet(self):
        """A parts kit can be a handgun and a long gun at once; guessing which
        form the words meant would be inventing an answer."""
        title = "ENFIELD Rifle and Pistol parts"
        assert form_in_title(title, is_rifle=True, is_pistol=True) is None

    def test_and_with_neither(self):
        assert form_in_title("Rifle and Pistol", is_rifle=False, is_pistol=False) is None


class TestIgnitionSharpensTheForm:
    """FirearmKind is really ignition by form, so a title naming both should
    land in the finer bucket rather than the plain one."""

    def test_percussion_and_revolver_make_percussion_revolver(self):
        title = "Original U.S. Civil War Rogers & Spencer Army Model .44 Percussion Revolver"
        assert form_in_title(title, is_pistol=True) == "percussion_revolver"

    def test_flintlock_and_musket_make_flintlock_rifle(self):
        title = "North African Moroccan Flintlock Musket"
        assert form_in_title(title, is_rifle=True) == "flintlock_rifle"

    def test_a_pair_the_enum_has_no_slot_for_keeps_the_plain_form(self):
        """There is no percussion_shotgun, and inventing one would store a
        value the column cannot hold."""
        title = "Original British 13 Bore Double Barrel Percussion Shotgun"
        assert form_in_title(title, is_rifle=True) == "shotgun"

    def test_an_ignition_the_enum_ignores_is_ignored(self):
        """Matchlock and wheellock have no slot; seven listings name one."""
        assert form_in_title("Japanese Matchlock Rifle", is_rifle=True) == "rifle"


class TestTheCombinedKindsAgreeWithTheEnum:
    def test_every_pair_spelled_here_is_a_real_firearm_kind(self):
        """_COMBINED_KINDS is written out rather than imported, because
        classify.py deliberately depends on nothing but the standard library.
        This is what stops the two drifting apart."""
        values = {kind.value for kind in FirearmKind}
        assert values >= _COMBINED_KINDS

    def test_and_every_combined_member_of_the_enum_is_spelled_here(self):
        """The other direction: adding percussion_shotgun to the enum without
        adding it here would silently keep storing the plain form."""
        combined = {
            kind.value
            for kind in FirearmKind
            if kind.value.startswith(("flintlock_", "percussion_"))
        }
        assert combined == set(_COMBINED_KINDS)


class TestWhereItSitsInThePrecedence:
    def test_the_model_still_wins(self):
        """ "German K98 8mm Rifle" is a Karabiner. The curated row knows; the
        title is the loose one, and must not overrule it."""
        assert finer_kind(FirearmKind.CARBINE, None, "rifle") == "carbine"

    def test_the_vendors_category_still_beats_the_title(self):
        assert finer_kind(None, "Revolver", "pistol") == "revolver"

    def test_but_the_title_answers_when_neither_did(self):
        assert finer_kind(None, None, "revolver") == "revolver"

    def test_a_category_that_names_no_form_falls_through_to_the_title(self):
        """Simpson's "Combination" and "Gun Deal" name no form, and a coarse
        "Handgun" is not in the map either -- so a title saying "Revolver"
        gets its say rather than being blocked by a word that answered nothing.
        """
        assert finer_kind(None, "Combination", "revolver") == "revolver"
        assert finer_kind(None, "Handgun", "revolver") == "revolver"

    def test_and_nothing_at_all_is_still_nothing(self):
        assert finer_kind(None, None, None) is None
