"""Swords, sabers and suppressors: the head nouns that could never be found.

`_HEAD_NOUN_ACCESSORIES` has listed swords, sabers, cutlasses, suppressors and
silencers since it was written, and every one of those entries was a dead
letter. That constant filters a word the scan has *already found*, and the
scan runs over `_ACCESSORY_NOUN`, which did not contain any of them -- so the
veto that outranks the vendor's category never got a word to veto.

What it cost: a Civil War cavalry saber filed by its vendor under "M1 Garand &
U.S. Rifles" was stored as a rifle, and so was a Gemtech suppressor under
"Used & Collectible Firearms". The category promoted both.
"""

from __future__ import annotations

import pytest

from app.services.classify import classify_firearm, enrich

#: The categories these listings actually carried. The point of every test
#: here is that the veto has to beat them.
RIFLE_SECTION = "M1 Garand & U.S. Rifles"
FIREARM_SECTION = "Used & Collectible Firearms"


def _is_firearm(title: str, category: str | None = None) -> bool:
    found = enrich(title, None, None, category=category)
    return bool(found["is_rifle"] or found["is_pistol"])


class TestAnEdgedWeaponIsNotAFirearm:
    @pytest.mark.parametrize(
        "title",
        [
            "Original U.S. Civil War Model 1860 Light Cavalry Saber with Scabbard",
            'Original U.S Civil War German-Made M-1840 "Wrist Breaker" Heavy Cavalry Saber',
            "British Pattern 1796 Heavy Cavalry Sword",
            "French Naval Boarding Cutlass",
        ],
    )
    def test_even_when_the_vendor_filed_it_under_rifles(self, title):
        assert _is_firearm(title, RIFLE_SECTION) is False


class TestASuppressorIsNotAFirearm:
    def test_a_dotted_caliber(self):
        assert _is_firearm("LEO Trade-In OSS HXQD .30cal Suppressor", "Police Trade-Ins") is False

    def test_and_one_written_without_the_dot(self):
        """ "22" here is a bore, not a count of suppressors -- but the attached
        part rule reads a bare one-or-two-digit number as a count, so this
        stripped the only noun in the title and left "Gemtech SeaHunter" to be
        filed as a rifle. The dotted spelling was safe all along, because a
        leading "." fails the introducer's lookbehind."""
        assert _is_firearm("Gemtech SeaHunter 22 Suppressor", FIREARM_SECTION) is False

    def test_a_silencer_reads_the_same_way(self):
        assert _is_firearm("SilencerCo Omega 9K Silencer", FIREARM_SECTION) is False


class TestButTheGunItIsFittedToStillIs:
    """The other direction, which is where a rule like this does its damage."""

    def test_a_rifle_with_a_saber_bayonet_lug(self):
        """The regression this guard exists for. "Saber" landed before
        "bayonet" in the scan, took the head-noun slot, and turned a Civil War
        rifle into an edged weapon the moment these words were added. A saber
        bayonet is a bayonet, which the vocabulary already covered.
        """
        title = (
            "Original U.S. Civil War Model 1841 Mississippi Rifle by E. Remington & Sons "
            "of Herkimer in Original .54 Caliber with Saber Bayonet Lug, 1851 Lock"
        )
        assert classify_firearm(title) == (True, False)

    def test_a_pistol_with_suppressor_sights(self):
        """ "Suppressor" as an adjective on a sight, with the gun named first."""
        title = "PD Trade | Glock 34 Gen5 MOS | 9mm | Suppressor Sights"
        assert _is_firearm(title, "Police Trade-Ins") is True

    def test_a_pistol_sold_with_a_faux_suppressor(self):
        title = "Beretta M-71 Pistol .22LR W / Faux Suppressor, Semi-Auto"
        assert _is_firearm(title, FIREARM_SECTION) is True

    def test_a_rifle_with_a_sword_bayonet(self):
        title = "Chassepot Model 1866 Rifle with Sword Bayonet"
        assert classify_firearm(title) == (True, False)
