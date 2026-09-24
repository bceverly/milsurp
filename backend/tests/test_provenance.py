"""Where a stored field's value came from, and what may rewrite it.

The gap this closes had a measured cost. `reclassify --recompute`, scoped to
nothing but the caliber, changed **3,187 of 11,038 listings** -- 2,251 of them
to nothing at all -- because nothing recorded whether a stored caliber was the
rules' guess or the dealer's own words. A Carl Gustafs 1896 stated as 6.5x55mm
Swedish came back 8mm Mauser.

Two properties carry the whole design and both are tested here:

* **A spelling is not a source.** The armory normalizes ".32 ACP" and "7.65mm
  Browning" into one answer and the maker table spells "S&W" as "Smith &
  Wesson". Recording either as the catalog's opinion would hand a later
  recompute permission over the vendor's own field -- the original bug wearing
  a hat.
* **Unknown is protected.** Every row written before this existed has no
  source, and the safe direction to be wrong in is to leave it alone.
"""

from __future__ import annotations

import pytest

from app.models import Item, Site
from app.services import provenance


@pytest.fixture
def item():
    return Item(site_id=1, external_key="k", url="u", title="t")


class TestFilling:
    def test_it_writes_the_value_and_the_source(self, item):
        assert provenance.fill(item, "caliber", "8mm Mauser", provenance.DERIVED) is True
        assert item.caliber == "8mm Mauser"
        assert item.caliber_source == provenance.DERIVED

    def test_it_will_not_overwrite(self, item):
        provenance.fill(item, "caliber", "8mm Mauser", provenance.VENDOR)
        assert provenance.fill(item, "caliber", ".303 British", provenance.DERIVED) is False
        assert item.caliber == "8mm Mauser"
        assert item.caliber_source == provenance.VENDOR

    def test_an_empty_value_writes_nothing(self, item):
        """Including the source. A field nobody filled has no origin to
        record, and recording one would make a blank look like a decision."""
        assert provenance.fill(item, "caliber", None, provenance.DERIVED) is False
        assert item.caliber_source is None


class TestAdoptingAValueOfUnknownOrigin:
    """Rows written before provenance existed carry no source, and ``fill``
    returns early on a filled field -- so without adoption they never gain one,
    and a recompute (which refuses unknown origins) can never reach them."""

    def test_a_matching_unattributed_value_is_adopted(self, item):
        item.caliber = "8mm Mauser"
        assert (
            provenance.fill(item, "caliber", "8mm Mauser", provenance.DERIVED, adopt=True) is False
        )
        assert item.caliber == "8mm Mauser"
        assert item.caliber_source == provenance.DERIVED

    def test_not_without_being_asked(self, item):
        """The scan asks only for a vendor whose scraper states no facts."""
        item.caliber = "8mm Mauser"
        provenance.fill(item, "caliber", "8mm Mauser", provenance.DERIVED)
        assert item.caliber_source is None

    def test_a_value_the_rules_would_not_produce_stays_unknown(self, item):
        item.caliber = "7.92x57mm"
        provenance.fill(item, "caliber", "8mm Mauser", provenance.DERIVED, adopt=True)
        assert item.caliber == "7.92x57mm"
        assert item.caliber_source is None

    def test_a_recorded_source_is_never_replaced(self, item):
        provenance.fill(item, "caliber", "8mm Mauser", provenance.VENDOR)
        provenance.fill(item, "caliber", "8mm Mauser", provenance.DERIVED, adopt=True)
        assert item.caliber_source == provenance.VENDOR


class TestRespelling:
    def test_it_changes_the_value_and_keeps_the_source(self, item):
        """A vendor who states "7.65mm Browning" is not being argued with, they
        are being spelled."""
        provenance.fill(item, "caliber", "7.65mm Browning", provenance.VENDOR)
        assert provenance.respell(item, "caliber", ".32 ACP") is True
        assert item.caliber == ".32 ACP"
        assert item.caliber_source == provenance.VENDOR

    def test_it_does_not_invent_a_source(self, item):
        """A normalization of a value of unknown origin leaves it unknown --
        and therefore still protected."""
        item.caliber = "7.65mm Browning"
        provenance.respell(item, "caliber", ".32 ACP")
        assert item.caliber_source is None


class TestPermission:
    @pytest.mark.parametrize(
        ("source", "allowed"),
        [
            (provenance.DERIVED, True),
            (provenance.CATALOG, True),
            (provenance.VENDOR, False),
            (None, False),
        ],
    )
    def test_who_may_be_rebuilt(self, item, source, allowed):
        item.caliber_source = source
        assert provenance.may_recompute(item, "caliber") is allowed

    def test_every_recomputable_field_has_a_source_column(self):
        """The two lists are maintained in different files, and a field in one
        and not the other is a field the gate silently never protects."""
        from cli import RECOMPUTABLE

        assert set(RECOMPUTABLE) == set(provenance.SOURCE_COLUMNS)

    def test_the_source_columns_exist_on_the_model(self):
        for column in provenance.SOURCE_COLUMNS.values():
            assert hasattr(Item, column), column


class TestWhatTheScanRecords:
    """The scan is the only thing that can tell the three apart, because it is
    the only place that sees the vendor's own fields."""

    @pytest.fixture
    def scanned(self, clean_db):
        from app.scrapers.base import ScrapedItem
        from app.services import scan_service

        site = Site(slug="prov", name="Prov", base_url="https://p.test/")
        clean_db.add(site)
        clean_db.commit()

        def scan(**fields):
            scraped = ScrapedItem(
                external_key=fields.pop("key"),
                url="https://p.test/x",
                title=fields.pop("title"),
                **fields,
            )
            item, _, _ = scan_service._upsert_item(
                clean_db, site, scraped, run=None, seen_at=scan_service.utcnow()
            )
            clean_db.commit()
            return item

        return scan

    def test_a_vendor_field_is_stamped_vendor(self, scanned):
        item = scanned(key="a", title="Some rifle", caliber="8x57mm")
        assert item.caliber == "8x57mm"
        assert item.caliber_source == provenance.VENDOR

    def test_a_value_read_out_of_the_title_is_stamped_derived(self, scanned):
        item = scanned(key="b", title="Yugoslav M48 Mauser rifle 8mm")
        assert item.caliber
        assert item.caliber_source == provenance.DERIVED

    def test_a_vendor_who_states_it_later_takes_the_stamp_back(self, scanned):
        """Otherwise a row the rules filled first would never learn that the
        shop has since published the answer itself, and a rebuild would keep
        permission it no longer has."""
        first = scanned(key="c", title="Yugoslav M48 Mauser rifle 8mm")
        assert first.caliber_source == provenance.DERIVED

        again = scanned(key="c", title="Yugoslav M48 Mauser rifle 8mm", caliber="7.92x57mm")
        assert again.caliber == "7.92x57mm"
        assert again.caliber_source == provenance.VENDOR

    def test_a_field_nothing_could_fill_has_no_source(self, scanned):
        item = scanned(key="d", title="Mystery object")
        assert item.caliber is None
        assert item.caliber_source is None


class TestAnOverrideIsTheStrongest:
    """A correction is made knowing what the rules said, which makes the rules
    the last thing entitled to argue with it."""

    @pytest.fixture
    def corrected(self, clean_db):
        from app.services import overrides

        site = Site(slug="ovr", name="Ovr", base_url="https://o.test/")
        clean_db.add(site)
        clean_db.commit()
        item = Item(
            site_id=site.id,
            external_key="k",
            url="https://o.test/1",
            title="BREDA ASTRO 12 GA",
            caliber="12-gauge",
            caliber_source=provenance.DERIVED,
        )
        clean_db.add(item)
        clean_db.commit()
        overrides.save(clean_db, item, {"caliber": "20-gauge"}, note="measured it")
        clean_db.commit()
        overrides.apply_to(clean_db, item)
        clean_db.commit()
        return item

    def test_applying_one_stamps_the_field(self, corrected):
        assert corrected.caliber == "20-gauge"
        assert corrected.caliber_source == provenance.OVERRIDE

    def test_and_a_rebuild_may_not_touch_it(self, corrected):
        """The hole this closes predates provenance: `reclassify` never read
        the override table at all, so a rebuild undid a person's correction
        until the next scan put it back."""
        assert provenance.may_recompute(corrected, "caliber") is False

    def test_a_correction_that_agrees_with_the_rules_is_still_a_correction(self, clean_db):
        from app.services import overrides

        site = Site(slug="ovr2", name="Ovr2", base_url="https://o2.test/")
        clean_db.add(site)
        clean_db.commit()
        item = Item(
            site_id=site.id,
            external_key="k",
            url="https://o2.test/1",
            title="BREDA ASTRO 12 GA",
            caliber="12-gauge",
            caliber_source=provenance.DERIVED,
        )
        clean_db.add(item)
        clean_db.commit()
        overrides.save(clean_db, item, {"caliber": "12-gauge"}, note="checked, it is right")
        clean_db.commit()

        overrides.apply_to(clean_db, item)
        assert item.caliber_source == provenance.OVERRIDE
