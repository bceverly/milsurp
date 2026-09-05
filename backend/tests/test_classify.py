"""The heuristics that turn listing prose into structured fields."""

from __future__ import annotations

import pytest

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

    def test_cheap_items_are_never_firearms(self):
        """Nothing under $70 is a firearm, whatever the title claims."""
        assert classify_firearm("Mosin Nagant rifle", price=25.0) == (False, False)

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
