"""The finer kind: revolver, carbine, percussion pistol.

The browse filter's five Types **partition the catalog** and answer "what am I
looking at". They cannot answer "show me the revolvers", which is a question a
collector asks constantly: a flintlock pistol and a percussion revolver are
both "Handguns" up there, and a carbine is a Rifle.

``FirearmKind`` has carried the vocabulary since the armory shipped, but on the
*model* rather than the listing — so it could not be faceted, and it threw away
the second source. Simpson Ltd. state "Revolver" and "Shotgun" per listing.

So it is resolved once and stored on the row: the model's kind first, because
it is curated and the finer of the two, then the vendor's word.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import FirearmKind, Item, Site
from app.services import search
from app.services.classify import finer_kind


class TestResolvingIt:
    def test_the_model_wins_because_it_is_finer(self):
        """A curated model knows percussion_revolver where a vendor writing
        per listing says only "Revolver"."""
        assert finer_kind(FirearmKind.PERCUSSION_REVOLVER, "Revolver") == "percussion_revolver"

    def test_the_vendors_word_is_used_when_no_model_matched(self):
        """4,713 listings carry one and no model, which is most of the reach."""
        assert finer_kind(None, "Revolver") == "revolver"
        assert finer_kind(None, "Shotgun") == "shotgun"

    def test_a_word_that_names_no_form_is_left_unanswered(self):
        """Simpson use "Combination" for a rifle-and-shotgun barrel pair and
        "Gun Deal" for a bundle. Forcing those into the nearest bucket would
        be inventing an answer."""
        assert finer_kind(None, "Combination") is None
        assert finer_kind(None, "Gun Deal") is None

    def test_neither_source_means_no_answer(self):
        """A real state rather than a gap: a quarter of the firearms in the
        catalog are in it."""
        assert finer_kind(None, None) is None
        assert finer_kind(None, "") is None

    def test_the_spelling_is_the_enums_own(self):
        """The column holds FirearmKind values, so the facet can be labelled
        from the same table the armory page uses."""
        assert finer_kind(None, "carbine") in {k.value for k in FirearmKind}


class TestFilteringOnIt:
    @pytest.fixture
    def catalog(self, clean_db):
        site = Site(slug="s", name="S", base_url="https://s.test/")
        clean_db.add(site)
        clean_db.commit()
        rows = [
            ("A Colt Dragoon", True, "percussion_revolver"),
            ("A S&W Model 10", True, "revolver"),
            ("A Mosin M44", False, "carbine"),
            ("A Mosin 91/30", False, "rifle"),
            ("A listing nothing could be said about", False, None),
        ]
        for title, pistol, kind in rows:
            clean_db.add(
                Item(
                    site_id=site.id,
                    external_key=title,
                    url=f"https://s.test/{title}",
                    title=title,
                    is_pistol=pistol,
                    is_rifle=not pistol,
                    kind=kind,
                    is_active=True,
                )
            )
        clean_db.commit()
        return clean_db

    def _count(self, session, query_string):
        parsed = search.parse_query(query_string)
        return session.scalar(search.apply_filters(select(func.count(Item.id)), **parsed.filters))

    def test_one_form(self, catalog):
        assert self._count(catalog, "form=revolver&availability=all") == 1

    def test_several_at_once(self, catalog):
        """A multi-select facet, like caliber and maker beside it."""
        assert self._count(catalog, "form=revolver&form=carbine&availability=all") == 2

    def test_it_narrows_within_a_type_rather_than_replacing_it(self):
        """The two questions compose: Handguns *and* revolvers."""
        parsed = search.parse_query("kind=pistol&form=revolver")
        assert parsed.filters["kinds"] == ["pistol"]
        assert parsed.filters["forms"] == ["revolver"]

    def test_listings_with_no_form_are_not_swept_into_one(self, catalog):
        """Nothing should claim the quarter of the catalog that has no answer."""
        every = sum(
            self._count(catalog, f"form={form}&availability=all")
            for form in ("percussion_revolver", "revolver", "carbine", "rifle")
        )
        assert every == 4

    def test_an_unknown_parameter_is_still_refused(self):
        """The saved-search guard: a query that has rotted must fail in front
        of somebody rather than mail an empty result."""
        with pytest.raises(search.BadQuery):
            search.parse_query("frm=revolver")


class TestItIsAFacet:
    def test_the_query_parameter_is_registered(self):
        assert search.QUERY_PARAMS["form"] is True

    def test_and_maps_to_what_apply_filters_calls_it(self):
        assert search.parse_query("form=revolver").filters["forms"] == ["revolver"]

    def test_the_schema_carries_it(self):
        from app.schemas import ItemFacets

        assert "forms" in ItemFacets.model_fields

    def test_every_value_it_can_produce_has_a_label(self):
        """The column holds enum values and the page shows words. Labelled
        server-side so the browse page and the armory page cannot drift."""
        from app.api.armory import KIND_LABELS

        assert {kind.value for kind in FirearmKind} <= {k.value for k in KIND_LABELS}
