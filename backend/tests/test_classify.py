"""The heuristics that turn listing prose into structured fields."""

from __future__ import annotations

import pytest

from app.services import classify
from app.services.classify import (
    classify_firearm,
    enrich,
    extract_bore_condition,
    extract_caliber,
    extract_country,
    extract_manufacturer,
)


class TestCaliber:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Mosin Nagant M91/30 7.62x54R", "7.62x54R"),
            ("German K98 Mauser rifle", "8mm Mauser"),
            ("Lee-Enfield No. 4 Mk I", ".303 British"),
            ("M1 Garand Springfield", ".30-06"),
            ("M1 Carbine, US", ".30 Carbine"),
            ("Russian SKS carbine", "7.62x39mm"),
            ("Walther PP pistol", ".32 ACP"),
            ("Makarov PM", "9x18 Makarov"),
            ("Swiss Schmidt-Rubin K31", "7.5x55 Swiss"),
            ("Japanese Arisaka Type 99", "7.7x58mm Arisaka"),
        ],
    )
    def test_model_implies_caliber(self, title, expected):
        assert extract_caliber(title) == expected

    def test_carcano_never_becomes_30_06(self):
        """Carcano descriptions routinely mention other calibers in passing."""
        description = "Italian rifle. Comparable in power to the .30-06 Springfield."
        assert extract_caliber("Carcano M91 rifle", description) == "6.5x52mm Carcano"

    def test_carcano_7_35_variant(self):
        assert extract_caliber("Carcano M38 7.35x51 short rifle") == "7.35x51mm Carcano"

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Shotgun, 12 gauge", "12-gauge"),
            ("Shotgun, 20 guage", "20-gauge"),  # vendor misspelling
            ("Pistol in 9x19", "9mm"),
            ("Colt 1911 .45 ACP", ".45 ACP"),
        ],
    )
    def test_explicit_calibers_normalized(self, title, expected):
        assert extract_caliber(title) == expected

    @pytest.mark.parametrize(
        "title",
        ["Leather ammo pouch", "Cleaning kit", "Stripper clip, 5 round", "Steel helmet"],
    )
    def test_accessories_get_no_caliber(self, title):
        assert extract_caliber(title) is None

    def test_firearm_bundled_with_accessory_keeps_caliber(self):
        """'with holster' marks a bundle, not an accessory listing."""
        assert extract_caliber("Makarov pistol with original holster") == "9x18 Makarov"

    def test_empty_input(self):
        assert extract_caliber("") is None


class TestABoreWrittenOnItsOwn:
    """The number without the cartridge, which is how half the catalog reads.

    Legacy Collectibles describe a percussion revolver as "- .31" and a Yugoslav
    Mauser as "8mm", and neither used to produce a caliber at all: 78 of their
    listings had an empty caliber column while the number sat in the title.
    """

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            # 8mm on a Mauser-pattern rifle, which is what a bare 8mm means
            # once Lebel and Nambu have had their turn.
            ("Yugoslavian M48 Bolt Action Rifle 8mm (L2026-02099)", "8mm Mauser"),
            ("Late War Walther K43 Semi-Auto Rifle 8mm", "8mm Mauser"),
            ("WWII German SS Issued converted Gew 98 8mm (R42670)", "8mm Mauser"),
            # Inches, the percussion end of the catalog.
            ("First Model Remington Beals M1857 Revolver - .31 Cal", ".31"),
            ("Factory-Nickel Colt M1877 Thunderer Revolver - .41", ".41"),
            ("US Civil War Burnside Saddle Ring Carbine - .54 Burnside", ".54"),
            ("Antique Webley W.G. Target Model 1892 Revolver - .450 Mark I", ".450"),
            # Millimeters with no case length.
            ("AUGUST MENZ LILIPUT MODEL 1925, 4.25MM SEMI AUTO PISTOL", "4.25mm"),
        ],
    )
    def test_the_number_is_read(self, title, expected):
        assert extract_caliber(title) == expected

    def test_a_named_cartridge_still_wins(self):
        """The bare number is the weaker statement, so it is tried last."""
        assert extract_caliber("German K98 Mauser 7.92x57") == "8mm Mauser"
        assert extract_caliber("Colt 1911 .45 ACP") == ".45 ACP"

    def test_bare_8mm_never_takes_a_lebel_or_a_nambu(self):
        assert extract_caliber("Berthier Carbine 8mm Lebel") == "8mm Lebel"
        assert extract_caliber("Japanese Type 14 Nambu Pistol 8mm") == "8mm Nambu"

    def test_the_cents_of_a_price_are_not_a_caliber(self):
        """Which is why the list of bores is closed rather than any two digits:
        a description carrying "$1,250.50" would otherwise read as a .50."""
        assert extract_caliber("Antique Revolver, reduced from $1,250.50") is None

    def test_nor_is_a_number_too_big_to_be_a_small_arm(self):
        assert extract_caliber("Photographed with a 35mm lens") is None
        assert extract_caliber("Bofors 40mm anti-aircraft gun") is None

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Winchester Model 1873 .44-40 - 1882 mfg", ".44-40 Winchester"),
            ("Springfield Trapdoor Rifle .45-70", ".45-70 Government"),
            ("Colt Single Action Army .32-20", ".32-20 Winchester"),
            ("Winchester Model 1892 .38-40", ".38-40 Winchester"),
            ("Krag-Jorgensen Rifle .30-40 Krag", ".30-40 Krag"),
        ],
    )
    def test_a_hyphenated_name_keeps_both_halves(self, title, expected):
        """Bore and powder charge, and the second number is what says which
        cartridge it is. ".44-40" read as a bare .44, or ".32-20" read by the
        ".32" rule as a .32 ACP, throws that away."""
        assert extract_caliber(title) == expected


class TestAnAccessoryWordInsideAnotherWord:
    """ "spring" is inside "Springfield", and that was not a hypothetical.

    The accessory list was matched as substrings, so every Springfield in the
    catalog was an accessory and never got a caliber — 23 of the 28 there.
    """

    def test_springfield_is_not_a_spring(self):
        assert extract_caliber("Springfield Model 1903 .30-06") == ".30-06"
        assert extract_caliber("Springfield Trapdoor .45-70") == ".45-70 Government"

    def test_nor_is_recovered_a_cover(self):
        assert extract_caliber("M1 Garand recovered from a barn, .30-06") == ".30-06"

    def test_but_a_spring_is_still_a_spring(self):
        assert extract_caliber("Recoil spring assembly, .45 ACP") is None
        assert extract_caliber("Canvas ammo pouch, 8mm") is None

    def test_an_optic_is_named_by_what_it_ends_in(self):
        """Which is why "scope" is the one keyword still allowed a prefix: a
        telescope and a periscope are the same kind of thing as a scope and
        neither of them is spelled like one."""
        assert extract_caliber("Carl Zeiss Jena 10x60 Marina Romana Periscope") is None
        assert extract_caliber("ZF41 telescope, 8mm") is None


class TestClassification:
    @pytest.mark.parametrize(
        "title",
        ["Mosin Nagant M91/30 rifle", "M1 Garand", "SKS carbine", "Lee-Enfield No.4"],
    )
    def test_rifles(self, title):
        is_rifle, is_pistol = classify_firearm(title, price=500.0)
        assert is_rifle and not is_pistol

    @pytest.mark.parametrize(
        "title",
        ["Luger P08 pistol", "Makarov PM", "Tokarev TT-33", "Webley revolver"],
    )
    def test_pistols(self, title):
        is_rifle, is_pistol = classify_firearm(title, price=500.0)
        assert is_pistol and not is_rifle

    @pytest.mark.parametrize(
        "title",
        [
            "Rifle cleaning kit",
            "Scope mount for Mauser",
            "Pistol grip, polymer",
            "Bayonet, German",
            "Tripod for MG34",
        ],
    )
    def test_accessories_are_neither(self, title):
        assert classify_firearm(title, price=200.0) == (False, False)

    def test_a_cheap_thing_that_does_not_say_what_it_is_is_not_a_firearm(self):
        """The price floor keeps accessories out of the firearm filters.

        It used to be absolute — "nothing under $70 is a firearm, whatever the
        title claims" — and that was wrong in the one direction that matters.
        On a flyer read by OCR the price is the *least* reliable field on the
        page, and using it to overrule a listing headed "WW2 RUSSIAN 91/30
        RIFLES" excluded five genuine firearms from a single page. The floor
        still decides when the title does not say.
        """
        assert classify_firearm("Mosin Nagant, as is", price=25.0) == (False, False)
        assert classify_firearm("Assorted small parts lot", price=25.0) == (False, False)

    def test_a_title_that_says_rifle_outranks_the_price(self):
        assert classify_firearm("WW2 RUSSIAN 91/30 RIFLES", price=20.0) == (True, False)

    def test_title_wins_when_both_match(self):
        """A rifle description mentioning a pistol must stay a rifle."""
        is_rifle, is_pistol = classify_firearm(
            "Mauser rifle", "Sold alongside a Luger pistol.", price=900.0
        )
        assert is_rifle and not is_pistol

    def test_rifle_caliber_overrules_a_pistol_keyword(self):
        _is_rifle, is_pistol = classify_firearm(
            "Mauser pistol carbine", caliber="8mm Mauser", price=900.0
        )
        assert not is_pistol

    def test_firearm_with_magazine_is_still_a_firearm(self):
        is_rifle, _ = classify_firearm("Vz.58 rifle with magazine", price=800.0)
        assert is_rifle

    def test_bare_magazine_is_not(self):
        assert classify_firearm("Magazine, 10 round steel", price=90.0) == (False, False)


class TestCountryAndManufacturer:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("GERMAN K98 Mauser", "Germany"),
            ("RUSSIAN Mosin Nagant", "Russia"),
            ("ITALIAN Carcano M91", "Italy"),
            ("BRITISH Lee-Enfield", "United Kingdom"),
            ("FINNISH M39", "Finland"),
            ("SWISS K31", "Switzerland"),
        ],
    )
    def test_leading_nationality_wins(self, title, expected):
        assert extract_country(title) == expected

    def test_title_beats_description(self):
        """The vendors lead with the country; the body mentions others."""
        assert extract_country("FINNISH M39 rifle", "Built on a Russian receiver.") == "Finland"

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Mosin-Nagant M91/30", "Mosin-Nagant"),
            ("Mauser K98k", "Mauser"),
            ("Springfield 1903", "Springfield"),
            ("Smith & Wesson revolver", "Smith & Wesson"),
        ],
    )
    def test_manufacturer(self, title, expected):
        assert extract_manufacturer(title) == expected

    def test_unknown_returns_none(self):
        assert extract_manufacturer("Unmarked trench club") is None


class TestBoreCondition:
    def test_grades_only_bore_sentences(self):
        """'overall excellent' must not become an excellent bore."""
        text = "Overall condition is excellent. The bore is dark and pitted, poor."
        assert extract_bore_condition(text) == "Poor"

    def test_ranges(self):
        assert extract_bore_condition("Bore is fair to good.") == "Fair to Good"

    def test_no_mention(self):
        assert extract_bore_condition("A nice rifle in great shape.") is None

    def test_none_input(self):
        assert extract_bore_condition(None) is None


class TestEnrich:
    def test_fills_every_field(self):
        result = enrich("GERMAN K98 Mauser rifle", "Bore is excellent.", 900.0)
        assert result["caliber"] == "8mm Mauser"
        assert result["country"] == "Germany"
        assert result["manufacturer"] == "Mauser"
        assert result["condition"] == "Excellent"
        assert result["is_rifle"] is True
        assert result["is_pistol"] is False

    def test_scraper_supplied_values_are_trusted(self):
        """A caliber parsed off the page beats anything guessed from prose."""
        result = enrich("Some rifle", None, 500.0, caliber="6.5x55 Swedish")
        assert result["caliber"] == "6.5x55 Swedish"


class TestVetoesReadTheTitleOnly:
    """A firearm's own description mentions its parts. That is not a veto.

    Measured against the live catalogs before this was fixed: reading the
    description here wrongly rejected 17 of 58 Empire Arms listings and 61 of
    210 Royal Tiger listings, every one of them a real firearm.
    """

    def test_a_rifle_whose_description_mentions_its_bolt_is_still_a_rifle(self):
        is_rifle, is_pistol = classify.classify_firearm(
            "C Grade Vetterli Model 1870/87 Rifle Caliber 10.4x47mmR",
            "Serial numbers match. The rifle bolt is in good order and the bore is bright.",
            caliber="10.4x47mmR",
            price=149.99,
        )
        assert is_rifle is True
        assert is_pistol is False

    def test_an_accessory_named_in_the_title_is_still_vetoed(self):
        is_rifle, is_pistol = classify.classify_firearm(
            "Mosin Nagant rifle bolt, matching",
            "A spare bolt for the 91/30.",
            price=95.0,
        )
        assert (is_rifle, is_pistol) == (False, False)


class TestVendorCategoryOutranksHeuristics:
    """A dealer who files a listing under "Handguns" has settled the question."""

    def test_category_names_the_type(self):
        assert classify.kind_from_category("Rifle") == (True, False)
        assert classify.kind_from_category("Handguns") == (False, True)
        assert classify.kind_from_category("Revolvers") == (False, True)

    def test_a_category_that_says_nothing_defers_to_the_heuristics(self):
        for category in (None, "", "Antique", "Deal of the Day", "Shop All", "Parts Kit"):
            assert classify.kind_from_category(category) is None

    def test_a_contradictory_category_defers_too(self):
        assert classify.kind_from_category("Rifles & Handguns") is None

    def test_it_rescues_a_pistol_no_pattern_would_catch(self):
        # "BELGIAN Model 1910/22 Browning" names neither a pistol nor a rifle,
        # and it is a pistol. Only the vendor's section knows.
        title = "BELGIAN Model 1910/22 Browning"
        assert classify.classify_firearm(title, price=400.0) == (False, False)
        assert classify.classify_firearm(title, price=400.0, category="Handgun") == (False, True)

    def test_enrich_passes_the_category_through(self):
        derived = classify.enrich("Some Old Thing", price=400.0, category="Handgun")
        assert derived["is_pistol"] is True
        assert derived["is_rifle"] is False


class TestPluralsAreRecognized:
    """ "RIFLES" is not "rifle", and a dealer's catalog is written in plurals.

    A word boundary after "rifle" does not match "rifles", so the
    singular-only patterns silently skipped most of a listing page: measured
    against the stored catalog, six of the eight titles naming more than one
    firearm were classified as neither rifle nor pistol.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "1893 SPANISH MAUSER LONG RIFLES",
            "RUSSIAN M44 CARBINES",
            "SPANISH 1916 SHORT RIFLES 7x57 as is",
            "1910 MEXICAN MAUSER RIFLES",
        ],
    )
    def test_plural_rifles(self, title):
        assert classify.classify_firearm(title, price=300.0) == (True, False)

    @pytest.mark.parametrize(
        "title",
        ["S&W MODEL 10 PISTOLS", "BRITISH Webley Mk VI revolvers", "Assorted HANDGUNS"],
    )
    def test_plural_handguns(self, title):
        assert classify.classify_firearm(title, price=300.0) == (False, True)

    def test_the_singular_still_works(self):
        assert classify.classify_firearm("Mosin Nagant M38 carbine", price=300.0) == (True, False)
        assert classify.classify_firearm("Luger P08 pistol", price=900.0) == (False, True)


class TestThingsSoldBesideFirearms:
    """A dealer's catalog is not only firearms, and prose bleeds between them."""

    def test_a_blanket_is_not_a_rifle(self):
        # Reported from a real scan: the neighbouring panel's text bled into
        # this listing's description and it was filed as a rifle.
        assert classify.classify_firearm(
            "HAND WOVEN EXTRA LARGE VAQUERO BLANKETS",
            "Native hand spun and woven. Ships with the rifle order.",
            price=99.0,
        ) == (False, False)

    @pytest.mark.parametrize(
        "title",
        ["WW2 US GI HELMETS, no liner", "Original unit patches", "Reference book, Mauser rifles"],
    )
    def test_other_goods_are_not_firearms(self, title):
        assert classify.classify_firearm(title, price=99.0) == (False, False)


class TestColtPolicePositive:
    """ "Colt PP" on a dealer's flyer is a revolver, not an unknown."""

    @pytest.mark.parametrize(
        "title",
        ["COLT PP .38 FRAMES. Most have bbl& maybe few parts", "Colt Police Positive .38"],
    )
    def test_it_is_a_handgun(self, title):
        assert classify.classify_firearm(title, price=99.0) == (False, True)


class TestACheapFrameIsStillAFirearm:
    """The one exception to the price floor, and why it is drawn there.

    Below $70 a listing is a part or an accessory, whatever it is called — a
    $25 "Mosin Nagant rifle" is a book or a toy. A frame or a receiver is
    different in kind: it is the serialised part, it is what the law regulates,
    and it is the firearm. A dealer's "COLT PP .38 FRAMES" at $29 came back as
    neither rifle nor pistol before this.
    """

    def test_a_cheap_handgun_frame_is_a_handgun(self):
        assert classify.classify_firearm("COLT PP .38 FRAMES", price=29.0) == (False, True)

    def test_a_cheap_rifle_receiver_is_a_rifle(self):
        assert classify.classify_firearm("Stripped AR-15 lower receiver", price=45.0) == (
            True,
            False,
        )

    def test_a_parts_kit_with_no_frame_is_not_a_firearm(self):
        # Which is the whole point of a dealer saying so.
        for title in (
            "Enfield parts kits, no frame",
            "K98 parts kit without receiver",
            "Mauser parts set, less frame",
        ):
            assert classify.classify_firearm(title, price=48.88) == (False, False)

    def test_the_floor_still_applies_to_everything_else(self):
        assert classify.classify_firearm("Mosin Nagant, as is", price=25.0) == (False, False)
        # An accessory named ahead of the firearm is an accessory, and the
        # floor is not what decides it.
        assert classify.classify_firearm("Leather sling for a Mauser rifle", price=20.0) == (
            False,
            False,
        )

    def test_a_frame_with_no_firearm_named_is_still_nothing(self):
        # "Picture frames" should not become handguns.
        assert classify.classify_firearm("Wooden picture frames, lot of 3", price=30.0) == (
            False,
            False,
        )


class TestTheTitleOutranksTheDescription:
    """When the two disagree, the heading is the claim.

    This matters most for OCR'd flyers, where a neighbouring panel's prose
    bleeds into a listing's description: "COLT PP .38 FRAMES" arrived carrying
    a paragraph about Russian carbines and was filed as a rifle.
    """

    def test_a_handgun_title_beats_rifle_prose(self):
        assert classify.classify_firearm(
            "COLT PP .38 FRAMES",
            "RUSSIAN M44 CARBINES good condition. WW2 ENFIELD rifles as is.",
            price=29.0,
        ) == (False, True)

    def test_a_rifle_title_beats_handgun_prose(self):
        assert classify.classify_firearm(
            "1893 SPANISH MAUSER LONG RIFLES",
            "Found a small lot. Pistol grip stocks available too.",
            price=110.88,
        ) == (True, False)

    def test_when_the_title_names_both_the_leading_word_still_decides(self):
        is_rifle, is_pistol = classify.classify_firearm(
            "Mauser rifle sold with a Luger pistol", price=900.0
        )
        assert is_rifle and not is_pistol


class TestACaliberDoesNotOverrideANamedPistol:
    """The caliber rule is for prose, not for a title that says "pistol".

    A caliber is often extracted from the description, and on an OCR'd flyer
    the description carries whatever the neighbouring panel said: "MAUSER C96
    PISTOL KITS" picked up "8mm Mauser" from the column beside it and stopped
    being a handgun on the strength of it.
    """

    def test_a_rifle_caliber_does_not_unmake_a_named_pistol(self):
        assert classify.classify_firearm(
            "MAUSER C96 PISTOL KITS",
            "with frames, used, good condition. 8mm Mauser rifles also available.",
            caliber="8mm Mauser",
            price=278.88,
        ) == (False, True)

    def test_it_still_rescues_a_rifle_described_with_a_pistol_word(self):
        _is_rifle, is_pistol = classify.classify_firearm(
            "GERMAN K98 Mauser",
            "Comes with a holster for the pistol cartridge conversion.",
            caliber="8x57",
            price=900.0,
        )
        assert not is_pistol

    def test_a_title_naming_both_still_defers_to_the_caliber(self):
        """ "Mauser pistol carbine" is genuinely ambiguous; the caliber decides."""
        _is_rifle, is_pistol = classify.classify_firearm(
            "Mauser pistol carbine", caliber="8mm Mauser", price=900.0
        )
        assert not is_pistol

    def test_enrich_extracts_a_caliber_without_losing_the_handgun(self):
        derived = classify.enrich(
            "MAUSER C96 PISTOL KITS",
            "with frames, used. 8mm Mauser mentioned nearby.",
            278.88,
            category="Flyer",
        )
        assert derived["is_pistol"] is True
        assert derived["is_rifle"] is False


class TestAccessoryOrBundle:
    """A listing is titled for the thing being sold, so order decides.

    "Leather sling for a Mauser rifle" and "Mosin Nagant rifle with sling" both
    name an accessory and a firearm. Whichever is named first is the thing.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "Leather sling for a Mauser rifle",
            "Leather ammo pouch, Wehrmacht",
            "Holster for a Luger pistol",
            "Bayonet scabbard, K98",
        ],
    )
    def test_the_accessory_comes_first(self, title):
        assert classify.classify_firearm(title, price=400.0) == (False, False)

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Mosin Nagant rifle with sling and cleaning rod", (True, False)),
            ("Makarov pistol with original holster", (False, True)),
            ("K98 Mauser rifle, bayonet and scabbard included", (True, False)),
        ],
    )
    def test_the_firearm_comes_first(self, title, expected):
        assert classify.classify_firearm(title, price=400.0) == expected


class TestBarrelledReceivers:
    """ "BBL REC" is a barrelled receiver: the serialised part with a barrel."""

    @pytest.mark.parametrize(
        "title",
        [
            "JAP ARISIKA BBL REC .T-99, T-38, CARBINE AND RIFLE",
            "GAHENDRA MARTINI RIFLE BBL Action/Rec",
            "Mauser barreled receiver, matching",
        ],
    )
    def test_it_is_the_firearm_even_below_the_price_floor(self, title):
        assert classify.classify_firearm(title, price=45.0) == (True, False)


class TestModelsTheHeuristicsDidNotKnow:
    @pytest.mark.parametrize(
        "title",
        [
            "JAP ARISAKA Type 99, matching",
            "Italian Vetterli 1870/87, as is",
            "Swiss Schmidt-Rubin K31",
            "GAHENDRA MARTINI, Nepalese",
        ],
    )
    def test_they_are_rifles(self, title):
        is_rifle, _is_pistol = classify.classify_firearm(title, price=400.0)
        assert is_rifle


class TestDesignationsSomebodyHadToTellUs:
    """Names whose type cannot be read out of the words.

    Everything else here is a rule about English or about the trade in
    general. This table is the opposite: single designations, each one
    present because somebody who knows the market said what it is. The
    rules cannot derive these, so they are asserted, and the table is
    consulted first.
    """

    def test_the_enfield_no1_mk2_is_the_revolver(self):
        # Reported by the site's owner. Note it is *not* the No.1 Mk III,
        # which is the SMLE rifle -- hence a deliberately narrow pattern.
        for title in (
            "WW2 ENFIELD NO1 MK2 PARTS KITS",
            "Enfield No.1 Mk.2 revolver, .38",
            "ww2 enfield no 1 mk 2 parts kits",
        ):
            assert classify.classify_firearm(title, price=48.88) == (False, True)

    def test_it_outranks_the_no_frame_veto(self):
        """A named handgun kit is still a handgun.

        The dealer sells "revolver kits" and "pistol kits" as handguns, and
        counts them that way. A general "no frame" is what stops an unnamed
        parts pile; it does not unname something we were told the type of.
        """
        assert classify.classify_firearm(
            "WW2 ENFIELD NO1 MK2 PARTS KITS. No frame", price=48.88
        ) == (False, True)

    def test_the_smle_is_untouched(self):
        for title in (
            "BRITISH Lee-Enfield No.4 Mk I rifles",
            "Enfield No1 Mk3 SMLE, .303",
        ):
            is_rifle, is_pistol = classify.classify_firearm(title, price=400.0)
            assert (is_rifle, is_pistol) == (True, False), title


class TestPartsAndAccessories:
    """Things a dealer sells beside firearms, at firearm prices.

    Royal Tiger lists $449 AK parts kits and $149 barrels among the rifles;
    neither is a firearm. Reported from the live catalog by the site's owner:
    "any 'parts kit' is in that category".
    """

    @pytest.mark.parametrize(
        "title",
        [
            "Polish AK Underfolder Parts Kits with Rear Sight & Live Barrel, 7.62x39",
            "Ethiopian Gafat ET-97 AK Parts Kit with Live Barrel, 7.62x39",
            "East German KM 72 AK Parts Kits with Live Barrel, POOR BORE",
            "K98 Mauser parts kit",
        ],
    )
    def test_a_parts_kit_is_parts(self, title):
        assert classify.classify_firearm(title, price=449.99) == (False, False)

    def test_a_kit_named_for_a_handgun_is_still_a_handgun(self):
        """The dealer's own way of selling one, and not the phrase "parts kit"."""
        for title in ("S&W K-Frame Snub Nose Revolver Kits", "CZ 50/70 Pistol Kits"):
            assert classify.classify_firearm(title, price=88.0) == (False, True)

    def test_a_buttstock_is_not_a_rifle(self):
        assert classify.classify_firearm(
            "AK-47 Black Polymer Buttstock with hardware", price=129.99
        ) == (False, False)

    @pytest.mark.parametrize(
        "title",
        [
            'AK47 / AKM 16" Chrome Lined Barrels, New Production Parkerized, 7.62x39',
            'AK47 / AKM 16" BARRELS, NEW PRODUCTION, CHROME LINED BARREL, IN THE WHITE',
        ],
    )
    def test_a_loose_barrel_is_not_a_rifle(self, title):
        assert classify.classify_firearm(title, price=149.99) == (False, False)

    def test_but_a_barreled_action_still_is(self):
        """The distinction the owner drew: barrels, "not barreled action"."""
        assert classify.classify_firearm(
            "Berthier 1907/15 barreled action, shortened barrel, Serial number 19668",
            price=149.99,
        ) == (True, False)

    def test_a_rifle_sold_with_a_new_stock_is_a_rifle(self):
        # The accessory is named after the firearm, so the firearm is the thing.
        assert classify.classify_firearm(
            "Gunsmith Special Yugo SKS MODEL 59/66 CAL. 7.62x39 with New Production Stock",
            price=349.99,
        ) == (True, False)


class TestLicensesAreNotProducts:
    """C&R and FFL are licenses the ATF issues, not things anybody sells.

    They are on every surplus listing, because every listing has to say which
    one a buyer needs. That makes them behave like a product name: set in
    capitals like one, sitting next to a price like one — "Add frame for
    $38.88. C&R/FFL required." — and on a flyer read by OCR that was enough to
    produce a $38.88 listing called "C&R/FFL".
    """

    @pytest.mark.parametrize(
        "title",
        [
            "C&R/FFL",
            "FFL",
            "C&R required",
            "No FFL required",
            "FFL or C&R req.",
            "Curio and Relic",
            "C & R only",
        ],
    )
    def test_a_title_that_is_only_a_license_names_nothing(self, title):
        assert classify.names_only_a_license(title)
        assert classify.classify_firearm(title, price=38.88) == (False, False)

    @pytest.mark.parametrize(
        "title",
        [
            "1888 GERMAN COMMISSION RIFLE",
            "ENFIELD NO1 MK2 PARTS KITS",
            "WW2 RUSSIAN 91/30 RIFLES C&R/FFL required",
            "COLT PP .38 FRAMES, FFL required",
        ],
    )
    def test_a_listing_that_merely_requires_one_is_untouched(self, title):
        assert not classify.names_only_a_license(title)

    def test_it_outranks_the_vendor_category(self):
        """No category can make a license into a rifle."""
        assert classify.classify_firearm("C&R/FFL", category="Rifles", price=300.0) == (
            False,
            False,
        )

    def test_a_license_is_ruled_out_rather_than_merely_unknown(self):
        """The difference matters to anything that fills gaps from elsewhere."""
        assert classify.is_ruled_out("C&R/FFL required")


class TestAMakersNameIsTheLastResortForACaliber:
    """Mauser and Enfield each made a famous rifle and a famous revolver.

    The name alone points at the rifle, which is right for a listing that says
    nothing more and wrong the moment it does. "MAUSER C96 PISTOL KITS" came
    back in 8mm Mauser — the 98's cartridge, not the C96's — and "ENFIELD NO1
    MK2 PARTS KITS", a .38 revolver, came back in .303 British.
    """

    def test_a_maker_alone_still_answers_for_a_rifle(self):
        assert classify.extract_caliber("1903 TURKISH CONTRACT MAUSERS") == "8mm Mauser"
        assert classify.extract_caliber("ENFIELD NO4 MK1 RIFLES") == ".303 British"

    def test_but_never_for_a_handgun(self):
        assert classify.extract_caliber("MAUSER C96 PISTOL KITS") is None
        assert classify.extract_caliber("Mauser C96 Broomhandle") is None

    def test_including_one_only_a_designation_identifies(self):
        """The Enfield No.1 Mk.2 does not say "revolver" anywhere in its name."""
        assert classify.extract_caliber("ENFIELD NO1 MK2 PARTS KITS") is None

    def test_an_explicit_caliber_beats_the_maker(self):
        """The maker rule used to be reached first and overrule the page."""
        assert classify.extract_caliber("Spanish Mauser 7x57 short rifle") == "7x57mm Mauser"

    def test_a_model_rule_still_beats_both(self):
        assert classify.extract_caliber("GERMAN K98 Mauser rifle") == "8mm Mauser"
        assert classify.extract_caliber("BRITISH Lee-Enfield No4 Mk1") == ".303 British"

    def test_a_dealer_sells_them_in_lots(self):
        """ "MAUSERS" is not "MAUSER" to a word boundary."""
        assert classify.extract_caliber("Lot of Mausers, as is") == "8mm Mauser"


class TestDescriptionsThatAreNotAboutTheirListing:
    """A flyer read by OCR carries the panel next door into every description.

    Reading it is useful. Deriving facts from it is not: it filed hand-woven
    blankets under 8mm Mauser and put a Japanese Arisaka in Sweden.
    """

    BLED = "8mm Mauser, Swedish steel, excellent bore. $47.88 C&R"

    def test_by_default_a_description_is_evidence(self):
        found = classify.enrich("HAND WOVEN BLANKETS", self.BLED)
        assert found["caliber"] == "8mm Mauser"
        assert found["country"] == "Sweden"

    def test_and_for_a_bleeding_source_it_is_not(self):
        found = classify.enrich("HAND WOVEN BLANKETS", self.BLED, trust_description=False)
        assert found["caliber"] is None
        assert found["country"] is None
        assert found["condition"] is None

    def test_the_title_still_answers(self):
        found = classify.enrich(
            "6.5MM ITALIAN CARCANO CARBINES", self.BLED, trust_description=False
        )
        assert found["caliber"] == "6.5x52mm Carcano"
        assert found["country"] == "Italy"

    def test_the_rifle_handgun_split_still_reads_the_description(self):
        """A judgement about a whole block of text survives some contamination;
        a specific claim like a caliber does not."""
        found = classify.enrich("GAHENDRA MARTINI", "a fine old rifle", trust_description=False)
        assert found["is_rifle"] is True

    def test_what_a_vendor_states_is_still_taken(self):
        found = classify.enrich("Blankets", self.BLED, caliber="8mm", trust_description=False)
        assert found["caliber"] == "8mm"


class TestACartridgeNamedAfterItsDesigner:
    """This table names the maker wherever the cartridge does, and that is
    where a listing gets a maker it never mentions.

    "SPANISH 1916 SHORT RIFLES 7x57" is a Mauser and says so nowhere. Left as
    a bare "7x57" by the generic metric fallback, it named nobody.
    """

    def test_7x57_is_a_mauser_cartridge(self):
        assert classify.extract_caliber("SPANISH 1916 SHORT RIFLES 7x57 as is") == "7x57mm Mauser"

    def test_and_is_not_confused_with_8x57(self):
        assert classify.extract_caliber("SPANISH M43 RIFLES 8x57 as is") == "8mm Mauser"

    @pytest.mark.parametrize(
        ("caliber", "expected"),
        [
            ("8mm Mauser", "Mauser"),
            ("7x57mm Mauser", "Mauser"),
            ("6.5x52mm Carcano", "Carcano"),
            ("7.7x58mm Arisaka", "Arisaka"),
            (".45 ACP", None),
            ("7.62x54R", None),
        ],
    )
    def test_the_label_is_read_for_a_maker(self, caliber, expected):
        """Only what the name actually says. 7.62x54R is a Mosin cartridge and
        does not say so, which is what the catalog scan is for."""
        assert classify.extract_manufacturer(caliber) == expected


class TestCalibersFoundByAuditingTheCatalog:
    """Found by asking the catalog which listings have caliber-shaped text in
    the title and no caliber recorded — which is what the "Unknown" bucket in
    the filters is for.
    """

    def test_a_trailing_mm_no_longer_hides_a_caliber(self):
        """The class bug behind three of these.

        The generic metric rule ended in a word boundary, and "10.35x22mm" has
        none between the 22 and the mm — so it matched nothing at all.
        """
        assert classify.extract_caliber("Bodeo M1889 Revolver, 10.35x22mm") == "10.35x22mm"
        assert classify.extract_caliber("Beaumont Rifle Cal. 11x52mm") == "11x52mm"

    def test_and_the_label_is_not_shouted(self):
        """Upper-cased for the R of a rimmed cartridge, then mm put back."""
        assert classify.extract_caliber("Rifle 7.62x54R") == "7.62x54R"
        assert "MM" not in (classify.extract_caliber("Revolver 10.35x22mm") or "")

    @pytest.mark.parametrize(
        "title",
        [
            "BAYARD MODEL 1908 .25ACP/6.35 SEMI-AUTO PISTOL",
            "Colt Vest Pocket .25 ACP",
            "Browning 6.35mm pocket pistol",
        ],
    )
    def test_25_acp_however_it_is_written(self, title):
        """A dealer writes it with no space, or under its metric name, or both
        at once."""
        assert classify.extract_caliber(title) == ".25 ACP"

    def test_the_metric_name_for_8mm_mauser(self):
        assert classify.extract_caliber("Yugoslavian 24/47 rifle 7.92x57mm") == "8mm Mauser"

    def test_8mm_lebel_spelled_out(self):
        assert classify.extract_caliber("M16 Carbine 8mm Lebel") == "8mm Lebel"

    def test_the_japanese_6_5(self):
        assert classify.extract_caliber("Japanese Training Rifle 6.5x50mm") == "6.5x50mm Arisaka"

    def test_38_after_380_so_the_longer_number_wins(self):
        assert classify.extract_caliber("Beretta 1934 .380 ACP") == ".380 ACP"
        assert classify.extract_caliber("COLT PP .38 FRAMES") == ".38 Special"

    def test_a_periscope_is_not_a_caliber(self):
        """ "10×60" on an optic looks exactly like a metric cartridge."""
        assert classify.extract_caliber("Carl Zeiss Jena 10×60 Marina Romana Periscope") is None


class TestAStandalonePistolMagazine:
    """A magazine on its own is a part; a firearm sold with one is a firearm.

    Both are written the same way — a model name, then the word "magazine" —
    and eight Luger magazines at $130 to $200 were filed as handguns because
    of it.
    """

    def kind(self, title, price=150.0, category=None):
        d = classify.enrich(title, None, price, category=category)
        return "pistol" if d["is_pistol"] else "rifle" if d["is_rifle"] else "accessory"

    @pytest.mark.parametrize(
        "title",
        [
            "East German Luger Magazine, Serial Number 137",
            "Erma Luger Magazine",
            "FXO WWII GERMAN LUGER MAGAZINE",
            "GERMAN LUGER MAGAZINE, SERIAL NUMBER 0388",
            "CZ82 9x18 Makarov - 12RD Magazine + Free Accessories",
        ],
    )
    def test_the_magazine_is_the_product(self, title):
        assert self.kind(title) == "accessory"

    @pytest.mark.parametrize(
        "title",
        [
            "CZ75D Pistol 9mm Luger with Factory Box and 2 Magazines",
            "AR-15 9MM Rifle / Carbine with Glock Magazine",
            "CZ BRNO Model 2 Trainer Rifle, .22 Long Rifle, 5 round magazine included",
            "Czech VZ 82 / CZ82 - 9x18mm Makarov Pistol with Holster & 2 Magazines",
        ],
    )
    def test_a_firearm_sold_with_one_is_still_a_firearm(self, title):
        assert self.kind(title, price=900.0) != "accessory"

    def test_an_unknown_model_falls_back_to_the_vendor_category(self):
        """ "Pre-Ban Interdynamic KG-99 w/ Extra Magazines" names no word this
        code knows to be a firearm, so the title alone genuinely does not say —
        and the section the dealer filed it under does."""
        title = "Pre-Ban Interdynamic KG-99 w/ Extra Magazines"
        assert self.kind(title, 900.0) == "accessory"
        assert self.kind(title, 900.0, category="Modern Handguns") == "pistol"

    def test_a_matching_magazine_is_a_fact_about_the_pistol(self):
        """The hard pair. Same shape, same words, opposite meanings — and only
        "matching" tells them apart, because a collector writes it to mean the
        serial numbers agree, which presupposes the gun."""
        assert self.kind("Rare 1925-Dated Simson Luger - Matching Magazine", 3250.0) == "pistol"
        assert self.kind('1934 "K Date" Mauser Luger - Matching Magazine', 3995.0) == "pistol"
        assert self.kind("Erma Luger Magazine", 199.99) == "accessory"

    def test_mag_is_not_accepted_as_an_abbreviation(self):
        """ ".44 Mag" is a cartridge and "Mag Fed Shotgun" is a shotgun. Either
        would lead the rule straight past the firearm it is describing."""
        assert self.kind("Toros Arms Coppola TR-12 Semi Auto Mag Fed Shotgun, 12 Gauge", 400.0) == (
            "rifle"
        )
        assert self.kind("Smith & Wesson Model 29 .44 Mag Revolver", 1200.0) == "pistol"

    def test_the_barrels_you_were_told_about_are_still_parts(self):
        """Teaching the *order* rule about model names undid this: the AK47 is
        named before the barrels, so the listing read as a rifle. It is a box
        of barrels, and the AK47 only says what they fit."""
        title = "AK47 / AKM 16in Chrome Lined Barrels, New Production Parkerized, 7.62x39"
        assert self.kind(title, 89.99) == "accessory"


class TestBayonetsAndPartsKits:
    """Their own flags, so they stop hiding in the accessories pile.

    Both used to be "neither a rifle nor a handgun", which is also what a
    sling, a helmet and a cleaning kit are — so somebody watching for a Carcano
    bayonet had to read the lot.
    """

    def flags(self, title, category=None, price=200.0):
        d = classify.enrich(title, None, price, category=category)
        return (d["is_rifle"], d["is_pistol"], d["is_bayonet"], d["is_parts_kit"])

    @pytest.mark.parametrize("title", ["1891 Carcano Bayonet", "VZ24 BAYONET", "BAYONET GRAB BAG"])
    def test_a_bayonet_is_a_bayonet(self, title):
        assert self.flags(title) == (False, False, True, False)

    @pytest.mark.parametrize(
        "title",
        [
            'Excellent Remington Model 1863 "Zouave" Rifle w/ bayonet',
            "Springfield Model 1884 Trapdoor w/ Ramrod Bayonet - 1891 mfg",
            "WWII Italian Carcano M91 Cavalry Carbine 6.5x52mm with bayonet",
        ],
    )
    def test_but_a_firearm_that_comes_with_one_is_not_a_bayonet(self, title):
        """A third of the listings that say "bayonet" are these, and what marks
        them is "with" or "w/" before the word. A bayonet named without one is
        what is for sale; "Bayonet w/ Scabbard" is still a bayonet, so only a
        "with" that comes *before* the word counts."""
        _rifle, _pistol, bayonet, _kit = self.flags(title, price=900.0)
        assert bayonet is False

    def test_a_bayonet_keeps_its_own_scabbard(self):
        assert self.flags("German S84/98 Bayonet w/ Scabbard")[2] is True

    def test_a_rifle_sold_without_one_is_not_a_bayonet(self):
        """The listing that prompted all of this. Every rule involved saw the
        word "Bayonet" and none of them saw the "No" in front of it, so a
        799-dollar SKS was filed as a blade."""
        # En dashes, because that is what the vendor actually types. Rewriting
        # them as hyphens would test a title that does not exist.
        title = (
            "Russian Tula SKS – Letter Series 1958 – No Import Marks – "  # noqa: RUF001
            "Numbers Matching – No Bayonet – C&R"  # noqa: RUF001
        )
        rifle, _pistol, bayonet, _kit = self.flags(title, price=799.99)
        assert bayonet is False
        assert rifle is True

    def test_the_negation_has_to_be_next_to_the_word(self):
        """That title also says "No Import Marks" forty characters earlier. An
        unanchored search found that one and concluded nothing."""
        assert self.flags("K98 Bayonet, no import marks")[2] is True

    def test_and_it_is_not_a_negation_inside_another_word(self):
        """ "Carca-no Bayonet". A missing word boundary here turns every Carcano
        bayonet in the catalog into a rifle that has none."""
        assert self.flags("1891 Carcano Bayonet")[2] is True

    @pytest.mark.parametrize(
        "title",
        [
            "Enfield No4 Mk1 .303 British w Bayonet",
            "Mauser 1900 Danzig Gewehr 98 7.92x57 Mauser w Bayonet",
        ],
    )
    def test_a_bare_w_also_means_with(self, title):
        """Which is how one vendor writes it, and neither of these rifles names
        the word "rifle" anywhere."""
        rifle, _pistol, bayonet, _kit = self.flags(title, price=900.0)
        assert bayonet is False
        assert rifle is True

    def test_but_a_bare_w_is_not_the_start_of_a_makers_name(self):
        """W+F Bern is Waffenfabrik Bern. Reading that W as "with" cost them
        their K31 Pioneer Sawback Bayonet."""
        assert self.flags("W+F Bern K31 Pioneer Sawback Bayonet 7.5x55 Swiss")[2] is True

    def test_a_parts_kit_from_the_title(self):
        assert self.flags("ENFIELD NO1 MK2 PARTS KITS")[3] is True

    def test_and_from_the_vendors_own_section(self):
        """Royal Tiger files them under a category and does not always say so
        in the title."""
        assert self.flags("Mauser K98 kit, no receiver", category="Parts Kit")[3] is True

    def test_a_parts_kit_can_be_a_handgun_too(self):
        """Which is why these are separate flags and not one enum: a kit is a
        firearm minus its serialized part, so a filter for either should find
        it."""
        rifle, pistol, _bayonet, kit = self.flags("ENFIELD NO1 MK2 PARTS KITS")
        assert kit is True
        assert rifle or pistol

    def test_an_ordinary_accessory_is_neither(self):
        assert self.flags("Canvas ammo pouch") == (False, False, False, False)
