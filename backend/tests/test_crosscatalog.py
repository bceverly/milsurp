"""Borrowing a listing's blank fields from a better-described one elsewhere.

The guards are what these tests are about. The feature itself finds very
little on a small catalog and is meant to; what matters is that when it does
find something it is not making it up, because the first version run against
the live catalog decided US T-handle trench shovels were chambered in
6.5x52mm Carcano and made by Remington.
"""

from __future__ import annotations

from app.services import crosscatalog as cc


def entry(item_id, title, *, site=1, kind=(True, False), **fields):
    return cc.Entry(
        item_id=item_id,
        site_id=site,
        title=title,
        words=cc.tokens(title),
        caliber=fields.get("caliber"),
        country=fields.get("country"),
        manufacturer=fields.get("manufacturer"),
        kind=kind,
    )


class TestTokens:
    def test_the_trade_s_own_vocabulary_is_dropped(self):
        assert cc.tokens("Russian rifle, good bore, surplus condition") == {"russian"}

    def test_a_designation_spelled_three_ways_lands_on_one_token(self):
        assert cc.tokens("T-99") == cc.tokens("T.99") == cc.tokens("T99") == {"t99"}

    def test_a_caliber_survives_its_punctuation(self):
        assert cc.tokens("AK parts kit, 7.62x39") == {"762x39"}

    def test_fragments_are_not_words(self):
        assert cc.tokens("a of 10 K98") == {"k98"}


class TestWhatItRefusesToMatch:
    """Each of these was a real wrong answer before the guard that stops it."""

    def index(self, *entries):
        return cc.CatalogIndex(entries)

    def test_one_word_in_common_is_not_evidence(self):
        index = self.index(
            entry(1, "Italian Vetterli Model 1870/87/15", site=2, caliber="6.5x52mm Carcano")
        )
        assert index.suggest("US T-handle trench shovels, Italian", kind=(True, False)) is None

    def test_a_donor_of_a_different_type_is_no_donor(self):
        """A rifle's caliber is no use to a shovel, or to a revolver."""
        index = self.index(
            entry(1, 'BRITISH Pattern 14 "Enfield"', site=2, caliber=".303 British"),
            entry(2, "Italian Carcano Carbine", site=2, caliber="6.5x52mm"),
            entry(3, "GERMAN Model 98k Mauser", site=2, caliber="8mm Mauser"),
            entry(4, "Swiss Schmidt-Rubin K31", site=2, caliber="7.5x55mm"),
        )
        assert index.suggest("BRITISH PATTERN 14 ENFIELD KITS", kind=(False, True)) is None
        assert index.suggest("BRITISH PATTERN 14 ENFIELD KITS", kind=(True, False)) is not None

    def test_the_same_vendor_is_not_asked(self):
        """A vendor who leaves a field blank once tends to leave it blank twice."""
        index = self.index(entry(1, "JAPANESE Arisaka Type 99", site=7, caliber="7.7x58mm"))
        assert index.suggest("Arisaka Type 99 rifle", kind=(True, False), exclude_site_id=7) is None

    def test_a_long_title_does_not_win_by_having_more_chances(self):
        """Coverage, not just rarity: the two have to be about the same thing."""
        index = self.index(
            entry(
                1,
                "Arisaka Vetterli Carcano Berthier Gahendra Schmidt Rubin collection lot",
                site=2,
                caliber="6.5x52mm",
            )
        )
        assert index.suggest("Italian Carcano Berthier", kind=(True, False)) is None

    def test_a_donor_with_nothing_to_give_is_not_a_donor(self):
        index = self.index(entry(1, "JAPANESE Arisaka Type 99", site=2))
        assert index.suggest("JAPANESE Arisaka Type 99", kind=(True, False)) is None


class TestWhatItDoesMatch:
    def test_two_rare_words_in_common_carry_the_facts_across(self):
        index = cc.CatalogIndex(
            [
                entry(
                    1,
                    "JAPANESE Arisaka Type 99 Rifle",
                    site=2,
                    caliber="7.7x58mm",
                    country="Japan",
                    manufacturer="Arisaka",
                ),
                entry(2, "GERMAN Model 98k Mauser", site=2, caliber="8mm Mauser"),
                entry(3, "Italian Carcano Carbine", site=2, caliber="6.5x52mm"),
            ]
        )
        hint = index.suggest("JAPANESE ARISAKA T99 RIFLES as is", kind=(True, False))

        assert hint is not None
        assert hint.caliber == "7.7x58mm"
        assert hint.source_id == 1
        assert set(hint.shared) == {"arisaka", "japanese"}

    def test_one_word_alone_is_never_enough(self):
        """Even a word unique to one other listing. It is the commonest shape
        of a wrong answer: a part named after the rifle it fits."""
        index = cc.CatalogIndex(
            [
                entry(1, "JAPANESE Arisaka Type 99 Rifle", site=2, caliber="7.7x58mm"),
                entry(2, "GERMAN Model 98k Mauser", site=2, caliber="8mm Mauser"),
                entry(3, "Italian Carcano Carbine", site=2, caliber="6.5x52mm"),
            ]
        )
        assert index.suggest("ARISAKA bolt body, stripped", kind=(True, False)) is None


class TestFillingTheCatalog:
    def test_it_fills_only_the_blanks_and_says_what_it_did(self, seeded):
        from sqlalchemy import select

        from app.models import Item, Site

        sites = seeded.execute(select(Site)).scalars().all()
        described, sparse = sites[0], sites[1]

        def add(site, key, title, **fields):
            item = Item(
                site_id=site.id,
                external_key=key,
                url=f"https://example.test/{key}",
                title=title,
                is_rifle=True,
                **fields,
            )
            seeded.add(item)
            return item

        # A catalog, so that "arisaka" is rare in it and "rifle" is not. Two
        # listings on their own tell you nothing about which words are rare.
        for index, (title, caliber) in enumerate(
            [
                ("GERMAN Model 98k Mauser rifle", "8mm Mauser"),
                ("Italian Carcano Carbine rifle", "6.5x52mm"),
                ("Swiss Schmidt-Rubin K31 rifle", "7.5x55mm"),
                ("RUSSIAN Mosin Nagant 91/30 rifle", "7.62x54R"),
                ("BRITISH Lee-Enfield No4 Mk1 rifle", ".303 British"),
            ]
        ):
            add(described, f"filler{index}", title, caliber=caliber)

        add(
            described,
            "a",
            "JAPANESE Arisaka Type 99 Rifle",
            caliber="7.7x58mm",
            country="Japan",
            manufacturer="Arisaka",
        )
        target = add(
            sparse,
            "b",
            "JAPANESE ARISAKA rifles, as is",
            country="Nepal",  # already known, and not to be touched
        )
        seeded.commit()

        filled = cc.fill_gaps(seeded)
        seeded.commit()

        assert target.caliber == "7.7x58mm"
        assert target.manufacturer == "Arisaka"
        assert target.country == "Nepal"
        assert {entry.field for entry in filled} == {"caliber", "manufacturer"}
        assert all(entry.item_id == target.id for entry in filled)

    def test_running_it_twice_changes_nothing_the_second_time(self, seeded):
        assert cc.fill_gaps(seeded) == []


class TestPistolHolsters:
    """Not a guard on this module, but the classification it depends on."""

    def test_an_accessory_named_after_the_firearm_is_the_product(self):
        from app.services import classify

        assert classify.classify_firearm(
            'Mauser C96 "Broomhandle" Pistol Holster', price=120.0
        ) == (
            False,
            False,
        )

    def test_a_firearm_sold_with_one_is_still_the_firearm(self):
        from app.services import classify

        assert classify.classify_firearm("Mosin Nagant rifle with sling", price=300.0) == (
            True,
            False,
        )
