"""Curio and relic eligibility, read out of what a vendor wrote.

Two things here carry the risk and everything else is detail.

**A four-digit number in a milsurp title is usually a name, not a date.**
"M1911A1" is 1911 whether the gun left Colt in 1943 or a reproduction shop
last year, and the reproduction is exactly the listing where being wrong costs
somebody something. So a bare year is only read as a date when it is not in a
designation context and does not appear in the armory model's own name.

**The judgment exists twice and must be one judgment.** ``status()`` answers
for a listing in hand and ``clause()`` answers for a filter over the catalog;
if they ever disagree, a browse count says one thing and the page it opens says
another. The agreement is asserted over every combination rather than assumed
from the two having been written together.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models import Item, Site
from app.services import curio

TODAY = date(2026, 6, 1)
CUTOFF = 2026 - curio.CURIO_YEARS  # 1976


class TestWhatTheVendorSaid:
    def test_saying_so_is_the_strongest_source(self):
        found = curio.read("Swiss K31", "Excellent bore. C&R FFL OK.")
        assert found.stated is True
        assert found.evidence == curio.BY_VENDOR

    def test_curio_spelled_out_counts_too(self):
        assert curio.read("Mauser", "A curio and relic eligible rifle.").stated is True

    def test_and_a_refusal_is_read_as_one(self):
        """ "not C&R" contains "C&R", so a naive match reads a refusal as a
        confirmation -- and does it on exactly the listings where the vendor
        went out of their way to warn somebody."""
        found = curio.read("Modern AR-15", "This is not C&R eligible.")
        assert found.stated is False
        assert curio.status(found.stated, found.year, today=TODAY) == curio.NOT_ELIGIBLE

    def test_the_vendor_outranks_the_arithmetic(self):
        """They are looking at the gun and at its proof marks."""
        found = curio.read("Rifle", "Made 2019. C&R eligible per ATF listing.")
        assert found.stated is True
        assert curio.status(found.stated, found.year, today=TODAY) == curio.ELIGIBLE


class TestAYearThatIsADate:
    @pytest.mark.parametrize(
        "text",
        [
            "K98k Mauser, dated 1939",
            "Mosin Nagant, mfg. 1939",
            "Rifle manufactured in 1939",
            "1939 production Tula",
        ],
    )
    def test_explicit_manufacture_phrasing_is_taken(self, text):
        found = curio.read(text)
        assert found.year == 1939
        assert found.evidence == curio.BY_DATE

    def test_the_earliest_of_several_wins(self):
        """A listing naming two years is usually a receiver and a later
        rebuild, and the question is when it was made."""
        assert curio.read("Rifle, dated 1943, refurbished 1955").year == 1943


class TestAYearThatIsAName:
    @pytest.mark.parametrize(
        "title",
        ["Colt M1911A1 .45 ACP", "Winchester Model 1873", "Enfield Mk 1917", "Type 38 Arisaka"],
    )
    def test_a_designation_is_not_a_date(self, title):
        found = curio.read(title)
        assert found.year is None
        assert curio.status(found.stated, found.year, today=TODAY) == curio.UNKNOWN

    def test_nor_is_a_pattern_written_as_a_fraction(self):
        assert curio.read("Mosin Nagant 91/30 rifle").year is None

    def test_the_armory_model_name_suppresses_its_own_year(self):
        """The armory's names are curated and approved, which is what makes
        this safe: "1891" against an M91/30 is recognisably the pattern."""
        assert curio.read("ARGENTINE 1891 Mauser", model_name="Model 1891 Mauser").year is None

    def test_but_a_year_the_model_does_not_carry_is_a_date(self):
        found = curio.read("1943 Izhevsk Mosin Nagant", model_name="Mosin-Nagant M91/30")
        assert found.year == 1943
        assert found.evidence == curio.BY_YEAR

    def test_a_new_gun_on_an_old_pattern_is_not_eligible(self):
        """The case the whole exercise exists for."""
        found = curio.read("Colt 1911 Government, new production 2021", model_name="M1911A1")
        assert curio.status(found.stated, found.year, today=TODAY) == curio.NOT_ELIGIBLE


class TestTheBoundaryRolls:
    def test_the_cut_off_follows_the_date(self):
        assert curio.cutoff(date(2026, 1, 1)) == 1976
        assert curio.cutoff(date(2027, 1, 1)) == 1977

    def test_a_gun_becomes_eligible_without_anything_changing(self):
        """1977 is not eligible in 2026 and is in 2027, which is the whole
        reason the column holds a year and not an answer."""
        assert curio.status(None, 1977, today=date(2026, 6, 1)) == curio.NOT_ELIGIBLE
        assert curio.status(None, 1977, today=date(2027, 6, 1)) == curio.ELIGIBLE

    def test_exactly_on_the_boundary_is_eligible(self):
        assert curio.status(None, CUTOFF, today=TODAY) == curio.ELIGIBLE
        assert curio.status(None, CUTOFF + 1, today=TODAY) == curio.NOT_ELIGIBLE

    def test_silence_is_unknown_rather_than_a_no(self):
        """The ATF's other limbs are museum certification and being novel or
        rare, neither of which this application can see. A gun under fifty may
        still be a curio, and saying otherwise is a claim nothing here can
        support."""
        assert curio.status(None, None, today=TODAY) == curio.UNKNOWN


#: Listings that are not firearms, as their flags would have them. A parts kit
#: is filed as a rifle too, and is still not one: it has no receiver.
NOT_FIREARMS = (
    {"is_bayonet": True},
    {},
    {"is_rifle": True, "is_parts_kit": True},
    {"is_pistol": True, "is_parts_kit": True},
)


class TestOnlyFirearms:
    """C&R is a category of firearm. A cap, a book or a bayonet has no status."""

    def test_a_rifle_or_a_handgun_has_one(self):
        assert curio.applies(is_rifle=True, is_pistol=False, is_parts_kit=False)
        assert curio.applies(is_rifle=False, is_pistol=True, is_parts_kit=False)

    @pytest.mark.parametrize("flags", NOT_FIREARMS)
    def test_nothing_else_does(self, flags):
        assert not curio.applies(
            is_rifle=flags.get("is_rifle", False),
            is_pistol=flags.get("is_pistol", False),
            is_parts_kit=flags.get("is_parts_kit", False),
        )


class TestTheTwoReadingsAgree:
    """``status()`` for one listing, ``clause()`` for a filter. One judgment."""

    @pytest.fixture
    def stocked(self, clean_db):
        """``clean_db`` rather than ``session``: this asserts set equality over
        the whole table, and other tests in the suite commit listings of their
        own. On a shared table the sums are somebody else's."""
        session = clean_db
        site = Site(slug="curio-test", name="Curio", base_url="https://c.test/")
        session.add(site)
        session.flush()
        combinations = [
            (stated, year)
            for stated in (True, False, None)
            for year in (1943, CUTOFF, CUTOFF + 1, 2021, None)
        ]
        for n, (stated, year) in enumerate(combinations):
            session.add(
                Item(
                    site_id=site.id,
                    external_key=f"c{n}",
                    url=f"https://c.test/{n}",
                    title=f"Listing {n}",
                    cr_stated=stated,
                    manufacture_year=year,
                    is_rifle=True,
                )
            )
        # And the same evidence on things that are not firearms, which no
        # state may pick up: C&R is a class of firearm.
        for n, flags in enumerate(NOT_FIREARMS):
            session.add(
                Item(
                    site_id=site.id,
                    external_key=f"x{n}",
                    url=f"https://c.test/x{n}",
                    title=f"Not a firearm {n}",
                    cr_stated=True,
                    manufacture_year=1943,
                    **flags,
                )
            )
        session.flush()
        return session, combinations

    @pytest.mark.parametrize("state", curio.STATES)
    def test_the_filter_returns_exactly_what_status_says(self, stocked, state):
        session, combinations = stocked
        by_clause = set(
            session.execute(select(Item.external_key).where(curio.clause(state))).scalars()
        )
        by_status = {
            f"c{n}"
            for n, (stated, year) in enumerate(combinations)
            if curio.status(stated, year) == state
        }
        assert by_clause == by_status

    def test_and_between_them_they_cover_every_firearm_once(self, stocked):
        """No firearm in two buckets, none in none of them -- and nothing else
        in any of them."""
        session, combinations = stocked
        seen: list[str] = []
        for state in curio.STATES:
            seen += list(
                session.execute(select(Item.external_key).where(curio.clause(state))).scalars()
            )
        assert sorted(seen) == sorted(f"c{n}" for n in range(len(combinations)))

    def test_an_invented_state_is_refused(self):
        with pytest.raises(ValueError, match="unknown curio state"):
            curio.clause("probably")


class TestTheBackfill:
    """Migration 0037 runs this over everything already stored, because a fix
    to how a listing is *read* never reaches the listings already read."""

    @pytest.fixture
    def stored(self, clean_db):
        """Emptied first: the backfill reads every listing there is, so its
        counts only mean anything against a table this test owns."""
        session = clean_db
        site = Site(slug="curio-backfill", name="Curio", base_url="https://b.test/")
        session.add(site)
        session.flush()
        rows = [
            ("says", "Swiss K31", "C&R FFL OK."),
            ("dated", "Mauser K98k", "Dated 1939."),
            ("loose", "1943 Izhevsk Mosin", None),
            ("quiet", "Colt M1911A1", "A pistol."),
        ]
        for key, title, description in rows:
            session.add(
                Item(
                    site_id=site.id,
                    external_key=key,
                    url=f"https://b.test/{key}",
                    title=title,
                    description=description,
                )
            )
        session.flush()
        return session

    def _by_key(self, session):
        return {i.external_key: i for i in session.execute(select(Item)).scalars()}

    def test_it_reads_each_source(self, stored):
        counts = curio.backfill(stored)
        rows = self._by_key(stored)
        assert rows["says"].cr_stated is True
        assert rows["says"].cr_evidence == curio.BY_VENDOR
        assert (rows["dated"].manufacture_year, rows["dated"].cr_evidence) == (1939, curio.BY_DATE)
        assert (rows["loose"].manufacture_year, rows["loose"].cr_evidence) == (1943, curio.BY_YEAR)
        assert counts["examined"] == 4

    def test_a_listing_that_says_nothing_is_left_null(self, stored):
        """Not stamped "unknown" -- left unexamined, so a later run with
        tightened rules still looks at it."""
        curio.backfill(stored)
        quiet = self._by_key(stored)["quiet"]
        assert (quiet.cr_stated, quiet.manufacture_year, quiet.cr_evidence) == (None, None, None)

    def test_by_default_it_leaves_a_reading_alone(self, stored):
        curio.backfill(stored)
        rows = self._by_key(stored)
        rows["dated"].manufacture_year = 1901
        stored.flush()

        curio.backfill(stored)
        assert self._by_key(stored)["dated"].manufacture_year == 1901

    def test_and_recomputing_re_reads_it(self, stored):
        """The case for after the rules have been tightened, which is what
        `cli.py curio-backfill --recompute` is."""
        curio.backfill(stored)
        rows = self._by_key(stored)
        rows["dated"].manufacture_year = 1901
        stored.flush()

        curio.backfill(stored, only_missing=False)
        assert self._by_key(stored)["dated"].manufacture_year == 1939


class TestFilteringTheCatalog:
    @pytest.fixture
    def stocked(self, seeded):
        site = seeded.query(Site).order_by(Site.id).first()
        for key, stated, year in (
            ("old", None, 1943),
            ("new", None, 2021),
            ("said", True, None),
            ("quiet", None, None),
        ):
            seeded.add(
                Item(
                    site_id=site.id,
                    external_key=key,
                    url=f"https://f.test/{key}",
                    title=f"Listing {key}",
                    cr_stated=stated,
                    manufacture_year=year,
                    is_rifle=True,
                )
            )
        seeded.add(
            Item(
                site_id=site.id,
                external_key="bayonet",
                url="https://f.test/bayonet",
                title="Listing bayonet",
                cr_stated=True,
                manufacture_year=1943,
                is_bayonet=True,
            )
        )
        seeded.commit()
        return seeded

    def _keys(self, client, headers, query):
        """Keyed on the title: ItemOut does not carry the external key, which
        is the vendor's identifier and nothing a reader needs."""
        body = client.get(f"/api/items?{query}", headers=headers).json()
        return {row["title"].removeprefix("Listing ") for row in body["items"]}

    def test_eligible_takes_the_old_and_the_vouched_for(self, client, admin_headers, stocked):
        assert self._keys(client, admin_headers, "curio=eligible&availability=all") == {
            "old",
            "said",
        }

    def test_not_eligible_takes_the_modern_one(self, client, admin_headers, stocked):
        assert self._keys(client, admin_headers, "curio=not_eligible&availability=all") == {"new"}

    def test_unknown_takes_the_one_nothing_is_known_about(self, client, admin_headers, stocked):
        assert self._keys(client, admin_headers, "curio=unknown&availability=all") == {"quiet"}

    def test_the_filter_repeats_because_eligible_or_maybe_is_a_real_want(
        self, client, admin_headers, stocked
    ):
        assert self._keys(
            client, admin_headers, "curio=eligible&curio=unknown&availability=all"
        ) == {"old", "said", "quiet"}

    def test_an_invented_state_is_refused_rather_than_ignored(self, client, admin_headers, stocked):
        response = client.get("/api/items?curio=probably", headers=admin_headers)
        assert response.status_code == 400
        assert "probably" in response.json()["detail"]

    def test_a_listing_carries_its_own_verdict_and_its_working(
        self, client, admin_headers, stocked
    ):
        body = client.get("/api/items?curio=eligible&availability=all", headers=admin_headers)
        row = next(r for r in body.json()["items"] if r["title"] == "Listing old")
        assert row["curio"] == curio.ELIGIBLE
        assert row["curio_evidence"] is None or isinstance(row["curio_evidence"], str)
        assert row["manufacture_year"] == 1943

    def test_a_bayonet_carries_no_verdict_at_all(self, client, admin_headers, stocked):
        """Not "unknown", which would say the question is open. None."""
        body = client.get("/api/items?availability=all", headers=admin_headers).json()
        row = next(r for r in body["items"] if r["title"] == "Listing bayonet")
        assert row["curio"] is None
        assert row["curio_label"] is None
        assert row["curio_evidence"] is None

    def test_and_no_filter_state_picks_it_up(self, client, admin_headers, stocked):
        every = "&".join(f"curio={state}" for state in curio.STATES)
        assert "bayonet" not in self._keys(client, admin_headers, f"{every}&availability=all")

    def _facet(self, client, headers, query=""):
        body = client.get(f"/api/items?include_facets=true&{query}", headers=headers).json()
        return {row["value"]: row["count"] for row in body["facets"]["curio"]}

    def test_the_facet_counts_all_three_states(self, client, admin_headers, stocked):
        counts = self._facet(client, admin_headers, "availability=all")
        assert counts == {curio.ELIGIBLE: 2, curio.NOT_ELIGIBLE: 1, curio.UNKNOWN: 1}

    def test_and_is_not_narrowed_by_its_own_choice(self, client, admin_headers, stocked):
        """The property that makes the numbers worth reading: with the filter
        applied, counting over the current results would report zero of
        everything else and each entry would only describe the choice already
        made. Same reasoning as the Type facet beside it."""
        chosen = self._facet(client, admin_headers, "availability=all&curio=eligible")
        assert chosen == {curio.ELIGIBLE: 2, curio.NOT_ELIGIBLE: 1, curio.UNKNOWN: 1}

    def test_but_it_is_narrowed_by_everything_else(self, client, admin_headers, stocked):
        """It still has to answer "what would picking this give me *here*",
        so every other filter applies."""
        narrowed = self._facet(client, admin_headers, "availability=all&search=Listing+old")
        assert narrowed == {curio.ELIGIBLE: 1, curio.NOT_ELIGIBLE: 0, curio.UNKNOWN: 0}

    def test_each_entry_carries_the_words_a_reader_sees(self, client, admin_headers, stocked):
        body = client.get(
            "/api/items?include_facets=true&availability=all", headers=admin_headers
        ).json()
        labels = {row["value"]: row["label"] for row in body["facets"]["curio"]}
        assert labels[curio.NOT_ELIGIBLE] == "Not eligible by age"
        assert labels[curio.UNKNOWN] == "Not known"
