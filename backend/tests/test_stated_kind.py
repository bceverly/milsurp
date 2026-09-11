"""The type a vendor states per listing, which outranks every heuristic here.

``kind_from_category`` already covered the case where a *section* says what
things are — "Handguns" tells you something no pattern gets from "BELGIAN
Model 1910/22 Browning". But a section is one label over hundreds of listings,
and two vendors state it per listing instead: Simpson Ltd. in a ``Type`` field
and GunPrime in each product's own taxons.

**Simpson made the case.** 1,051 of their 5,241 listings typed as neither rifle
nor handgun, because collector shorthand carries no noun to key on — "SWISS
1906/24 RIG", "DWM P.08 FINNISH MILITARY", "ERFURT 1918 MILITARY". Every one
carries ``Type: Pistol``.

**And the blank is what makes it safe.** Simpson leave ``Type`` empty on
accessories: 112 of the 129 accessory-sounding titles in their first 500 Lugers
have none. So a value is a positive claim rather than a default, which is why
it may outrank even the accessory test — "LUGER P.08 1941 RIG" is a pistol, and
"rig" is in the accessory vocabulary.
"""

from __future__ import annotations

import pytest

from app.services.classify import enrich


def kind(title, stated_kind=None, category=None, description=None):
    found = enrich(title=title, description=description, category=category, stated_kind=stated_kind)
    return "rifle" if found["is_rifle"] else "pistol" if found["is_pistol"] else "other"


class TestWhatTheVendorSaidAboutThisListing:
    @pytest.mark.parametrize(
        ("title", "stated", "expected"),
        [
            ("SWISS 1906/24 RIG", "Pistol", "pistol"),
            ("DWM P.08 FINNISH MILITARY", "Pistol", "pistol"),
            ("ERFURT 1918 MILITARY", "Pistol", "pistol"),
            ("BSW MODEL 625Z", "Rifle", "rifle"),
            ("Remington 1867", "Revolver", "pistol"),
            ("SAUER & SOHN 16 BORE", "Shotgun", "rifle"),
        ],
    )
    def test_a_title_with_no_noun_in_it_is_typed_anyway(self, title, stated, expected):
        """None of these says rifle, pistol, revolver or anything else a
        pattern can read. The dealer looking at the gun did."""
        assert kind(title, stated_kind=stated) == expected

    def test_it_beats_the_accessory_vocabulary(self):
        """ "Rig" is an accessory word and this is a pistol sold in its
        holster. The vendor leaving Type blank on the actual holsters is what
        earns this precedence."""
        assert kind("LUGER P.08 1941 RIG", stated_kind="Pistol") == "pistol"

    def test_it_beats_a_section_that_says_otherwise(self):
        """A section is one label over hundreds of listings; this is about
        one. Simpson file a handful of rifles under their Walther shelf."""
        assert kind("WALTHER SPORT MODEL", stated_kind="Rifle", category="Walther") == "rifle"


class TestSayingNothingIsAnAnswer:
    @pytest.mark.parametrize(
        "title",
        [
            "MAUSER P.08 LUGER MAGAZINE",
            "LUGER P.08 MILITARY HOLSTER 1941",
            "REPRODUCTION LUGER TAKEDOWN TOOL",
            "LUGER LP.08 SNAIL DRUM MAGAZINE",
        ],
    )
    def test_an_accessory_is_left_to_the_heuristics(self, title):
        """Simpson leave Type blank on these, so nothing overrides the usual
        reading — which already gets them right."""
        assert kind(title, stated_kind=None, category="Lugers") == "other"

    def test_a_blank_string_is_the_same_as_nothing(self):
        """The field comes back as "" rather than null for some rows."""
        assert kind("MAUSER P.08 LUGER MAGAZINE", stated_kind="", category="Lugers") == "other"

    def test_a_word_that_names_no_type_changes_nothing(self):
        """ "Combination" is a gun with a rifle barrel and a shotgun barrel,
        and kind_from_category reads it as neither rather than both."""
        before = kind("Some Ordinary Rifle")
        assert kind("Some Ordinary Rifle", stated_kind="Curio") == before


class TestItSurvivesAReclassify:
    """The reason it is a column rather than something applied during a scan.

    ``reclassify`` re-derives everything from what the row holds, so a type
    worked out at scan time and not written down is thrown away by the next
    rebuild — which is exactly the trap ``--fields`` was added for.
    """

    def test_the_column_is_on_the_row(self):
        from app.models import Item

        assert "stated_kind" in {column.name for column in Item.__table__.columns}

    def test_enrich_reads_it_the_same_way_reclassify_will(self, clean_db):
        from app.models import Item, Site
        from app.services import classify

        site = Site(slug="s", name="S", base_url="https://s.test/")
        clean_db.add(site)
        clean_db.commit()
        row = Item(
            site_id=site.id,
            external_key="k",
            url="https://s.test/1",
            title="ERFURT 1918 MILITARY",
            category="Lugers",
            stated_kind="Pistol",
            is_active=True,
        )
        clean_db.add(row)
        clean_db.commit()

        derived = classify.enrich(
            row.title, row.description, None, category=row.category, stated_kind=row.stated_kind
        )
        assert derived["is_pistol"] is True


class TestTheVendorsThatStateIt:
    def test_simpson_reads_its_type_field(self):
        from app.scrapers.simpson_ltd import item_from_record

        record = {
            "SKU": "C1",
            "Title": "ERFURT 1918 MILITARY",
            "Type": "Pistol",
            "imageUrls": [],
        }
        assert item_from_record(record, "Lugers").stated_kind == "Pistol"

    def test_and_leaves_it_alone_when_they_say_nothing(self):
        from app.scrapers.simpson_ltd import item_from_record

        record = {"SKU": "C2", "Title": "LUGER MAGAZINE", "Type": "", "imageUrls": []}
        assert item_from_record(record, "Lugers").stated_kind is None

    def test_gunprime_reads_it_off_the_taxon(self):
        """Their taxons already carried it:
        ``categories/firearms/pistols/semi-auto-pistols``."""
        from app.scrapers.gunprime import kind_of

        assert kind_of(["categories/firearms/pistols/semi-auto-pistols"]) == "Pistol"
        assert kind_of(["categories/firearms/rifles/semi-auto-rifles"]) == "Rifle"

    def test_and_says_nothing_for_a_thing_that_is_not_a_firearm(self):
        from app.scrapers.gunprime import kind_of

        assert kind_of(["categories/ammunition"]) is None
        assert kind_of(["categories/accessories/firearm"]) is None


class TestItAlsoGuardsTheArmoryMatch:
    """The same fact, used a second way.

    A designation is not unique — "Model 1911" is a Colt automatic and a
    Schmidt-Rubin rifle — so ``_contradicted`` throws away a model whose kind
    the listing contradicts. It read only the title, which works when the
    seller wrote a type word ("Swiss K1911 Carbine Straight Pull *Rifle*") and
    not otherwise: **28 Swiss straight-pulls titled "SWISS M1911" were filed as
    Colt automatics**, and every one carried the vendor's ``Type: Rifle``.
    """

    @pytest.fixture
    def two_1911s(self, clean_db):
        from app.models import ArmoryStatus, FirearmKind, FirearmModel

        colt = FirearmModel(
            name="M1911A1",
            aliases="M1911",
            kind=FirearmKind.PISTOL,
            country="United States",
            status=ArmoryStatus.APPROVED,
            position=1000,
        )
        swiss = FirearmModel(
            name="Schmidt-Rubin Model 1911",
            aliases="K1911",
            kind=FirearmKind.RIFLE,
            country="Switzerland",
            status=ArmoryStatus.APPROVED,
            position=1000,
        )
        clean_db.add_all([colt, swiss])
        clean_db.commit()
        from app.services import armory

        armory.invalidate()
        return colt, swiss

    def test_a_title_with_no_type_word_used_to_take_the_wrong_one(self, clean_db, two_1911s):
        """Without the vendor's word there is nothing to go on, and the Colt
        wins on id. This is the state the 28 were in."""
        from app.services import armory

        assert armory.match(clean_db, "SWISS M1911").model == "M1911A1"

    def test_the_vendors_word_rejects_it(self, clean_db, two_1911s):
        """No model is a better answer than the wrong one: a model that is
        wrong about the kind is wrong about the caliber and the maker too."""
        from app.services import armory

        assert armory.match(clean_db, "SWISS M1911", stated_kind="Rifle").model != "M1911A1"

    def test_and_leaves_the_right_one_alone(self, clean_db, two_1911s):
        from app.services import armory

        assert armory.match(clean_db, "COLT M1911", stated_kind="Pistol").model == "M1911A1"

    def test_a_title_that_says_it_still_works_on_its_own(self, clean_db, two_1911s):
        """The title was the only source before this and stays a source."""
        from app.services import armory

        assert armory.match(clean_db, "M1911 Straight Pull Rifle").model != "M1911A1"

    def test_a_stated_kind_that_names_no_type_changes_nothing(self, clean_db, two_1911s):
        from app.services import armory

        assert armory.match(clean_db, "SWISS M1911", stated_kind="Curio").model == "M1911A1"
