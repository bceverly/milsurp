"""Things that are not guns, arriving under Rifles.

Three separate reports from the running catalog, one root cause each.

**A bayonet whose prose names the gun it fits.** "16003 M4 bayonet with M8A1
scabbard ... made to supply to our allies using the M1 and M2 carbines" was a
rifle, because ``enrich`` only asked the bayonet question about a listing that
was already neither a rifle nor a handgun -- and the description had already
made it one. eBayonet sells bayonets and nothing else, so the vendor's own
section is the answer and second-guessing it from the title is the bug.

**A lot of parts sold as one item.** "AK-100 Series Fire Control Package",
"Spare Parts Set", "Rifle Parts Selection, NO Barrel". Parts, not a parts kit
-- a kit is a whole firearm minus its serialized part -- and certainly not a
rifle, but the title names the gun they fit and that is what was read.

**A magazine for a gun the vocabulary knows.** The magazine rule gave up as
soon as the title named a model, which is precisely what these titles are for:
"East German Galil / Valmet Bakelite 5.56/223 30rd Magazine".
"""

from __future__ import annotations

import pytest

from app.services.classify import enrich


def kind(title, category=None, description=None):
    found = enrich(title=title, category=category, description=description)
    for flag in ("is_rifle", "is_pistol", "is_bayonet", "is_parts_kit"):
        if found[flag]:
            return flag[3:]
    return "other"


class TestTheVendorsSectionSaysBayonet:
    """757 listings sit in a bayonet-named section across four vendors and
    every one of them is a bayonet. 31 were filed under Rifles and 18 under
    nothing at all."""

    @pytest.mark.parametrize(
        "title",
        [
            (
                "16003 M4 bayonet with M8A1 scabbard, made to supply allies "
                "using the M1 and M2 carbines."
            ),
            (
                "18942 M1885 Kropatschek bayonet with scabbard STEYR 1886 Standard "
                "full length rifle bayonet. Not Carbine or Short Rifle."
            ),
            "17430 PAKISTANI FAKE No.5 Jungle Carbine Bayonet with scabbard.",
        ],
    )
    def test_the_section_decides_it(self, title):
        assert kind(title, category="Bayonet") == "bayonet"

    def test_a_kit_that_includes_one_is_still_a_kit(self):
        """The buckets partition the catalog, and the thing being sold is the
        kit: "Polish Radom Military Collectors Package - Circle 11 AKM Parts
        Kit ... + Circle 11 Bayonet & Circle 11 Magazine"."""
        title = "Polish Radom Military Collectors Package - Circle 11 AKM Parts Kit + Bayonet"
        assert kind(title, category="Bayonets") == "parts_kit"

    def test_the_section_alone_is_not_enough(self):
        """DuPage Trading file bare M8A1 scabbards and a fighting knife under
        theirs, so the heading proposes and the listing has to corroborate --
        the same discipline the parts-kit rule uses, and for the same reason.

        The cost is that bayonet *accessories* -- a P37 frog, a lug adapter --
        stay out of the bucket. eBayonet sells nothing but bayonets and their
        fittings, so arguably they belong in it; DuPage's equivalents are
        deliberately excluded today, and making them agree is a separate
        decision from this bug.
        """
        assert kind("NORWEGIAN M8A1 SCABBARD", category="Bayonets") == "other"

    def test_a_rifle_in_a_rifle_section_is_unaffected(self):
        assert kind("Springfield Trapdoor Rifle w/ Ramrod Bayonet", category="Rifles") == "rifle"


class TestALotOfParts:
    @pytest.mark.parametrize(
        "title",
        [
            "AK-100 Series Fire Control Package - IGLIM",
            "AK-100 Series Rear Sight Package- IGLIM",
            "AK-100 Series Front End Package - IGLIM",
            "AK-103 7.62x39 Core Parts Package - IGLIM",
            "Dominican Republic San Cristobal Carbine Spare Parts Set *Good*",
            "French MAS 36 Rifle Parts Selection, NO Barrel, 7.5X54, *Good*",
        ],
    )
    def test_it_is_not_the_rifle_it_names(self, title):
        assert kind(title) == "other"

    def test_nor_is_it_promoted_to_a_parts_kit(self):
        """A kit is a whole firearm minus the serialized part. A handful of
        fire-control bits is not one, and the Parts kit bucket is watched by
        people who want the former."""
        assert kind("AK-100 Series Fire Control Package - IGLIM") == "other"

    def test_a_real_parts_kit_still_is_one(self):
        assert kind("Yugoslav M70 AB2 Underfolder Parts Kit") == "parts_kit"

    def test_a_gun_that_comes_with_parts_is_still_the_gun(self):
        """The regression this nearly shipped with. "w/" is the difference
        between a musket sold with its trigger group and a trigger group."""
        title = (
            "Ishapore Enfield No.1 MK.III 410 Musket w/ Complete Trigger Group, "
            "Rear Sight, and Frontsight"
        )
        assert kind(title) == "rifle"


class TestAMagazineForAGunTheVocabularyKnows:
    def test_naming_the_rifle_does_not_make_it_one(self):
        title = "East German Galil / Valmet Bakelite 5.56/223 30rd Magazine, Collector New"
        assert kind(title) == "other"

    def test_a_magazine_that_names_no_model_was_always_caught(self):
        assert kind("CZ82 9x18 Makarov - 12RD Magazine") == "other"

    @pytest.mark.parametrize(
        "title",
        [
            "Ruger Mini-14 Ranch Rifle 5.56 with 20 Round Magazine",
            "Springfield M1A Rifle .308, 22in Barrel, 10rd Magazine, Walnut Stock",
            "Mas 49/56, 7.5MM French, Semi-Auto Rifle W / 10 Round Removable Box Mag",
        ],
    )
    def test_a_rifle_listing_its_magazine_is_still_a_rifle(self, title):
        """The whole risk in this one: a magazine is a specification on most
        rifle titles and the product on a few."""
        assert kind(title) == "rifle"
