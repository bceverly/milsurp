"""`make reclassify`, and what --recompute is allowed to overwrite.

Two modes and, since the caliber rules were reworked, a third position between
them. The default fills blanks only: a value the vendor stated is theirs.
``--recompute`` overwrites, because most stored values were derived here rather
than stated and a fix to the rules otherwise never reaches the listings that
need it.

The trouble is that it overwrote *everything*. Correcting 172 calibers after a
caliber fix cost 138 listings their manufacturer -- a maker the vendor supplied,
which cannot be re-derived from the text and comes back only on that site's
next scan. So ``--fields`` says which of the four it may touch, and the rest
keep the fill-blanks-only behavior.
"""

from __future__ import annotations

import argparse

import pytest
from cli import RECOMPUTABLE, cmd_reclassify

from app.models import Item, Site


@pytest.fixture
def site(clean_db):
    row = Site(slug="recl", name="Recl", base_url="https://r.test/")
    clean_db.add(row)
    clean_db.commit()
    return row


@pytest.fixture
def listing(clean_db, site):
    """A listing whose stored values the text does not agree with.

    The caliber is wrong in a way the rules now fix -- a Breda shotgun labeled
    with the cartridge of the rifles Breda built in the 1890s -- and the maker
    is one no rule can re-derive from this title.
    """
    row = Item(
        site_id=site.id,
        external_key="k1",
        url="https://r.test/1",
        title="BREDA ASTRO 12 GA",
        caliber="6.5x52mm Carcano",
        manufacturer="Breda Meccanica Bresciana",
        is_active=True,
    )
    clean_db.add(row)
    clean_db.commit()
    return row


def _run(**kwargs):
    args = argparse.Namespace(recompute=False, fields=",".join(RECOMPUTABLE))
    for key, value in kwargs.items():
        setattr(args, key, value)
    return cmd_reclassify(args)


class TestTheDefault:
    def test_it_leaves_a_stored_value_alone(self, clean_db, listing):
        """A value the vendor stated is theirs, and this command has to be safe
        to run against a catalog that has some."""
        _run()
        clean_db.refresh(listing)
        assert listing.caliber == "6.5x52mm Carcano"


class TestRecompute:
    def test_it_corrects_the_caliber(self, clean_db, listing):
        _run(recompute=True)
        clean_db.refresh(listing)
        assert listing.caliber == "12-gauge"

    def test_and_costs_the_listing_its_maker(self, clean_db, listing):
        """The behavior that makes the unscoped form expensive: nothing in
        "BREDA ASTRO 12 GA" re-derives "Breda Meccanica Bresciana"."""
        _run(recompute=True)
        clean_db.refresh(listing)
        assert listing.manufacturer != "Breda Meccanica Bresciana"


class TestScopingIt:
    def test_only_the_named_field_is_overwritten(self, clean_db, listing):
        _run(recompute=True, fields="caliber")
        clean_db.refresh(listing)
        assert listing.caliber == "12-gauge"
        assert listing.manufacturer == "Breda Meccanica Bresciana"

    def test_a_field_left_out_still_fills_a_blank(self, clean_db, listing):
        """Left out means "do not overwrite", not "do not touch": a blank is
        not a value somebody stated, so filling it overrules nobody."""
        listing.caliber = None
        clean_db.commit()

        _run(recompute=True, fields="manufacturer")
        clean_db.refresh(listing)
        assert listing.caliber == "12-gauge"

    def test_several_fields_can_be_named(self, clean_db, listing):
        _run(recompute=True, fields="caliber,country")
        clean_db.refresh(listing)
        assert listing.caliber == "12-gauge"
        assert listing.manufacturer == "Breda Meccanica Bresciana"

    def test_an_unknown_field_is_refused_rather_than_ignored(self, clean_db, listing):
        """Silently ignoring a typo would run the unscoped form under a name
        that promised otherwise."""
        assert _run(recompute=True, fields="calibre") == 1
        clean_db.refresh(listing)
        assert listing.caliber == "6.5x52mm Carcano"

    def test_the_default_is_every_field(self, clean_db, listing):
        """So the flag changes nothing for anybody who does not pass it."""
        _run(recompute=True)
        clean_db.refresh(listing)
        assert listing.manufacturer != "Breda Meccanica Bresciana"
