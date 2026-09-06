"""The maker list as data: matching, seeding, and re-filing after an edit."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Item, Manufacturer, Site
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
