"""Where one listing sits among the others of the same gun.

The measurements that shaped this are in the module docstring of
``app/services/pricing.py``: surplus prices are skewed hard enough that a
dollar-scaled axis is unreadable, so the bar is scaled by rank. What is pinned
here is the arithmetic, the grouping rule, and the refusals.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmModel, Item, Site
from app.services import pricing


@pytest.fixture
def sites(clean_db):
    rows = [
        Site(slug=f"vendor-{n}", name=f"Vendor {n}", base_url=f"https://v{n}.test/")
        for n in range(1, 4)
    ]
    clean_db.add_all(rows)
    clean_db.commit()
    return rows


@pytest.fixture
def model(clean_db):
    row = FirearmModel(name="Karabiner 98k", status=ArmoryStatus.APPROVED)
    clean_db.add(row)
    clean_db.commit()
    return row


def _listing(session, site, price, *, model=None, maker="Mauser", caliber="8mm Mauser", **kw):
    item = Item(
        site_id=site.id,
        external_key=f"k-{site.id}-{price}-{maker}-{caliber}",
        url="https://example.test/x",
        title="A rifle",
        current_price=price,
        manufacturer=maker,
        caliber=caliber,
        firearm_model_id=model.id if model else None,
        **{"is_active": True, **kw},
    )
    session.add(item)
    session.flush()
    return item


class TestThePercentileArithmetic:
    def test_the_ends(self):
        assert pricing.percentile([10.0, 20.0, 30.0], 0) == 10.0
        assert pricing.percentile([10.0, 20.0, 30.0], 100) == 30.0

    def test_the_middle(self):
        assert pricing.percentile([10.0, 20.0, 30.0], 50) == 20.0

    def test_it_interpolates_between_neighbours(self):
        assert pricing.percentile([0.0, 100.0], 25) == 25.0

    def test_one_value_is_every_percentile_of_itself(self):
        assert pricing.percentile([7.0], 25) == 7.0

    def test_nothing_is_zero_rather_than_an_exception(self):
        assert pricing.percentile([], 50) == 0.0


class TestWhoCountsAsAPeer:
    """All three of model, maker and cartridge, because any two of them leave
    a group that is not comparable: a model alone puts an Inland M1 Carbine
    beside a Winchester, and a model with a maker puts an 8x50mmR Steyr M95
    beside an 8x56mmR one."""

    def test_a_different_model_is_not_a_peer(self, clean_db, sites, model):
        other = FirearmModel(name="Gewehr 98", status=ArmoryStatus.APPROVED)
        clean_db.add(other)
        clean_db.flush()
        for price in (100.0, 200.0, 300.0):
            _listing(clean_db, sites[0], price, model=model)
        odd = _listing(clean_db, sites[0], 999.0, model=other)
        clean_db.commit()

        found = pricing.position(clean_db, odd)
        assert found is None

    def test_the_maker_splits_a_model_several_firms_built(self, clean_db, sites, model):
        """An Inland M1 Carbine is not a Winchester, and the armory saying so
        is what makes the difference checkable."""
        from app.models import Manufacturer

        first = Manufacturer(name="Mauser", status=ArmoryStatus.APPROVED)
        second = Manufacturer(name="Steyr", status=ArmoryStatus.APPROVED)
        clean_db.add_all([first, second])
        clean_db.flush()
        model.manufacturers = [first, second]
        clean_db.commit()

        for price in (100.0, 200.0, 300.0):
            _listing(clean_db, sites[0], price, model=model, maker="Mauser")
        _listing(clean_db, sites[0], 900.0, model=model, maker="Steyr")
        clean_db.commit()

        subject = _listing(clean_db, sites[1], 150.0, model=model, maker="Mauser")
        clean_db.commit()
        found = pricing.position(clean_db, subject)
        assert found.count == 4  # the three Mausers plus this one, not the Steyr

    def test_the_maker_does_not_split_a_model_one_firm_built(self, clean_db, sites, model):
        """The maker is settled by the model, so asking the listings to agree
        about it adds nothing and can only split them on a bad derivation."""
        from app.models import Manufacturer

        only = Manufacturer(name="Mauser", status=ArmoryStatus.APPROVED)
        clean_db.add(only)
        clean_db.flush()
        model.manufacturers = [only]
        clean_db.commit()

        _listing(clean_db, sites[0], 100.0, model=model, maker="Mauser")
        _listing(clean_db, sites[1], 200.0, model=model, maker="Oberndorf")
        subject = _listing(clean_db, sites[2], 300.0, model=model, maker=None)
        clean_db.commit()
        assert pricing.position(clean_db, subject).count == 3

    def test_nor_a_model_the_armory_credits_to_nobody(self, clean_db, sites, model):
        """Seven Yugoslav M57 Tokarevs, all in 7.62x25mm, split into groups of
        two and three because three vendors' titles read as Zastava -- who
        built them -- and two as Tokarev, who designed the pattern. With no
        maker on the model row, the maker on a listing is a derivation, and
        demanding agreement compares derivations rather than guns."""
        _listing(clean_db, sites[0], 240.0, model=model, maker="Tokarev")
        _listing(clean_db, sites[1], 300.0, model=model, maker="Zastava")
        subject = _listing(clean_db, sites[2], 450.0, model=model, maker="Zastava")
        clean_db.commit()
        assert pricing.position(clean_db, subject).count == 3

    def test_a_different_cartridge_is_not_a_peer(self, clean_db, sites, model):
        for price in (100.0, 200.0, 300.0):
            _listing(clean_db, sites[0], price, model=model, caliber="8mm Mauser")
        _listing(clean_db, sites[0], 900.0, model=model, caliber=".308 Winchester")
        clean_db.commit()

        subject = _listing(clean_db, sites[1], 150.0, model=model, caliber="8mm Mauser")
        clean_db.commit()
        assert pricing.position(clean_db, subject).count == 4

    def test_a_de_listed_one_is_not_a_peer(self, clean_db, sites, model):
        """It is not on a shelf you can buy from, so it is not part of what
        this one is competing with."""
        for price in (100.0, 200.0, 300.0):
            _listing(clean_db, sites[0], price, model=model)
        _listing(clean_db, sites[0], 5000.0, model=model, is_active=False)
        clean_db.commit()

        subject = _listing(clean_db, sites[1], 150.0, model=model)
        clean_db.commit()
        found = pricing.position(clean_db, subject)
        assert (found.count, found.high) == (4, 300.0)

    def test_the_listing_counts_as_one_of_its_own_peers(self, clean_db, sites, model):
        """Taking it out would move the median by its own absence, and it is
        one of the listings on the shelf."""
        for price in (100.0, 200.0, 300.0):
            _listing(clean_db, sites[0], price, model=model)
        clean_db.commit()
        subject = clean_db.query(Item).filter_by(current_price=200.0).one()
        assert pricing.position(clean_db, subject).count == 3


class TestWhenItSaysNothing:
    def test_too_few_peers(self, clean_db, sites, model):
        """Two listings are a pair, not a distribution, and a marker halfway
        between them says nothing."""
        first = _listing(clean_db, sites[0], 100.0, model=model)
        _listing(clean_db, sites[1], 200.0, model=model)
        clean_db.commit()
        assert pricing.position(clean_db, first) is None

    def test_no_model_match(self, clean_db, sites):
        for price in (100.0, 200.0, 300.0):
            _listing(clean_db, sites[0], price, model=None)
        clean_db.commit()
        subject = clean_db.query(Item).filter_by(current_price=100.0).one()
        assert pricing.position(clean_db, subject) is None

    def test_no_price(self, clean_db, sites, model):
        for price in (100.0, 200.0, 300.0):
            _listing(clean_db, sites[0], price, model=model)
        clean_db.commit()
        subject = _listing(clean_db, sites[1], None, model=model)
        clean_db.commit()
        assert pricing.position(clean_db, subject) is None

    def test_no_caliber(self, clean_db, sites, model):
        subject = _listing(clean_db, sites[0], 100.0, model=model, caliber=None)
        clean_db.commit()
        assert pricing.position(clean_db, subject) is None


class TestWhatItReports:
    @pytest.fixture
    def shelf(self, clean_db, sites, model):
        # 100, 200, 300, 400, 9000 -- a long tail, which is the normal shape.
        for n, price in enumerate((100.0, 200.0, 300.0, 400.0, 9000.0)):
            _listing(clean_db, sites[n % len(sites)], price, model=model)
        clean_db.commit()
        return model

    def _at(self, session, price):
        return pricing.position(session, session.query(Item).filter_by(current_price=price).one())

    def test_the_ends_are_the_true_range(self, clean_db, shelf):
        found = self._at(clean_db, 300.0)
        assert (found.low, found.high) == (100.0, 9000.0)

    def test_the_median_is_the_middle_value_not_the_mean(self, clean_db, shelf):
        """The mean of that shelf is $2,000, which describes none of them."""
        assert self._at(clean_db, 300.0).median == 300.0

    def test_the_cheapest_undercuts_everybody_else(self, clean_db, shelf):
        """Four of the five are dearer than it, so it undercuts 80% of them.
        The first version had this backwards and printed "cheaper than 0%" for
        the cheapest listing on the shelf."""
        assert self._at(clean_db, 100.0).cheaper_than == 80

    def test_the_dearest_undercuts_nobody(self, clean_db, shelf):
        assert self._at(clean_db, 9000.0).cheaper_than == 0

    def test_but_the_dearest_marker_is_at_the_far_end(self, clean_db, shelf):
        """The bug this separation exists for. The dearest of five undercuts
        four of them -- 80% -- and a marker at 80% of a bar whose right end is
        labeled with this listing's own price is simply wrong."""
        assert self._at(clean_db, 9000.0).position == 100.0

    def test_and_the_cheapest_marker_is_at_the_near_end(self, clean_db, shelf):
        assert self._at(clean_db, 100.0).position == 0.0

    def test_the_marker_walks_evenly_up_the_ranks(self, clean_db, shelf):
        assert [self._at(clean_db, p).position for p in (100.0, 200.0, 300.0, 400.0)] == [
            0.0,
            25.0,
            50.0,
            75.0,
        ]

    def test_the_position_ignores_how_long_the_tail_is(self, clean_db, shelf):
        """The whole reason the bar is drawn by rank: $400 is the fourth of
        five whether the fifth is $9,000 or $900."""
        assert self._at(clean_db, 400.0).position == 75.0
        assert self._at(clean_db, 400.0).cheaper_than == 20

    def test_it_counts_the_vendors(self, clean_db, shelf):
        assert self._at(clean_db, 300.0).vendors == 3

    def test_identical_prices_do_not_all_claim_to_undercut_each_other(self, clean_db, sites, model):
        for site in sites:
            _listing(clean_db, site, 500.0, model=model)
        clean_db.commit()
        found = pricing.position(clean_db, clean_db.query(Item).first())
        assert found.cheaper_than == 0

    def test_and_identical_prices_share_the_middle_of_their_own_block(self, clean_db, sites, model):
        """Rather than being spread across the run they occupy by an accident
        of sort order, which would put three identical listings in three
        different places."""
        for site in sites:
            _listing(clean_db, sites[0] if False else site, 500.0, model=model)
        clean_db.commit()
        markers = {pricing.position(clean_db, item).position for item in clean_db.query(Item).all()}
        assert markers == {50.0}

    def test_it_says_what_made_them_peers(self, clean_db, shelf):
        found = self._at(clean_db, 300.0)
        assert (found.model, found.manufacturer, found.caliber) == (
            "Karabiner 98k",
            "Mauser",
            "8mm Mauser",
        )


class TestTheEndpoint:
    def test_it_answers_null_when_there_is_nothing_to_say(
        self, client, admin_headers, clean_db, sites, model
    ):
        item = _listing(clean_db, sites[0], 100.0, model=model)
        clean_db.commit()
        response = client.get(f"/api/items/{item.id}/price-position", headers=admin_headers)
        assert response.status_code == 200
        assert response.json() is None

    def test_it_answers_with_the_spectrum(self, client, admin_headers, clean_db, sites, model):
        for n, price in enumerate((100.0, 200.0, 300.0)):
            _listing(clean_db, sites[n], price, model=model)
        clean_db.commit()
        item = clean_db.query(Item).filter_by(current_price=200.0).one()

        body = client.get(f"/api/items/{item.id}/price-position", headers=admin_headers).json()
        assert body["count"] == 3
        assert body["cheaper_than"] == 33
        assert body["median"] == 200.0

    def test_an_unknown_item_is_a_404(self, client, admin_headers):
        assert (
            client.get("/api/items/999999/price-position", headers=admin_headers).status_code == 404
        )

    def test_a_stranger_cannot_read_it(self, client, clean_db, sites, model):
        item = _listing(clean_db, sites[0], 100.0, model=model)
        clean_db.commit()
        assert client.get(f"/api/items/{item.id}/price-position").status_code == 401
