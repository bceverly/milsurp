"""A search term matches the names of the listing's armory model, too.

"Russian 91/30 rifle" never says Mosin, and the model it was matched to --
"Mosin-Nagant M91/30" -- does. On production, 2026-10-06, 14 of the 82 listings
a search for "91/30" found were missing from a search for "mosin nagant", and 9
of the 36 for "m44".
"""

from __future__ import annotations

from urllib.parse import urlencode

import pytest

from app.models import ArmoryStatus, FirearmModel, Item, Site
from app.services import search


@pytest.fixture
def catalog(seeded):
    site = seeded.query(Site).order_by(Site.id).first()
    m9130 = FirearmModel(
        name="Mosin-Nagant M91/30",
        aliases="M91/30\n91/30",
        status=ArmoryStatus.APPROVED,
    )
    m44 = FirearmModel(name="Mosin-Nagant M44", aliases="M44", status=ArmoryStatus.APPROVED)
    seeded.add_all([m9130, m44])
    seeded.flush()
    rows = [
        ("Russian 91/30 rifle, Izhevsk 1943", m9130),
        ("Mosin Nagant M91/30 hex receiver", m9130),
        ("Soviet M44 carbine", m44),
        ("Swiss K31 carbine", None),
        # Says Mosin in its own text and is linked to nothing: still found.
        ("Mosin Nagant parts lot", None),
    ]
    for n, (title, model) in enumerate(rows):
        seeded.add(
            Item(
                site_id=site.id,
                external_key=f"s{n}",
                url=f"https://s.test/{n}",
                title=title,
                is_active=True,
                firearm_model_id=model.id if model else None,
            )
        )
    seeded.commit()
    return seeded


def titles(session, query):
    found = search.run(session, search.parse_query(urlencode({"search": query})))
    return sorted(item.title for item in found)


class TestTheModelIsPartOfTheListing:
    def test_mosin_nagant_finds_what_its_models_found(self, catalog):
        assert titles(catalog, "mosin nagant") == [
            "Mosin Nagant M91/30 hex receiver",
            "Mosin Nagant parts lot",
            "Russian 91/30 rifle, Izhevsk 1943",
            "Soviet M44 carbine",
        ]

    def test_every_term_still_has_to_be_found(self, catalog):
        """Each term may be found in the text or the model, but every one has
        to be found: "mosin k31" is no listing at all."""
        assert titles(catalog, "mosin k31") == []
        assert titles(catalog, "nagant izhevsk") == ["Russian 91/30 rifle, Izhevsk 1943"]

    def test_a_listing_matched_to_no_model_answers_as_before(self, catalog):
        assert titles(catalog, "k31") == ["Swiss K31 carbine"]

    @pytest.mark.parametrize("name", ["Mosin-Nagant", "91/30", "M44", "K31"])
    def test_the_armory_s_counts_still_agree_with_the_search(self, catalog, name):
        assert search.count_mentions_many(catalog, [name])[name] == search.count_mentions(
            catalog, name
        )
