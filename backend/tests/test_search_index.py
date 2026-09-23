"""The search index answers exactly what the unindexed scan answers.

The browse search has always been "every term must appear somewhere in the
listing", matched as a **substring** across six columns. Migration 0034 put a
trigram index behind that on both engines — pg_trgm on PostgreSQL, an FTS5
trigram table on SQLite — and the whole value of the change rests on one claim:
*the answers do not move.* These tests are that claim, checked term by term
against the six-column scan the index replaced.

**A word index was tried first and rejected.** PostgreSQL's `tsvector`
tokenizes, and this catalog tokenizes badly: `M1911A1` is one token, so "1911"
lost 86 listings; `K98k` is one token, so "k98" lost 59; and `S&W` reduces to
the single token `w`, which returned 1,736 listings instead of 211. Token
search cannot match inside a word, and matching inside a word is what this
search box has always promised. Trigrams can, which is why they won.

The first version of the SQLite path had a real bug that a corpus test like
this one is for: both terms of a two-word query carried the same bind parameter
name, so the second overwrote the first and "mosin german" was executed as
"german AND german".
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Item, Site
from app.services import search as search_service

#: Queries chosen for the ways they can go wrong rather than for coverage:
#: infix matches, punctuation, the LIKE wildcards, casing, quoted phrases,
#: terms too short for a trigram, and multiple terms that must be ANDed.
CORPUS = (
    "mauser",
    "enfield",
    "k98",
    "1911",
    "m1911a1",
    "303",
    ".303",
    "7.62x54r",
    "8mm",
    "s&w",
    "vz.24",
    "no.4",
    "m91/30",
    "lee-enfield",
    "MAUSER",
    "MaUsEr",
    "german bayonet",
    "mosin german",
    "enfield 303",
    '"lee enfield"',
    '"no.4 mk.i"',
    "38",
    "k9",
    "100% original",
    "a_b",
    "50%",
    "rifle",
    "rifles",
)


@pytest.fixture
def catalog(clean_db, seeded):
    """A catalog whose text contains every trap in the corpus above."""
    session = seeded
    site = Site(slug="idx", name="Index", base_url="https://i.test/")
    session.add(site)
    session.flush()
    rows = [
        (
            "GERMAN K98k Mauser rifle",
            "Collector grade, 100% original finish.",
            "8mm Mauser",
            "Mauser",
            "Germany",
            "Rifle",
        ),
        (
            "RUSSIAN Mosin-Nagant M91/30",
            "Russian rifle, arsenal refinished.",
            "7.62x54R",
            "Izhevsk",
            "Russia",
            "Rifle",
        ),
        (
            "Colt M1911A1 pistol",
            "US service pistol, 50% blue.",
            ".45 ACP",
            "Colt",
            "United States",
            "Handgun",
        ),
        (
            "BRITISH Lee-Enfield No.4 Mk.I",
            "Rifles of the Commonwealth.",
            ".303 British",
            "Enfield",
            "United Kingdom",
            "Rifle",
        ),
        (
            "Bayonet, German",
            "Fits the K98. Marked a_b on the ricasso.",
            None,
            None,
            "Germany",
            "Edged",
        ),
        (
            "S&W Model 10 revolver",
            "Smith & Wesson, .38 S&W chambering.",
            ".38 S&W",
            "Smith & Wesson",
            "United States",
            "Handgun",
        ),
        (
            "Czech vz.24 short rifle",
            "Brno production.",
            "8mm Mauser",
            "Brno",
            "Czech Republic",
            "Rifle",
        ),
    ]
    for index, (title, description, caliber, maker, country, category) in enumerate(rows):
        session.add(
            Item(
                site_id=site.id,
                external_key=f"k{index}",
                url=f"https://i.test/{index}",
                title=title,
                description=description,
                caliber=caliber,
                manufacturer=maker,
                country=country,
                category=category,
                is_active=True,
            )
        )
    session.commit()
    return session


def _ids(session, query: str) -> set[int]:
    stmt = search_service.apply_filters(
        select(Item.id),
        kinds=None,
        site_ids=None,
        categories=None,
        calibers=None,
        countries=None,
        manufacturers=None,
        models=None,
        forms=None,
        curio_states=None,
        availability="all",
        search=query,
        min_price=None,
        max_price=None,
        new_since_hours=None,
        price_drops_only=False,
    )
    return {row for (row,) in session.execute(stmt).all()}


class TestTheIndexAgreesWithTheScan:
    @pytest.fixture(autouse=True)
    def _reset(self):
        search_service.forget_search_index()
        yield
        search_service.forget_search_index()

    def test_the_test_is_actually_exercising_the_index(self, catalog):
        """Otherwise every assertion below compares the scan with itself and
        passes on a database that has no index at all."""
        assert search_service._search_index() == "sqlite"

    @pytest.mark.parametrize("query", CORPUS)
    def test_the_answers_are_identical(self, catalog, query):
        indexed = _ids(catalog, query)

        search_service._index_kind = "columns"
        scanned = _ids(catalog, query)

        assert indexed == scanned, (
            f"{query!r} answered differently: the index "
            f"{'added' if indexed - scanned else 'lost'} "
            f"{sorted(indexed ^ scanned)}"
        )

    def test_terms_are_still_anded(self, catalog):
        """The bug the first SQLite version had. Two clauses shared one bind
        parameter name, so the second overwrote the first and this returned
        every German listing instead of none."""
        assert _ids(catalog, "mosin german") == set()
        assert _ids(catalog, "mosin russian")

    def test_a_term_may_land_in_a_different_field(self, catalog):
        """ "enfield 303" is a maker and a caliber, and the document is the six
        fields joined so a query can reach across them."""
        assert len(_ids(catalog, "enfield 303")) == 1

    def test_a_phrase_cannot_match_across_a_field_boundary(self, catalog):
        """The fields are joined by a newline, which cannot be typed into the
        search box. A space would let "germany rifle" match a listing whose
        country is Germany and whose category is Rifle, and neither field
        contains the phrase."""
        assert _ids(catalog, '"germany rifle"') == set()


class TestWhatTheIndexIsMadeOf:
    def test_the_document_carries_every_searched_field(self, catalog):
        item = catalog.query(Item).filter(Item.title.like("GERMAN K98k%")).one()
        for value in ("K98k", "100% original", "8mm Mauser", "Mauser", "Germany", "Rifle"):
            assert value in item.search_document

    def test_it_is_maintained_by_the_database(self, catalog):
        """Nothing in the application writes it, so nothing can forget to."""
        item = catalog.query(Item).filter(Item.title.like("Colt%")).one()
        item.title = "Colt Python revolver"
        catalog.commit()
        catalog.refresh(item)
        assert "Python" in item.search_document
        assert "M1911A1" not in item.search_document

    def test_and_a_renamed_listing_is_findable_under_its_new_text(self, catalog):
        """The update trigger's delete half. Without it the old text stays in
        the index and the listing answers to a title it no longer has."""
        search_service.forget_search_index()
        item = catalog.query(Item).filter(Item.title.like("Colt%")).one()
        item.title = "Colt Python revolver"
        catalog.commit()

        assert _ids(catalog, "python")
        assert _ids(catalog, "m1911a1") == set()

    def test_a_deleted_listing_leaves_the_index(self, catalog):
        search_service.forget_search_index()
        assert _ids(catalog, "vz.24")
        catalog.query(Item).filter(Item.title.like("Czech%")).delete()
        catalog.commit()
        assert _ids(catalog, "vz.24") == set()
