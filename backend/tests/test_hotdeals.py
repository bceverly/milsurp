"""What counts as a hot deal, and why the rule is four numbers rather than one.

The interesting tests here are the ones about what the rule *excludes*. Ranking
listings purely by how far below their peers they sit produces a page of
misclassified parts -- measured against the live catalog, the top of that list
was a $25 "GERMAN LUGER P.08 PISTOL SEAR" reading as 99% below the median,
because a sear matched to the Luger P.08 model sits in a group of complete
Lugers. Below it: a ZFK-55 bolt, a P.08 magazine, a bare 1911A1 frame, a
non-firing miniature Colt.

None of those is mispriced. They are *mismatched*, and the only thing that
separates a mismatch from a bargain is the size of the gap -- which is why
there is a ceiling on the discount as well as a floor, and why raising it is
the one change that turns this page back into a parts bin.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    FirearmModel,
    HotDealNotice,
    HotDealPreference,
    Item,
    Manufacturer,
    Site,
    User,
    UserRole,
    utcnow,
)
from app.security import hash_password
from app.services import hotdeals, pricing


@pytest.fixture
def shop(clean_db):
    """Two shops and one model, which is the smallest world a deal can exist in.

    Two, because a deal has to be cheap against *somebody else's* shelf --
    ``min_vendors`` defaults to 2 and one dealer's spread is not a market.
    """
    model = FirearmModel(name="K31")
    a = Site(slug="a", name="Shop A", base_url="https://a.test/")
    b = Site(slug="b", name="Shop B", base_url="https://b.test/")
    clean_db.add_all([model, a, b])
    clean_db.flush()
    return model, a, b


def listing(
    session,
    site,
    model,
    price,
    *,
    title="Schmidt Rubin K31",
    caliber="7.5x55mm Swiss",
    rifle=True,
    pistol=False,
    police=False,
    sold=False,
    active=True,
    maker=None,
    key=None,
):
    item = Item(
        site_id=site.id,
        external_key=key or f"{site.slug}-{title}-{price}-{session.query(Item).count()}",
        url=f"{site.base_url}x",
        title=title,
        caliber=caliber,
        manufacturer=maker,
        firearm_model_id=model.id if model else None,
        current_price=price,
        is_rifle=rifle,
        is_pistol=pistol,
        is_police_surplus=police,
        is_sold=sold,
        is_active=active,
    )
    session.add(item)
    session.flush()
    return item


#: How many dearer peers each cheap listing needs before it can qualify.
#:
#: Not a magic number -- it falls out of the rule. ``cheaper_than`` is
#: ``100 * dearer / total``, and the default threshold is 80, so with ``C``
#: cheap listings and ``D`` dear ones every cheap one needs ``D >= 4C``.
#:
#: Worth stating rather than discovering: a crate of nine identical cheap
#: rifles *dilutes its own discount*, because the crate is part of the group
#: it is being measured against. That is the right answer -- if one shop holds
#: nine of them at $500, $500 is what they cost -- and it is the thing that
#: makes these fixtures look larger than they need to be.
DEAR_PER_CHEAP = 4


def dearer(session, site, model, count, price=1000.0, **kwargs):
    """*count* peers at the going rate, to measure a cheap one against."""
    return [listing(session, site, model, price, **kwargs) for _ in range(count)]


def shelf(session, shop, prices_a, prices_b, **kwargs):
    """A group of peers split across two shops, cheapest first in shop A."""
    model, a, b = shop
    made = [listing(session, a, model, price, **kwargs) for price in prices_a]
    made += [listing(session, b, model, price, **kwargs) for price in prices_b]
    session.commit()
    return made


def bargain_among(session, shop, cheap_prices, *, dear=1000.0, **kwargs):
    """*cheap_prices* in shop A, with just enough dearer peers in shop B.

    "Just enough" is DEAR_PER_CHEAP per cheap listing, so the cheapest of them
    clears the rule rather than sitting one listing short of it.
    """
    model, a, b = shop
    made = [listing(session, a, model, price, **kwargs) for price in cheap_prices]
    dearer(session, b, model, DEAR_PER_CHEAP * len(cheap_prices), dear, **kwargs)
    session.commit()
    return made


class TestTheRule:
    def test_a_listing_well_under_the_others_is_a_deal(self, clean_db, shop):
        made = shelf(clean_db, shop, [500.0], [1000.0, 1000.0, 1050.0, 1100.0])
        hotdeals.refresh(clean_db)

        found = hotdeals.deals(clean_db)
        assert [deal.item_id for deal in found] == [made[0].id]
        assert found[0].median_price == 1000.0
        assert found[0].discount_percent == 50.0

    def test_the_cheapest_of_a_tight_group_is_not(self, clean_db, shop):
        """It undercuts every one of them and saves nobody anything. The floor
        exists for exactly this: cheapest is not the same as cheap."""
        shelf(clean_db, shop, [990.0], [1000.0, 1000.0, 1010.0, 1020.0])
        hotdeals.refresh(clean_db)
        assert hotdeals.deals(clean_db) == []

    def test_and_neither_is_something_far_too_cheap_to_be_the_same_object(self, clean_db, shop):
        """**The one that matters.** A $25 sear in a group of $3,250 Lugers is
        not a bargain on a Luger, and the only signal that says so is the size
        of the gap. Without the ceiling this is what the page opens with."""
        shelf(clean_db, shop, [25.0], [1000.0, 1000.0, 1050.0, 1100.0])
        hotdeals.refresh(clean_db)
        assert hotdeals.deals(clean_db) == []

    def test_one_shops_own_price_spread_is_not_a_market(self, clean_db, shop):
        """Every peer on one shelf is that dealer's pricing -- the finding the
        Market page reports as `concentrated`."""
        model, a, _b = shop
        for price in (500.0, 1000.0, 1000.0, 1100.0):
            listing(clean_db, a, model, price)
        clean_db.commit()
        hotdeals.refresh(clean_db)
        assert hotdeals.deals(clean_db) == []

    def test_too_few_peers_is_not_a_distribution(self, clean_db, shop):
        """Two listings are a pair, not a spectrum. pricing.MIN_PEERS."""
        shelf(clean_db, shop, [500.0], [1000.0])
        hotdeals.refresh(clean_db)
        assert hotdeals.deals(clean_db) == []

    def test_a_sold_listing_is_a_peer_but_never_a_deal(self, clean_db, shop):
        """The buying opportunity is over, and offering one is the wrong side
        of useful -- the judgment watchlist._alert_is_due also makes.

        It still counts as a peer, because the listing page counts it and a
        reader clicking through must not meet a different number under the
        same words.
        """
        model, a, b = shop
        gone = listing(clean_db, a, model, 500.0, sold=True)
        live = listing(clean_db, a, model, 500.0)
        dearer(clean_db, b, model, DEAR_PER_CHEAP * 2)
        clean_db.commit()
        hotdeals.refresh(clean_db)

        found = hotdeals.deals(clean_db)
        assert [deal.item_id for deal in found] == [live.id]
        assert gone.id not in {deal.item_id for deal in found}
        # ...and the sold one is still in the arithmetic behind the row that
        # did qualify: ten listings, not nine.
        assert found[0].peer_count == 10

    def test_a_de_listed_one_is_not_even_a_peer(self, clean_db, shop):
        model, a, b = shop
        listing(clean_db, a, model, 500.0)
        listing(clean_db, a, model, 30.0, active=False)
        dearer(clean_db, b, model, DEAR_PER_CHEAP)
        clean_db.commit()
        hotdeals.refresh(clean_db)
        # Five: the cheap one and its four dearer peers. The de-listed $30 is
        # not among them, and if it were it would drag the median down far
        # enough to disqualify the deal.
        assert hotdeals.deals(clean_db)[0].peer_count == 5

    def test_the_thresholds_are_the_settings_and_not_constants(self, clean_db, shop):
        shelf(clean_db, shop, [25.0], [1000.0, 1000.0, 1050.0, 1100.0])
        row = hotdeals.settings(clean_db)
        row.max_discount_percent = 99
        clean_db.commit()

        hotdeals.refresh(clean_db)
        assert len(hotdeals.deals(clean_db)) == 1


class TestItAgreesWithTheListingPage:
    def test_placed_exactly_as_pricing_position_would(self, clean_db, shop):
        """Two implementations of one rule, which is a thing that drifts.

        ``pricing.position`` asks a query per listing and is what the detail
        page prints; ``_place_everything`` groups the whole catalog in memory
        because nine thousand queries is not a page load. They have to give the
        same answer, and this is what holds them to it.
        """
        shelf(clean_db, shop, [500.0, 700.0], [1000.0, 1000.0, 1050.0, 1100.0])
        placed, _considered = hotdeals._place_everything(clean_db)
        assert placed

        for entry in placed:
            position = pricing.position(clean_db, entry.item)
            assert position is not None
            assert (position.cheaper_than, position.count, position.vendors) == (
                entry.cheaper_than,
                entry.peers,
                entry.vendors,
            )
            assert round(position.median, 4) == round(entry.median, 4)

    def test_a_maker_that_tells_two_guns_apart_splits_the_group(self, clean_db, shop):
        """pricing.maker_distinguishes: a model naming several firms means an
        Inland is not a Winchester. The grouped pass has to honor that or it
        compares two different guns."""
        model, a, b = shop
        model.manufacturers.append(Manufacturer(name="Inland"))
        model.manufacturers.append(Manufacturer(name="Winchester"))
        clean_db.flush()
        for price in (500.0, 1000.0, 1000.0, 1100.0):
            listing(clean_db, a, model, price, maker="Inland")
        for price in (400.0, 420.0, 430.0):
            listing(clean_db, b, model, price, maker="Winchester")
        clean_db.commit()

        placed, _ = hotdeals._place_everything(clean_db)
        by_maker = {}
        for entry in placed:
            by_maker.setdefault(entry.item.manufacturer, set()).add(entry.peers)
        assert by_maker == {"Inland": {4}, "Winchester": {3}}


class TestTheThreeFilters:
    def test_they_are_the_browse_pages_own_buckets(self, clean_db, shop):
        model, a, b = shop
        assert hotdeals.bucket_of(listing(clean_db, a, model, 1.0, rifle=True)) == "rifle"
        assert (
            hotdeals.bucket_of(listing(clean_db, b, model, 1.0, rifle=False, pistol=True))
            == "pistol"
        )

    def test_a_police_trade_in_is_police_surplus_and_not_a_handgun(self, clean_db, shop):
        """It is still is_pistol, because it is one -- only the bucket changes.
        Counting it under both would show one listing twice."""
        model, a, _b = shop
        glock = listing(clean_db, a, model, 1.0, rifle=False, pistol=True, police=True)
        assert glock.is_pistol is True
        assert hotdeals.bucket_of(glock) == "police_surplus"

    def test_something_that_is_neither_is_not_offered_at_all(self, clean_db, shop):
        model, a, _b = shop
        sling = listing(clean_db, a, model, 1.0, rifle=False, pistol=False)
        assert hotdeals.bucket_of(sling) is None

    def test_the_filter_selects_only_its_own(self, clean_db, shop):
        bargain_among(clean_db, shop, [500.0], rifle=False, pistol=True)
        hotdeals.refresh(clean_db)

        assert len(hotdeals.deals(clean_db, "pistol")) == 1
        assert hotdeals.deals(clean_db, "rifle") == []
        assert hotdeals.counts(clean_db) == {"rifle": 0, "pistol": 1, "police_surplus": 0}


class TestIdenticalOffersCollapse:
    def test_a_crate_of_the_same_rifle_is_one_row(self, clean_db, shop):
        """Dealers buy surplus by the crate and list it a rifle at a time. Nine
        identical K31s at $295 are nine cheap rifles and one thing to say."""
        bargain_among(clean_db, shop, [500.0] * 9)
        hotdeals.refresh(clean_db)

        found = hotdeals.deals(clean_db)
        assert len(found) == 1
        assert found[0].duplicate_count == 9

    def test_but_two_prices_are_two_offers(self, clean_db, shop):
        """The price is the thing being reported, so a difference in it is a
        difference that matters."""
        bargain_among(clean_db, shop, [500.0, 550.0])
        hotdeals.refresh(clean_db)

        found = hotdeals.deals(clean_db)
        assert sorted(deal.price for deal in found) == [500.0, 550.0]
        assert {deal.duplicate_count for deal in found} == {1}

    def test_and_so_are_two_shops(self, clean_db, shop):
        model, a, b = shop
        listing(clean_db, a, model, 500.0)
        listing(clean_db, b, model, 500.0)
        dearer(clean_db, b, model, DEAR_PER_CHEAP * 2)
        clean_db.commit()
        hotdeals.refresh(clean_db)
        # Same gun, same price, two shelves. Two offers, and both are news.
        assert len(hotdeals.deals(clean_db)) == 2


class TestTheTableIsACache:
    def test_a_deal_that_stops_being_one_goes(self, clean_db, shop):
        made = shelf(clean_db, shop, [500.0], [1000.0, 1000.0, 1050.0, 1100.0])
        hotdeals.refresh(clean_db)
        assert hotdeals.deals(clean_db)

        made[0].current_price = 995.0
        clean_db.commit()
        hotdeals.refresh(clean_db)
        assert hotdeals.deals(clean_db) == []

    def test_but_first_listed_at_survives_the_rebuild(self, clean_db, shop):
        """ "New since you last looked" has to outlive the recompute that finds
        the same deal again."""
        shelf(clean_db, shop, [500.0], [1000.0, 1000.0, 1050.0, 1100.0])
        hotdeals.refresh(clean_db)
        first = hotdeals.deals(clean_db)[0].first_listed_at

        hotdeals.refresh(clean_db, now=utcnow() + timedelta(hours=8))
        again = hotdeals.deals(clean_db)[0]
        assert again.first_listed_at == first
        assert again.computed_at > first

    def test_the_run_is_recorded_where_the_page_can_read_it(self, clean_db, shop):
        shelf(clean_db, shop, [500.0], [1000.0, 1000.0, 1050.0, 1100.0])
        hotdeals.refresh(clean_db)

        row = hotdeals.settings(clean_db)
        assert row.last_status == hotdeals.Status.OK
        assert row.last_deal_count == 1
        assert row.last_considered == 5
        assert row.last_run_at is not None

    def test_and_so_is_a_failure(self, clean_db):
        hotdeals.record_failure(clean_db, RuntimeError("boom"))
        row = hotdeals.settings(clean_db)
        assert row.last_status == hotdeals.Status.FAILED
        assert "boom" in row.last_error
        # Moved on purpose: a pass that raises every time would otherwise stay
        # permanently due and retry on every scheduler tick.
        assert row.last_run_at is not None


class TestWhenAPassIsDue:
    def test_never_run_is_due_now(self, clean_db):
        assert hotdeals.is_due(clean_db) is True

    def test_and_not_again_until_the_interval_is_up(self, clean_db, shop):
        now = utcnow()
        hotdeals.refresh(clean_db, now=now)
        assert hotdeals.is_due(clean_db, now=now + timedelta(hours=7)) is False
        assert hotdeals.is_due(clean_db, now=now + timedelta(hours=8)) is True

    def test_switched_off_is_never_due(self, clean_db):
        hotdeals.settings(clean_db).enabled = False
        clean_db.commit()
        assert hotdeals.is_due(clean_db) is False

    def test_the_default_cadence_is_eight_hours(self, clean_db):
        assert hotdeals.settings(clean_db).interval_hours == 8


@pytest.fixture
def reader(clean_db):
    user = User(
        username="reader",
        email="reader@example.test",
        password_hash=hash_password("x" * 16),
        role=UserRole.NORMAL,
    )
    clean_db.add(user)
    clean_db.flush()
    return user


class TestWhoIsSubscribed:
    def test_everybody_is_until_they_say_otherwise(self, clean_db, reader):
        """The absence of a row *is* the default. That is what gives every
        existing account the feature without a backfill, and every new one
        without a signup step."""
        assert clean_db.get(HotDealPreference, 1) is None
        assert reader.id in hotdeals.subscribed_user_ids(clean_db)
        assert hotdeals.wants(None, "rifle") is True
        assert hotdeals.wants(None, "police_surplus") is True

    def test_and_all_three_categories(self, clean_db, reader):
        row = hotdeals.preference(clean_db, reader)
        assert (row.enabled, row.include_rifles, row.include_handguns) == (True, True, True)
        assert row.include_police_surplus is True

    def test_opting_out_takes_them_off_the_list(self, clean_db, reader):
        hotdeals.preference(clean_db, reader).enabled = False
        clean_db.commit()
        assert reader.id not in hotdeals.subscribed_user_ids(clean_db)

    def test_a_deactivated_account_is_not_mailed(self, clean_db, reader):
        reader.is_active = False
        clean_db.commit()
        assert reader.id not in hotdeals.subscribed_user_ids(clean_db)

    def test_dropping_one_category_keeps_the_others(self, clean_db, reader):
        row = hotdeals.preference(clean_db, reader)
        row.include_police_surplus = False
        clean_db.commit()
        assert hotdeals.wants(row, "rifle") is True
        assert hotdeals.wants(row, "police_surplus") is False


class TestTheWatermarkIsAPrice:
    """What makes the next email different from the last one.

    Without a memory every pass would mail the same hundred listings. With a
    *timestamp*, a listing that dropped again after we mentioned it would read
    as "already told you about that one". A price gets both right, and it is
    the same reasoning as WatchedItem.alerted_price.
    """

    @pytest.fixture
    def one_deal(self, clean_db, shop):
        made = shelf(clean_db, shop, [500.0], [1000.0, 1000.0, 1050.0, 1100.0])
        hotdeals.refresh(clean_db)
        return made[0]

    def test_a_deal_nobody_was_told_about_is_unsent(self, clean_db, reader, one_deal):
        assert [deal.item_id for deal in hotdeals.unsent_for(clean_db, reader)] == [one_deal.id]

    def test_and_is_not_sent_twice_at_the_same_price(self, clean_db, reader, one_deal):
        hotdeals.mark_sent(clean_db, reader, hotdeals.unsent_for(clean_db, reader))
        clean_db.commit()
        assert hotdeals.unsent_for(clean_db, reader) == []

    def test_but_a_price_change_brings_it_back(self, clean_db, reader, one_deal):
        hotdeals.mark_sent(clean_db, reader, hotdeals.unsent_for(clean_db, reader))
        clean_db.commit()

        one_deal.current_price = 450.0
        clean_db.commit()
        hotdeals.refresh(clean_db)

        assert [deal.item_id for deal in hotdeals.unsent_for(clean_db, reader)] == [one_deal.id]

    def test_including_a_price_that_went_up_and_came_back_down(self, clean_db, reader, one_deal):
        """A timestamp would swallow this one, which is the case the watchlist
        alert was rewritten to get right."""
        hotdeals.mark_sent(clean_db, reader, hotdeals.unsent_for(clean_db, reader))
        clean_db.commit()

        one_deal.current_price = 900.0
        clean_db.commit()
        hotdeals.refresh(clean_db)
        assert hotdeals.deals(clean_db) == []

        one_deal.current_price = 500.0
        clean_db.commit()
        hotdeals.refresh(clean_db)
        # Same price as last time -- and still not news, because that is
        # exactly what the reader was told.
        assert hotdeals.unsent_for(clean_db, reader) == []

        one_deal.current_price = 480.0
        clean_db.commit()
        hotdeals.refresh(clean_db)
        assert len(hotdeals.unsent_for(clean_db, reader)) == 1

    def test_a_category_they_dropped_is_never_offered(self, clean_db, reader, one_deal):
        row = hotdeals.preference(clean_db, reader)
        row.include_rifles = False
        clean_db.commit()
        assert hotdeals.unsent_for(clean_db, reader) == []

    def test_and_nothing_at_all_once_they_opt_out(self, clean_db, reader, one_deal):
        hotdeals.preference(clean_db, reader).enabled = False
        clean_db.commit()
        assert hotdeals.unsent_for(clean_db, reader) == []

    def test_one_email_is_capped(self, clean_db, reader, shop):
        """A pass just switched on finds several hundred at once, and a first
        email listing all of them is a thing that teaches somebody to filter
        the sender. The rest are not lost -- they go out next time."""
        many = hotdeals.MAX_PER_EMAIL + 5
        # Distinct prices, so nothing collapses and there really are `many`
        # separate offers to choose from.
        bargain_among(clean_db, shop, [500.0 + n for n in range(many)])
        hotdeals.refresh(clean_db)

        assert len(hotdeals.deals(clean_db)) == many
        assert len(hotdeals.unsent_for(clean_db, reader)) == hotdeals.MAX_PER_EMAIL

    def test_stale_notices_are_swept_up(self, clean_db, reader, one_deal):
        hotdeals.mark_sent(clean_db, reader, hotdeals.unsent_for(clean_db, reader))
        clean_db.commit()
        assert clean_db.query(HotDealNotice).count() == 1

        one_deal.current_price = 995.0
        clean_db.commit()
        hotdeals.refresh(clean_db)

        assert hotdeals.forget_stale_notices(clean_db) == 1
        assert clean_db.query(HotDealNotice).count() == 0

    def test_but_a_live_ones_notice_is_kept(self, clean_db, reader, one_deal):
        hotdeals.mark_sent(clean_db, reader, hotdeals.unsent_for(clean_db, reader))
        clean_db.commit()
        assert hotdeals.forget_stale_notices(clean_db) == 0
        assert clean_db.query(HotDealNotice).count() == 1


class TestOrdering:
    def test_by_how_far_below_the_median_and_not_by_dollars(self, clean_db, shop):
        """A 30% saving is $200 on a Mosin and $2,000 on a Luger. Ordering by
        the dollars would put every expensive gun above every cheap one
        whatever the bargain was."""
        model, a, b = shop
        cheap = listing(clean_db, a, model, 500.0, key="cheap")
        dearer(clean_db, b, model, DEAR_PER_CHEAP)

        pricey = FirearmModel(name="Luger P.08")
        clean_db.add(pricey)
        clean_db.flush()
        big = listing(clean_db, a, pricey, 3000.0, caliber="9mm", key="big")
        dearer(clean_db, b, pricey, DEAR_PER_CHEAP, 4000.0, caliber="9mm")
        clean_db.commit()
        hotdeals.refresh(clean_db)

        found = hotdeals.deals(clean_db)
        # $500 saved beats $1,000 saved, because 50% beats 25%.
        assert [deal.item_id for deal in found] == [cheap.id, big.id]
        assert found[0].discount_percent > found[1].discount_percent
