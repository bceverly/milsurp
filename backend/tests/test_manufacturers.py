"""The maker list as data: matching, seeding, and re-filing after an edit."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Item, Manufacturer, ManufacturerModel, Site
from app.services import classify
from app.services import manufacturers as service


def make(session, **fields):
    row = Manufacturer(**fields)
    session.add(row)
    session.flush()
    service.invalidate()
    return row


def listing(session, site_id, key, title, description=None, manufacturer=None):
    item = Item(
        site_id=site_id,
        external_key=key,
        url=f"https://example.test/{key}",
        title=title,
        description=description,
        manufacturer=manufacturer,
    )
    session.add(item)
    session.flush()
    return item


class TestSpellingsAreLiteral:
    """An alias comes from a form, so it is escaped rather than compiled."""

    def test_punctuation_is_taken_literally(self):
        pattern = service.pattern_for(["S&W"])
        assert pattern.search("a S&W Model 10")
        assert not pattern.search("SxW")

    def test_a_regular_expression_typed_in_is_just_text(self):
        """Nobody gets to hand the process a pathological backtrack."""
        pattern = service.pattern_for([".*"])
        assert not pattern.search("anything at all")
        assert pattern.search("a .* b")

    def test_whitespace_inside_a_name_may_stretch(self):
        """OCR and vendors both space a name however they like."""
        pattern = service.pattern_for(["Smith & Wesson"])
        assert pattern.search("SMITH  &  WESSON revolver")
        assert pattern.search("smith & wesson")

    def test_it_matches_whole_words_only(self):
        pattern = service.pattern_for(["FN"])
        assert pattern.search("an FN Mauser")
        assert not pattern.search("FNX or unFNished")

    def test_an_empty_rule_matches_nothing(self):
        assert not service.pattern_for([]).search("Mauser")
        assert not service.pattern_for(["   "]).search("Mauser")


class TestOrderDecides:
    def test_the_first_rule_that_matches_wins(self):
        registry = service.Registry(
            [
                ("Mosin-Nagant", service.pattern_for(["Mosin-Nagant", "Mosin Nagant"])),
                ("Nagant", service.pattern_for(["Nagant"])),
            ]
        )
        assert registry.extract("RUSSIAN Mosin Nagant 91/30") == "Mosin-Nagant"

    def test_and_the_wrong_order_gets_the_wrong_answer(self):
        """Stated as a test because it is the reason `position` exists."""
        registry = service.Registry(
            [
                ("Nagant", service.pattern_for(["Nagant"])),
                ("Mosin-Nagant", service.pattern_for(["Mosin-Nagant"])),
            ]
        )
        assert registry.extract("RUSSIAN Mosin-Nagant 91/30") == "Nagant"


class TestSeeding:
    def test_an_empty_table_is_filled_from_the_built_in_list(self, clean_db):
        added = service.seed(clean_db)

        assert added == len(classify.MANUFACTURER_PATTERNS)
        names = set(clean_db.execute(select(Manufacturer.name)).scalars())
        assert {"Mauser", "Smith & Wesson", "Mosin-Nagant"} <= names

    def test_the_aliases_survive_the_translation(self, clean_db):
        service.seed(clean_db)

        sw = clean_db.execute(
            select(Manufacturer).where(Manufacturer.name == "Smith & Wesson")
        ).scalar_one()
        assert "S&W" in sw.spellings

        mosin = clean_db.execute(
            select(Manufacturer).where(Manufacturer.name == "Mosin-Nagant")
        ).scalar_one()
        assert "Mosin Nagant" in mosin.spellings

    def test_a_table_with_anything_in_it_is_left_alone(self, clean_db):
        """Deleting a maker on purpose must survive a restart."""
        make(clean_db, name="Only This One", position=10)

        assert service.seed(clean_db) == 0
        assert clean_db.execute(select(Manufacturer)).scalars().all()[0].name == "Only This One"

    def test_the_built_ins_still_answer_while_the_table_is_empty(self, clean_db):
        assert service.extract(clean_db, "GERMAN K98 Mauser rifle") == "Mauser"


class TestReprocessing:
    """An edit rewrites listings, and only the ones it can reach."""

    def site_id(self, session):
        return session.execute(select(Site.id)).scalars().first()

    def test_adding_a_maker_files_the_listings_that_name_it(self, seeded):
        site = self.site_id(seeded)
        listing(seeded, site, "a", "Husqvarna M38 Swedish Mauser")
        listing(seeded, site, "b", "GERMAN K98 rifle")
        make(seeded, name="Husqvarna", position=5)

        changed = service.reprocess(seeded, ["Husqvarna"])
        seeded.commit()

        assert changed == 1
        rows = {item.title: item.manufacturer for item in seeded.execute(select(Item)).scalars()}
        assert rows["Husqvarna M38 Swedish Mauser"] == "Husqvarna"
        assert rows["GERMAN K98 rifle"] is None

    def test_it_only_reads_the_listings_the_change_can_reach(self, seeded):
        """The point of taking the strings rather than re-running everything."""
        site = self.site_id(seeded)
        untouched = listing(seeded, site, "a", "GERMAN K98 rifle", manufacturer="Mauser")
        make(seeded, name="Husqvarna", position=5)

        service.reprocess(seeded, ["Husqvarna"])
        seeded.commit()

        # Mauser has no rule here, so a pass over everything would have cleared it.
        assert untouched.manufacturer == "Mauser"

    def test_a_listing_loses_its_maker_when_the_rule_goes(self, seeded):
        site = self.site_id(seeded)
        item = listing(seeded, site, "a", "Husqvarna M38", manufacturer="Husqvarna")
        row = make(seeded, name="Husqvarna", position=5)
        seeded.delete(row)
        seeded.flush()
        service.invalidate()

        changed = service.reprocess(seeded, ["Husqvarna"])
        seeded.commit()

        assert changed == 1
        assert item.manufacturer is None

    def test_the_description_counts_too(self, seeded):
        site = self.site_id(seeded)
        item = listing(seeded, site, "a", "Swedish rifle", description="Made by Husqvarna.")
        make(seeded, name="Husqvarna", position=5)

        service.reprocess(seeded, ["Husqvarna"])
        seeded.commit()

        assert item.manufacturer == "Husqvarna"

    def test_a_name_full_of_wildcards_does_not_match_the_catalog(self, seeded):
        """LIKE has wildcards of its own, and a maker's name is not a pattern."""
        site = self.site_id(seeded)
        item = listing(seeded, site, "a", "GERMAN K98 rifle")
        make(seeded, name="%", position=5)

        service.reprocess(seeded, ["%"])
        seeded.commit()

        assert item.manufacturer is None


class TestTheTitleOutranksTheDescription:
    """The prose under a listing is not always about that listing.

    On an OCR'd flyer the description carries whatever the neighboring panel
    said. Reading title and description as one string filed "CZ 50/70 PISTOL
    KITS" under Walther, because Walther is tried before CZ and the word had
    bled in from the listing beside it.
    """

    def registry(self):
        return service.Registry(
            [
                ("Walther", service.pattern_for(["Walther"])),
                ("CZ", service.pattern_for(["CZ"])),
            ]
        )

    def test_a_maker_named_in_the_title_wins(self):
        found = self.registry().extract_from(
            "CZ 50/70 PISTOL KITS", "with frames, used. Walther PP holsters $18.88."
        )
        assert found == "CZ"

    def test_the_description_still_answers_when_the_title_does_not(self):
        found = self.registry().extract_from("PISTOL KITS, unissued", "These are Walther PPs.")
        assert found == "Walther"

    def test_and_order_still_decides_within_the_title(self):
        assert self.registry().extract_from("Walther and CZ lot") == "Walther"


class TestDesignationsThatNameNoMaker:
    """A dealer often gives the model and never the maker.

    "RUSSIAN M44 CARBINES" and "WW2 RUSSIAN 91/30 RIFLES" are Mosin-Nagants
    that do not contain the word Mosin, or Nagant, anywhere. On a vendor whose
    descriptions can be trusted the prose rescues them; on a flyer read by OCR
    there is nothing but the title, so they had no maker and did not appear
    under the filter.
    """

    def registry(self):
        """The built-in list as the seed would put it into the table.

        The canonical name belongs in the pattern, exactly as
        Manufacturer.spellings puts it there. Leaving it out builds a rule for
        "Carcano" that does not match the word Carcano — which is what this
        helper did at first, and it made a passing test out of a broken one.
        """
        rules = [
            (name, service.pattern_for([name, *service._spellings_in(pattern, name)]))
            for pattern, name in classify.MANUFACTURER_PATTERNS
        ]
        return service.Registry(rules)

    @pytest.mark.parametrize(
        "title", ["RUSSIAN M44 CARBINES", "WW2 RUSSIAN 91/30 RIFLES", "Izhevsk M91/30"]
    )
    def test_a_model_number_identifies_the_maker(self, title):
        assert self.registry().extract(title) == "Mosin-Nagant"

    def test_but_not_one_that_two_makers_share(self):
        """M38 is a Carcano as often as it is a Mosin, so it is not a rule."""
        assert self.registry().extract("C Grade M38 Carcano Cavalry Carbine") == "Carcano"

    def test_and_not_a_number_that_merely_looks_similar(self):
        """ "Type 44" is not "M44"; whole words only."""
        assert self.registry().extract("Koishikawa Arsenal Type 44 Carbine") != "Mosin-Nagant"

    def test_an_ocr_misreading_is_a_spelling_like_any_other(self):
        """A scanned page is a source too, and it says ARISIKA."""
        assert self.registry().extract("JAP ARISIKA BBL REC .T-99, T-38") == "Arisaka"


class TestSeedingKeepsDesignationsWithSlashes:
    def test_a_slash_survives_into_the_aliases(self):
        """ "91/30" and "50/70" are how these guns are written. The literal
        check rejected them, so the table was seeded without the spellings
        dealers actually use."""
        spellings = service._spellings_in(
            r"\bMosin[- ]?Nagant\b|\bM?91/30\b|\bM44\b", "Mosin-Nagant"
        )
        assert "91/30" in spellings
        assert "M91/30" in spellings

    def test_and_it_matches_as_plain_text(self):
        pattern = service.pattern_for(["91/30"])
        assert pattern.search("WW2 RUSSIAN 91/30 RIFLES")
        assert not pattern.search("WW2 RUSSIAN 91-30 RIFLES")


class TestModelsBelongToAMaker:
    """A dealer names the model far more often than the maker.

    Kept as rows rather than as more lines in the alias box, because "M44" and
    "Mosin Nagant" are different kinds of fact — what a firm made, and how its
    name is spelled — and a model has somewhere to grow: its caliber, its type,
    the years it ran.
    """

    def maker(self, session, name, models=(), position=10):
        row = Manufacturer(name=name, position=position)
        row.models = [ManufacturerModel(name=model) for model in models]
        session.add(row)
        session.flush()
        service.invalidate()
        return row

    def test_a_model_identifies_its_maker(self, clean_db):
        self.maker(clean_db, "Mosin-Nagant", ["M44", "91/30"])
        registry = service.registry(clean_db)
        assert registry.extract("RUSSIAN M44 CARBINES") == "Mosin-Nagant"
        assert registry.extract("WW2 RUSSIAN 91/30 RIFLES") == "Mosin-Nagant"

    def test_it_is_matched_as_literal_text_on_whole_words(self):
        """Same rule as an alias: it comes from a form, so it is escaped."""
        assert service.pattern_for(["M44"]).search("RUSSIAN M44 CARBINES")
        assert not service.pattern_for(["M44"]).search("Koishikawa Type 44 Carbine")
        assert not service.pattern_for(["M44"]).search("M448 widget")

    def test_a_model_two_makers_claim_identifies_neither(self, clean_db):
        """M38 is a Carcano as often as it is a Mosin. Picking the first rule
        in the list would be an accident of ordering, not a decision."""
        self.maker(clean_db, "Mosin-Nagant", ["M38"], position=10)
        self.maker(clean_db, "Carcano", ["M38"], position=20)

        assert service.registry(clean_db).extract("An M38 carbine") is None

    def test_but_both_entries_are_kept(self, clean_db):
        """They are both true; the admin page says which ones cancel out."""
        first = self.maker(clean_db, "Mosin-Nagant", ["M38"], position=10)
        second = self.maker(clean_db, "Carcano", ["M38"], position=20)

        assert first.model_names == ["M38"]
        assert second.model_names == ["M38"]
        assert service.ambiguous_models([first, second]) == {"m38"}

    def test_an_unshared_model_still_works_alongside_a_shared_one(self, clean_db):
        self.maker(clean_db, "Mosin-Nagant", ["M38", "M44"], position=10)
        self.maker(clean_db, "Carcano", ["M38"], position=20)

        registry = service.registry(clean_db)
        assert registry.extract("An M38 carbine") is None
        assert registry.extract("An M44 carbine") == "Mosin-Nagant"

    def test_a_disabled_maker_does_not_make_a_model_ambiguous(self, clean_db):
        keep = self.maker(clean_db, "Mosin-Nagant", ["M38"], position=10)
        gone = self.maker(clean_db, "Carcano", ["M38"], position=20)
        gone.enabled = False
        clean_db.flush()
        service.invalidate()

        assert service.registry(clean_db).extract("An M38 carbine") == keep.name
