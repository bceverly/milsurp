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
