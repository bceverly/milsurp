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

**And ``--fields`` was not enough**, which is what provenance is for. Scoped to
nothing but the caliber the flag still changed 3,187 of 11,038 listings, 2,251
of them to nothing at all, because it cannot tell a caliber the rules guessed
from one the dealer printed. Now it can: the scan stamps each value with who
supplied it, and a rebuild declines anything marked ``vendor`` -- **and
anything unmarked**, which is every row written before that existed. Half the
tests below exist to hold that second half, because it is the one that looks
like the command not working.
"""

from __future__ import annotations

import argparse

import pytest
from cli import RECOMPUTABLE, cmd_reclassify

from app.models import Item, Site
from app.services import provenance


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
        # Stamped as the rules', because that is what these tests are about:
        # whether a rebuild corrects what the rules got wrong. The vendor's own
        # values and the unmarked ones have their own class below.
        caliber_source=provenance.DERIVED,
        manufacturer_source=provenance.DERIVED,
        country_source=provenance.DERIVED,
        condition_source=provenance.DERIVED,
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


class TestWhoseValueItIs:
    """The gate that ``--fields`` alone could not provide."""

    def test_a_vendor_value_is_not_rebuilt(self, clean_db, listing):
        """Sixty years of surplus is full of rebarreled guns and the dealer has
        the thing in their hand."""
        listing.caliber_source = provenance.VENDOR
        clean_db.commit()

        _run(recompute=True, fields="caliber")
        clean_db.refresh(listing)
        assert listing.caliber == "6.5x52mm Carcano"

    def test_nor_is_one_whose_origin_nobody_recorded(self, clean_db, listing):
        """The important half. Every row written before provenance existed has
        no source, and treating those as fair game is exactly the damage this
        was built to prevent -- 2,251 listings cleared in one run."""
        listing.caliber_source = None
        clean_db.commit()

        _run(recompute=True, fields="caliber")
        clean_db.refresh(listing)
        assert listing.caliber == "6.5x52mm Carcano"

    def test_a_catalog_value_is_the_rules_too(self, clean_db, listing):
        """The armory is not the vendor. It filled a blank from the model the
        listing names, and a better rule may fill it better."""
        listing.caliber_source = provenance.CATALOG
        clean_db.commit()

        _run(recompute=True, fields="caliber")
        clean_db.refresh(listing)
        assert listing.caliber == "12-gauge"

    def test_a_rebuilt_field_is_restamped(self, clean_db, listing):
        """So the *next* fix can reach it. Without this the rows the rules own
        never say so and every run starts from the same standstill."""
        listing.caliber_source = provenance.CATALOG
        clean_db.commit()

        _run(recompute=True, fields="caliber")
        clean_db.refresh(listing)
        assert listing.caliber_source == provenance.DERIVED

    def test_a_field_outside_fields_keeps_its_source(self, clean_db, listing):
        """It was not rebuilt, so nothing new is known about where it came
        from and saying otherwise would be a lie the next run acts on."""
        listing.manufacturer_source = provenance.VENDOR
        clean_db.commit()

        _run(recompute=True, fields="caliber")
        clean_db.refresh(listing)
        assert listing.manufacturer_source == provenance.VENDOR


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
