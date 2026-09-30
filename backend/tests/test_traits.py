"""Import marks, matching numbers and the finish, read out of what a vendor wrote.

Every sentence here is one a vendor actually published, found by running the
reader over production's 9,970 active firearms and reading what it said. The
ones that caught it out are kept as tests beside the ones it gets right, since
they are the reason each rule is shaped the way it is.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Item, Site
from app.services import traits


def _read(text: str) -> traits.Reading:
    return traits.read("Rifle", text)


class TestImportMarks:
    @pytest.mark.parametrize(
        "text",
        [
            "Bright bore, muzzle=7.57+. Our import mark. Includes muzzle cover.",
            "CAI import marked on the barrel.",
            "The left side of the receiver bears import markings.",
            "Century Arms import mark on the bottom of the trigger guard.",
            "A post-'68 import mark is present on the right side of the barrel.",
        ],
    )
    def test_a_mark(self, text):
        assert _read(text).import_marked is True

    @pytest.mark.parametrize(
        "text",
        [
            "Not import marked.",
            "No import marks found. Overall condition is very good.",
            "There are no import marks on this carbine.",
            "Oh, I can't find an import mark anywhere on this rifle.",
            "Not import-marked, a very unusual example.",
            "No import stamps.",
            "It is all matching with no import marks.",
        ],
    )
    def test_the_absence_of_one(self, text):
        """ "Not import marked" contains "import marked", so the words in front
        are read first -- the same trap curio's "not C&R" is."""
        assert _read(text).import_marked is False

    def test_a_denial_does_not_reach_across_the_sentence(self):
        assert _read("The metal has no pitting and an import mark on the barrel.").import_marked

    def test_one_mark_anywhere_answers_it(self):
        text = "No import marks on the receiver. Small import mark under the barrel."
        assert _read(text).import_marked is True

    def test_silence_is_not_a_no(self):
        assert _read("Bright bore, strong rifling.").import_marked is None

    def test_the_words_are_kept(self):
        found = _read("Mechanically fine. Our import mark. Includes sling.")
        assert found.quotes[traits.IMPORT] == "Our import mark"


class TestMatchingNumbers:
    @pytest.mark.parametrize(
        "text",
        [
            "All matching serial numbers.",
            "It is all matching and has the proper Crown N commercial proofs.",
            "The numbered parts are matching.",
            "Serial numbers are matching.",
            "Swiss K11 carbine with matching numbers made at WF Bern in 1929.",
            "All visible serial numbers match, including the magazine.",
            "This example is all matching including the magazine.",
            "All numbers appear matching.",
        ],
    )
    def test_all_matching(self, text):
        assert _read(text).numbers_match is True

    @pytest.mark.parametrize(
        "text",
        [
            "Non-matching bolt.",
            "Serial numbers are non-matching.",
            "Matching bolt, mis-match magazine.",
            "Matching numbers except the bolt.",
            "Numbers matching except magazine.",
            "Matching numbers (minus the mag).",
            "The magazine floor plate force matched.",
            "The stock does not match the receiver.",
            "Mostly matching serial numbers on rifle.",
            "Bolt electro-penciled to match.",
        ],
    )
    def test_any_mismatch_is_not_all_matching(self, text):
        assert _read(text).numbers_match is False

    @pytest.mark.parametrize(
        "text",
        [
            "Comes in a non-matching plastic box with non-matching test target.",
            "This gun comes with a non matching shoulder stock.",
            "Comes with an original Smith & Wesson box (mismatched serial number).",
        ],
    )
    def test_an_accessory_that_does_not_match_is_not_the_gun(self, text):
        assert _read(text).numbers_match is None

    def test_an_exception_to_the_condition_is_not_one_to_the_numbers(self):
        text = "Swedish M96 rifle with all matching numbers in excellent condition except for the bore."
        assert _read(text).numbers_match is True

    def test_generic_prose_about_the_model_is_not_about_this_gun(self):
        text = "Surviving examples, especially with matching numbers, are highly desirable."
        assert _read(text).numbers_match is None


class TestTheFinish:
    @pytest.mark.parametrize(
        "text",
        [
            "Reblued finish, elm stock and handguard.",
            "Combloc arsenal refurbished.",
            "The gun has been re-blued and lightly buffed throughout.",
            "Arsenal refinished metal, walnut stock and handguard.",
            "The metal retains 95% of its arsenal rework parkerized finish.",
        ],
    )
    def test_refinished(self, text):
        assert _read(text).refinished is True

    @pytest.mark.parametrize(
        "text",
        [
            "Original blued finish, walnut stock and handguard.",
            "The original finish shows some holstering wear.",
            "Retains 95%+ of its original finish.",
        ],
    )
    def test_original(self, text):
        assert _read(text).refinished is False

    @pytest.mark.parametrize(
        "text",
        [
            "The stock has been sanded and refinished.",
            "Plain walnut stock, lightly refinished.",
            "The refinished stock is solid with numerous dings.",
            "The walnut grips are solid with much of the original finish missing.",
        ],
    )
    def test_the_wood_is_not_the_question(self, text):
        assert _read(text).refinished is None

    @pytest.mark.parametrize(
        "text",
        [
            "Unlike most of the Garands listed here I do not think this one has been refinished.",
            "The metalwork shows no signs of having been refinished.",
            "The markings are crisp, so it doesn't look to have been refinished at any time.",
            "We do not see any signs that it was refinished at any time.",
        ],
    )
    def test_a_denial_is_original_or_nothing_never_refinished(self, text):
        assert _read(text).refinished is not True

    @pytest.mark.parametrize(
        "text",
        [
            "The finish may have been a factory refinish at some point.",
            "This gun appears to be a very old refinish.",
        ],
    )
    def test_a_guess_is_not_a_statement(self, text):
        assert _read(text).refinished is None

    @pytest.mark.parametrize(
        ("text", "percent"),
        [
            ("It has retained about 93-94% of its original finish.", 93),
            ("Retains 95%+ of its original finish.", 95),
            ("Its original finish rates roughly 85% with general high edge wear.", 85),
            ("The barrel and action show about 80-85% of the original finish.", 80),
        ],
    )
    def test_how_much_of_the_finish_remains(self, text, percent):
        assert _read(text).finish_percent == percent


class TestTheConditionGrade:
    @pytest.mark.parametrize(
        ("text", "grade"),
        [
            ("Overall condition is good.", "good"),
            ("The rifle remains in overall very good condition.", "very_good"),
            ("CONDITION: Excellent", "excellent"),
            ("SWISS M29 LUGER MADE IN 1944 IN VERY GOOD OVERALL CONDITION", "very_good"),
            ("Receiver is in excellent + condition.", "excellent"),
            ("The gun is in like-new condition.", "like_new"),
            ("M1917 Enfield rifle, offered in good surplus condition.", "good"),
            ("SWISS M96/11 MADE IN 1900 IN POOR CONDITION", "poor"),
            ("GECO DSM 34 RIFLE IN GOOD CONDITION MISSING ITS CLEANING ROD", "good"),
            ("It is complete, fully functional, and in fair condition.", "fair"),
            ("Overall condition is fair to good.", "fair"),
        ],
    )
    def test_the_whole_gun_stated_in_words(self, text, grade):
        found = _read(text)
        assert found.grade == grade
        assert found.quotes[traits.CONDITION]

    @pytest.mark.parametrize(
        "text",
        [
            "The bore is in very good condition.",
            "Includes a leather holster in good condition.",
            "The stock is in fair condition with a crack at the wrist.",
            "Mechanically it is in good working order.",
            "The sight is in good condition, though it is a bit loose in the dovetail.",
        ],
    )
    def test_a_part_or_an_accessory_is_not_the_gun(self, text):
        """The ``condition`` column is exactly this mistake at scale: every
        value in it is a bore grade."""
        assert _read(text).grade is None

    @pytest.mark.parametrize(
        ("word", "grade"),
        [
            ("Excellent +", "excellent"),
            ("very good plus", "very_good"),
            ("Like-New", "like_new"),
            ("near mint", "like_new"),
            ("Poor to Fair", "poor"),
            ("Service Grade", None),
        ],
    )
    def test_words_on_one_scale(self, word, grade):
        assert traits.grade_word(word) == grade


class TestTheBackfillAndTheFilter:
    @pytest.fixture
    def stored(self, clean_db):
        session = clean_db
        site = Site(slug="traits-backfill", name="Traits", base_url="https://t.test/")
        session.add(site)
        session.flush()
        for key, description, rifle in (
            (
                "clean",
                (
                    "All matching. No import marks. Original blued finish. "
                    "Overall condition is excellent."
                ),
                True,
            ),
            ("marked", "Our import mark. Non-matching bolt.", True),
            ("quiet", "A rifle.", True),
            ("bayonet", "All matching bayonet. No import marks.", False),
        ):
            session.add(
                Item(
                    site_id=site.id,
                    external_key=key,
                    url=f"https://t.test/{key}",
                    title=key,
                    description=description,
                    is_rifle=rifle,
                    is_bayonet=not rifle,
                )
            )
        session.flush()
        return session

    def _by_key(self, session):
        return {i.external_key: i for i in session.execute(select(Item)).scalars()}

    def test_it_reads_and_grades(self, stored):
        counts = traits.backfill(stored)
        rows = self._by_key(stored)
        clean = rows["clean"]
        assert (clean.import_marked, clean.numbers_match, clean.refinished) == (False, True, False)
        assert clean.condition_grade == "excellent"
        assert clean.trait_quotes[traits.IMPORT] == "No import marks"
        assert (rows["marked"].import_marked, rows["marked"].numbers_match) == (True, False)
        assert rows["quiet"].trait_quotes is None
        assert counts["examined"] == 4

    def test_the_filter_combines_groups_and_ignores_what_is_not_a_gun(self, stored):
        traits.backfill(stored)

        def keys(*values):
            statement = select(Item.external_key).where(traits.traits_clause(list(values)))
            return set(stored.execute(statement).scalars())

        assert keys("unmarked") == {"clean"}
        assert keys("unmarked", "import_marked") == {"clean", "marked"}
        assert keys("unmarked", "not_matching") == set()
        assert keys("all_matching", "original_finish") == {"clean"}

    def test_an_unknown_trait_is_refused(self):
        with pytest.raises(ValueError, match="unknown trait"):
            traits.trait_clause("probably")


class TestTheBrowseApi:
    @pytest.fixture
    def stocked(self, seeded):
        site = seeded.query(Site).order_by(Site.id).first()
        for key, description, rifle in (
            ("clean", "All matching. No import marks. Overall condition is excellent.", True),
            ("marked", "Our import mark. Non-matching bolt. Overall condition is good.", True),
            ("bayonet", "All matching bayonet. No import marks.", False),
        ):
            item = Item(
                site_id=site.id,
                external_key=f"api-{key}",
                url=f"https://t.test/{key}",
                title=f"Listing {key}",
                description=description,
                current_price=500.0,
                is_rifle=rifle,
                is_bayonet=not rifle,
            )
            traits.apply(item, trusted=True)
            seeded.add(item)
        seeded.commit()
        return seeded

    def test_the_filters_and_the_facets(self, client, admin_headers, stocked):
        page = client.get(
            "/api/items?trait=unmarked&trait=all_matching", headers=admin_headers
        ).json()
        assert [item["title"] for item in page["items"]] == ["Listing clean"]
        facets = {row["value"]: row for row in page["facets"]["traits"]}
        assert facets["unmarked"]["group"] == "Import marks"

        graded = client.get("/api/items?grade=good", headers=admin_headers).json()
        assert [item["title"] for item in graded["items"]] == ["Listing marked"]
        grades = [
            row["value"]
            for row in client.get("/api/items", headers=admin_headers).json()["facets"]["grades"]
        ]
        assert grades.index("excellent") < grades.index("good")

    def test_a_listing_says_it_in_the_vendors_words(self, client, admin_headers, stocked):
        page = client.get("/api/items?search=clean", headers=admin_headers).json()
        clean = page["items"][0]
        assert clean["numbers_match"] is True
        assert clean["condition_grade_label"] == "Excellent"
        assert clean["trait_quotes"]["numbers"] == "All matching"

    def test_but_a_bayonet_carries_none_of_it(self, client, admin_headers, stocked):
        page = client.get("/api/items?search=bayonet", headers=admin_headers).json()
        assert page["items"][0]["numbers_match"] is None

    def test_an_unknown_value_is_refused(self, client, admin_headers):
        assert client.get("/api/items?trait=probably", headers=admin_headers).status_code == 400
        assert client.get("/api/items?grade=mint", headers=admin_headers).status_code == 400

    def test_a_saved_search_keeps_them(self, client, admin_headers):
        saved = client.post(
            "/api/saved-searches",
            json={"name": "Clean ones", "query": "trait=unmarked&grade=excellent"},
            headers=admin_headers,
        )
        assert saved.status_code == 201, saved.text
        assert "trait=unmarked" in saved.json()["query"]
