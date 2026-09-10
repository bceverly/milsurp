"""Three answers to "where is this from", and the order they are asked in.

The listing's own always wins. Then the model, which states where the *pattern*
comes from. Then the maker, which is only a proxy for that and is asked last.

The order is the whole design, so it is pinned here rather than left to be
inferred from a chain of ``or`` in one line of scan_service.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmKind, FirearmModel, Item, Manufacturer, Site
from app.services import armory, manufacturers
from app.services.scan_service import _apply_catalog


@pytest.fixture
def site(clean_db):
    """Somewhere for the listings to hang off. No scraper needed: these tests
    call _apply_catalog directly rather than running a scan."""
    row = Site(slug="precedence", name="Precedence", base_url="https://example.test/")
    clean_db.add(row)
    clean_db.commit()
    return row


@pytest.fixture
def catalog(clean_db):
    """A maker that says where it is, and a model that disagrees with it.

    Deliberately contradictory: Zastava is in Yugoslavia and built Mausers,
    which are a German pattern. That is the case the ordering exists for, and
    a fixture where the two agree would pass whatever order they were asked in.
    """
    zastava = Manufacturer(name="Zastava", status=ArmoryStatus.APPROVED, country="Yugoslavia")
    clean_db.add(zastava)
    clean_db.flush()

    model = FirearmModel(
        name="Mauser M24/47",
        aliases="M24/47",
        kind=FirearmKind.RIFLE,
        country="Germany",
        status=ArmoryStatus.APPROVED,
    )
    clean_db.add(model)
    clean_db.commit()
    armory.invalidate()
    manufacturers.invalidate()
    yield zastava, model
    armory.invalidate()
    manufacturers.invalidate()


def _item(session, site: Site, **kwargs) -> Item:
    item = Item(
        site_id=site.id,
        external_key=f"k-{kwargs.get('title', 'x')}",
        url="https://example.test/x",
        **kwargs,
    )
    session.add(item)
    session.flush()
    return item


class TestTheOrderCountriesAreAskedIn:
    def test_the_listing_wins_over_everything(self, clean_db, site, catalog):
        """Whoever wrote the listing was looking at the gun. A country in the
        title is a statement about *this* rifle and outranks both tables."""
        item = _item(
            clean_db,
            site,
            title="YUGOSLAVIAN Mauser M24/47 Rifle",
            country="Yugoslavia",
            manufacturer="Zastava",
        )
        _apply_catalog(clean_db, item, trusted=True)
        assert item.country == "Yugoslavia"

    def test_the_model_wins_over_the_maker(self, clean_db, site, catalog):
        """The model states where the pattern comes from and is right about it.
        The maker's country is a proxy, and here it is the wrong answer: an
        M24/47 built in Kragujevac is still a German pattern."""
        item = _item(
            clean_db,
            site,
            title="Mauser M24/47 Rifle",
            manufacturer="Zastava",
        )
        _apply_catalog(clean_db, item, trusted=True)
        assert item.country == "Germany"

    def test_the_maker_answers_when_nothing_else_can(self, clean_db, site, catalog):
        """The case this column was added for. Of 1,407 active listings with no
        country, 1,247 already carried a maker."""
        item = _item(
            clean_db,
            site,
            title="Zastava sporting rifle, no pattern named",
            manufacturer="Zastava",
        )
        _apply_catalog(clean_db, item, trusted=True)
        assert item.country == "Yugoslavia"

    def test_a_maker_with_no_country_still_says_nothing(self, clean_db, site, catalog):
        """A blank column is not an answer, and must not become one."""
        clean_db.add(Manufacturer(name="Nameless Works", status=ArmoryStatus.APPROVED))
        clean_db.commit()
        manufacturers.invalidate()

        item = _item(
            clean_db,
            site,
            title="Nameless Works rifle",
            manufacturer="Nameless Works",
        )
        _apply_catalog(clean_db, item, trusted=True)
        assert item.country is None

    def test_a_pending_maker_decides_nothing(self, clean_db, site, catalog):
        """The rule the whole armory runs on: a row nobody has vouched for is
        a question, and a question must not fill anything in."""
        clean_db.add(Manufacturer(name="Unchecked", status=ArmoryStatus.PENDING, country="France"))
        clean_db.commit()
        manufacturers.invalidate()

        item = _item(clean_db, site, title="Unchecked rifle", manufacturer="Unchecked")
        _apply_catalog(clean_db, item, trusted=True)
        assert item.country is None


class TestTheCaliberIsNeverOverruled:
    def test_a_stated_caliber_survives_the_model(self, clean_db, site, catalog):
        """Sixty years of surplus is full of rebarreled guns and the vendor has
        the thing in their hand. Pinned beside the country rules because it is
        the same principle pointed at the other field."""
        model = catalog[1]
        cartridge = armory.propose_caliber(clean_db, "7.92x57mm Mauser")
        if cartridge is not None:
            cartridge.status = ArmoryStatus.APPROVED
            model.calibers = [cartridge]
        clean_db.commit()
        armory.invalidate()

        item = _item(
            clean_db,
            site,
            title="Mauser M24/47 Rifle, rebarreled",
            caliber=".308 Winchester",
        )
        _apply_catalog(clean_db, item, trusted=True)
        assert item.caliber == ".308 Winchester"


class TestTheMatchIsRedoneOnEveryScan:
    """A listing's armory link is not a decision taken once when it was first
    met. Approve a model today and tonight's scan re-links every listing it
    reaches; rename or disable it and they let go again.

    This is the property that makes the armory worth editing at all, and it
    rests on one thing: `_upsert_item` calls `_apply_catalog` for *every*
    listing a scraper yields, not only the ones whose price or text changed.
    """

    def test_a_listing_picks_up_a_model_approved_after_it_was_stored(self, clean_db, site):
        item = _item(clean_db, site, title="Swedish Model 1896 Mauser rifle")
        pending = FirearmModel(
            name="Swedish Mauser M96",
            aliases="Model 1896",
            kind=FirearmKind.RIFLE,
            country="Sweden",
            status=ArmoryStatus.PENDING,
        )
        clean_db.add(pending)
        clean_db.commit()
        armory.invalidate()

        _apply_catalog(clean_db, item, trusted=True)
        assert item.firearm_model_id is None, "a pending row decides nothing"

        pending.status = ArmoryStatus.APPROVED
        clean_db.commit()
        armory.invalidate()

        _apply_catalog(clean_db, item, trusted=True)
        assert item.firearm_model_id == pending.id
        assert item.country == "Sweden"

    def test_it_lets_go_when_the_row_is_disabled(self, clean_db, site):
        model = FirearmModel(
            name="Swedish Mauser M96",
            aliases="Model 1896",
            kind=FirearmKind.RIFLE,
            status=ArmoryStatus.APPROVED,
        )
        clean_db.add(model)
        clean_db.commit()
        armory.invalidate()

        item = _item(clean_db, site, title="Swedish Model 1896 Mauser rifle")
        _apply_catalog(clean_db, item, trusted=True)
        assert item.firearm_model_id == model.id

        model.enabled = False
        clean_db.commit()
        armory.invalidate()

        _apply_catalog(clean_db, item, trusted=True)
        assert item.firearm_model_id is None

    def test_every_listing_goes_through_it_not_only_changed_ones(self):
        """Source-inspected, because the alternative is a scan that quietly
        stops re-matching anything whose price held steady -- which would look
        exactly like the armory not working, on the listings least likely to be
        looked at."""
        import inspect

        from app.services import scan_service

        body = inspect.getsource(scan_service._upsert_item)
        assert "_apply_catalog(session, item, trusted)" in body
        loop = inspect.getsource(scan_service.run_scan)
        assert "_upsert_item(session, site, entry, run, seen_at)" in loop


class TestBothCodePathsAgree:
    """`_apply_catalog` and `make reclassify` are two implementations of one
    decision, and every field either of them forgets has to be found by
    noticing it is missing. `is_police_surplus` was added to one and not the
    other once already; the maker's country was added to one and not the other
    on the very next change, and a full `--recompute` over 4,562 listings
    filled nothing at all.
    """

    def test_reclassify_asks_the_maker_about_the_country_too(self):
        backend = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (backend / "cli.py").read_text(encoding="utf-8")
        assert "manufacturers.country_for(session, chosen_maker)" in source
        # In both branches, and last in both: the default fills blanks, and
        # --recompute overwrites, but neither may put the firm above the model.
        assert "found.country or from_maker or item.country" in source
        assert 'derived["country"] or found.country or from_maker' in source

    def test_and_the_scan_path_does(self):
        import inspect

        from app.services import scan_service

        source = inspect.getsource(scan_service._apply_catalog)
        assert "manufacturers.country_for(" in source
        assert "item.country or found.country" in source
