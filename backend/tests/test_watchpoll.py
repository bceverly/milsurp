"""Re-reading a watched listing ahead of its shop's scan.

The alert can only be as fresh as the price it reads, and a price only changed
when a scan stored it — twenty-five of twenty-eight shops scan daily. This is
what makes the price fresh, and the properties worth pinning are the polite
ones: it reads one page, it honors the cooldown register, and it skips a shop
whose page it cannot read rather than guessing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Item, PriceHistory, Site, WatchedItem, utcnow
from app.scrapers.base import PriceCheck
from app.services import cooldown, watchpoll


@pytest.fixture
def shop(clean_db):
    site = Site(slug="demo", name="Demo", base_url="https://demo.test/")
    clean_db.add(site)
    clean_db.flush()
    return site


def _watched(session, shop, *, price=900.0, url="https://demo.test/x", active=True, sold=False):
    item = Item(
        site_id=shop.id,
        external_key=url,
        url=url,
        title="A rifle",
        current_price=price,
        currency="USD",
        is_rifle=True,
        is_active=active,
        is_sold=sold,
    )
    session.add(item)
    session.flush()
    session.add(WatchedItem(user_id=_a_user(session).id, item_id=item.id))
    session.commit()
    return item


def _a_user(session):
    from app.models import User, UserRole
    from app.security import hash_password

    user = session.query(User).filter_by(username="poller").one_or_none()
    if user is None:
        user = User(
            username="poller",
            email="poller@example.test",
            password_hash=hash_password("x" * 16),
            role=UserRole.NORMAL,
        )
        session.add(user)
        session.flush()
    return user


@pytest.fixture
def answering(monkeypatch):
    """A scraper that reports whatever the test says, without a network."""

    def answer(found):
        class Fake:
            def check_price(self, _ctx, _url):
                if isinstance(found, Exception):
                    raise found
                return found

        monkeypatch.setattr(watchpoll, "get_scraper", lambda _slug: Fake())

    return answer


class TestWhatAPassDoes:
    def test_a_new_price_is_stored_the_way_a_scan_stores_one(
        self, clean_db, shop, answering, app_config
    ):
        """Indistinguishable from a scan's, deliberately: the watchlist, the
        spectrum and the digest all read those columns, and a price arriving by
        a second route must not look different."""
        item = _watched(clean_db, shop, price=900)
        answering(PriceCheck(price=650))

        result = watchpoll.run(clean_db, app_config)
        clean_db.refresh(item)
        assert result.changed == 1
        assert item.current_price == 650
        assert item.previous_price == 900
        assert item.price_changed_at is not None
        assert item.lowest_price == 650

    def test_and_leaves_a_history_row_with_no_scan_run(self, clean_db, shop, answering, app_config):
        """It did not happen during a scan. Inventing a run to point at would
        put a lie in the scan history to keep a foreign key company."""
        item = _watched(clean_db, shop, price=900)
        answering(PriceCheck(price=650))
        watchpoll.run(clean_db, app_config)

        row = clean_db.query(PriceHistory).filter_by(item_id=item.id).one()
        assert row.price == 650
        assert row.scan_run_id is None

    def test_an_unchanged_price_changes_nothing(self, clean_db, shop, answering, app_config):
        item = _watched(clean_db, shop, price=900)
        answering(PriceCheck(price=900))

        result = watchpoll.run(clean_db, app_config)
        clean_db.refresh(item)
        assert result.changed == 0
        assert item.previous_price is None
        assert clean_db.query(PriceHistory).count() == 0

    def test_a_sold_out_listing_is_marked_sold(self, clean_db, shop, answering, app_config):
        """The thing a watcher most needs, and the poll is what finds it first."""
        item = _watched(clean_db, shop, price=900)
        answering(PriceCheck(price=900, sold_out=True))

        result = watchpoll.run(clean_db, app_config)
        clean_db.refresh(item)
        assert result.sold == 1
        assert item.is_sold is True


class TestWhatItRefusesToDo:
    def test_a_shop_that_publishes_no_price_is_skipped_not_guessed_at(
        self, clean_db, shop, answering, app_config
    ):
        """Fourteen of twenty-eight publish nothing this can read. Guessing one
        out of theme markup would eventually mail somebody about a rifle that
        is not on offer, which is worse than telling them a few hours late."""
        item = _watched(clean_db, shop, price=900)
        answering(None)

        result = watchpoll.run(clean_db, app_config)
        clean_db.refresh(item)
        assert result.skipped == 1
        assert item.current_price == 900
        # Still marked checked, or an unreadable page is asked for first on
        # every pass forever.
        assert item.last_checked_at is not None

    def test_a_host_the_register_is_resting_is_not_asked(
        self, clean_db, shop, answering, app_config
    ):
        """This is the most frequent thing the application does and would be
        the first to earn a block if it ignored the register."""
        _watched(clean_db, shop, price=900)
        answering(PriceCheck(price=1))
        cooldown.refused("https://demo.test/x", "429")
        try:
            result = watchpoll.run(clean_db, app_config)
            assert result.skipped == 1
            assert result.checked == 0
        finally:
            cooldown.clear()

    def test_a_de_listed_listing_is_not_re_read(self, clean_db, shop, answering, app_config):
        """Its story has ended and the watcher has been told. Spending requests
        on rifles nobody can buy is what a request budget is for."""
        _watched(clean_db, shop, price=900, active=False)
        answering(PriceCheck(price=650))
        assert watchpoll.run(clean_db, app_config).checked == 0

    def test_nor_a_sold_one(self, clean_db, shop, answering, app_config):
        _watched(clean_db, shop, price=900, sold=True)
        answering(PriceCheck(price=650))
        assert watchpoll.run(clean_db, app_config).checked == 0

    def test_a_refusal_does_not_end_the_pass(self, clean_db, shop, answering, app_config):
        from app.scrapers.base import ScrapeError

        _watched(clean_db, shop, price=900)
        answering(ScrapeError("nope", status=403))
        result = watchpoll.run(clean_db, app_config)
        assert result.failed == 1


class TestItReadsEachListingOnce:
    def test_two_watchers_of_one_rifle_is_one_request(self, clean_db, shop, answering, app_config):
        from app.models import User, UserRole
        from app.security import hash_password

        item = _watched(clean_db, shop, price=900)
        other = User(
            username="second",
            email="second@example.test",
            password_hash=hash_password("y" * 16),
            role=UserRole.NORMAL,
        )
        clean_db.add(other)
        clean_db.flush()
        clean_db.add(WatchedItem(user_id=other.id, item_id=item.id))
        clean_db.commit()

        answering(PriceCheck(price=650))
        assert watchpoll.run(clean_db, app_config).checked == 1

    def test_the_least_recently_checked_goes_first(self, clean_db, shop, answering, app_config):
        """So a watchlist longer than one pass is read round-robin rather than
        the same head of it on every tick."""
        old = _watched(clean_db, shop, url="https://demo.test/old")
        fresh = _watched(clean_db, shop, url="https://demo.test/fresh")
        old.last_checked_at = utcnow() - timedelta(days=2)
        fresh.last_checked_at = utcnow()
        clean_db.commit()

        order = [item.url for item in watchpoll.watched_items(clean_db)]
        assert order == [old.url, fresh.url]

    def test_a_never_checked_listing_sorts_first_of_all(
        self, clean_db, shop, answering, app_config
    ):
        checked = _watched(clean_db, shop, url="https://demo.test/checked")
        checked.last_checked_at = utcnow() - timedelta(days=30)
        never = _watched(clean_db, shop, url="https://demo.test/never")
        clean_db.commit()

        assert watchpoll.watched_items(clean_db)[0].url == never.url
