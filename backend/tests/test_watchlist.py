"""Following one listing, and what counts as news about it.

The catalog answers "what is on the shelves" and "is this a good deal". It
could not answer "tell me when *that one* moves" — the question somebody has
about the rifle they have decided they want and will not pay this week's price
for. The only way to find out was to come back and look.

What counts as news is defined once in the service and used by both the digest
that mails it and the page that shows it, so the two cannot disagree about
whether something happened.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    EmailPreference,
    Item,
    PriceHistory,
    Site,
    User,
    UserRole,
    WatchedItem,
    as_utc,
    utcnow,
)
from app.security import hash_password
from app.services import watchlist
from app.services.watchlist import News


@pytest.fixture
def watcher(clean_db):
    user = User(
        username="watcher",
        email="watcher@example.test",
        password_hash=hash_password("x" * 16),
        role=UserRole.NORMAL,
    )
    site = Site(slug="s", name="Shop", base_url="https://s.test/")
    clean_db.add_all([user, site])
    clean_db.flush()
    return user, site


def _watched(
    session,
    user,
    site,
    *,
    price=900.0,
    previous=None,
    target=None,
    sold=False,
    active=True,
    moved_hours_ago=None,
    note=None,
):
    item = Item(
        site_id=site.id,
        external_key=f"k{price}{previous}{sold}{active}{moved_hours_ago}",
        url="https://s.test/x",
        title="A rifle",
        current_price=price,
        previous_price=previous,
        is_sold=sold,
        is_active=active,
        is_rifle=True,
    )
    if moved_hours_ago is not None:
        item.price_changed_at = utcnow() - timedelta(hours=moved_hours_ago)
    session.add(item)
    session.flush()
    watch = WatchedItem(user_id=user.id, item_id=item.id, target_price=target, note=note)
    session.add(watch)
    session.commit()
    return watch, item


class TestWhatCountsAsNews:
    def test_a_price_drop_since_the_last_email(self, clean_db, watcher):
        user, site = watcher
        watch, item = _watched(clean_db, user, site, price=700, previous=900, moved_hours_ago=1)
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is News.CHEAPER

    def test_and_a_rise(self, clean_db, watcher):
        user, site = watcher
        watch, item = _watched(clean_db, user, site, price=950, previous=900, moved_hours_ago=1)
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is News.DEARER

    def test_selling_outranks_a_price(self, clean_db, watcher):
        """The end of the story, and the one a watcher most needs: nothing else
        is going to tell them."""
        user, site = watcher
        watch, item = _watched(clean_db, user, site, sold=True, moved_hours_ago=1)
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is News.SOLD

    def test_and_so_does_going_away(self, clean_db, watcher):
        user, site = watcher
        watch, item = _watched(clean_db, user, site, active=False, moved_hours_ago=1)
        item.delisted_at = utcnow() - timedelta(hours=1)
        clean_db.commit()
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is News.GONE

    def test_nothing_happened_is_nothing_to_say(self, clean_db, watcher):
        user, site = watcher
        watch, item = _watched(clean_db, user, site, price=900, previous=900)
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is None

    def test_nor_a_move_from_before_the_watermark(self, clean_db, watcher):
        """Reported once. The digest's own cutoff is the clock, so a listing
        does not come back in every email until it moves again."""
        user, site = watcher
        watch, item = _watched(clean_db, user, site, price=700, previous=900, moved_hours_ago=48)
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is None


class TestATargetIsAPromiseToStayQuiet:
    def test_it_says_nothing_until_the_price_arrives(self, clean_db, watcher):
        """Naming a number means "do not tell me until then". A rifle drifting
        from $900 to $925 is not news to somebody waiting for $700."""
        user, site = watcher
        watch, item = _watched(
            clean_db, user, site, price=925, previous=900, target=700, moved_hours_ago=1
        )
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is None

    def test_and_speaks_up_when_it_does(self, clean_db, watcher):
        user, site = watcher
        watch, item = _watched(
            clean_db, user, site, price=650, previous=900, target=700, moved_hours_ago=1
        )
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is News.TARGET

    def test_exactly_on_the_number_counts(self, clean_db, watcher):
        user, site = watcher
        watch, item = _watched(
            clean_db, user, site, price=700, previous=900, target=700, moved_hours_ago=1
        )
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is News.TARGET

    def test_but_selling_is_still_news_whatever_the_target(self, clean_db, watcher):
        """A target is about the price. Sold is about whether there is still a
        rifle, and somebody waiting for $700 needs to know it has gone."""
        user, site = watcher
        watch, item = _watched(
            clean_db, user, site, price=1200, target=700, sold=True, moved_hours_ago=1
        )
        assert watchlist.news_for(watch, item, utcnow() - timedelta(hours=24)) is News.SOLD


class TestTheOrderTheyAreReported:
    def test_an_ending_before_a_target_before_a_wobble(self, clean_db, watcher):
        user, site = watcher
        _watched(clean_db, user, site, price=950, previous=900, moved_hours_ago=1)
        _watched(clean_db, user, site, price=650, previous=900, target=700, moved_hours_ago=1)
        _watched(clean_db, user, site, sold=True, moved_hours_ago=1)
        clean_db.commit()

        found = watchlist.updates(clean_db, user, utcnow() - timedelta(hours=24))
        assert [u.news for u in found] == [News.SOLD, News.TARGET, News.DEARER]


class TestTheApi:
    def test_starring_is_idempotent(self, client, normal_user, clean_db, watcher):
        """The star is a state, not an event: clicking it twice leaves one
        watch rather than failing."""
        _user, site = watcher
        item = Item(
            site_id=site.id,
            external_key="k",
            url="https://s.test/1",
            title="A rifle",
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.commit()

        for _ in range(2):
            response = client.put(
                f"/api/watchlist/{item.id}", json={}, headers=normal_user["headers"]
            )
            assert response.status_code == 200
        listed = client.get("/api/watchlist", headers=normal_user["headers"]).json()
        assert len(listed) == 1

    def test_a_target_can_be_set_on_something_already_starred(
        self, client, normal_user, clean_db, watcher
    ):
        _user, site = watcher
        item = Item(
            site_id=site.id,
            external_key="k2",
            url="https://s.test/2",
            title="A rifle",
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.commit()

        client.put(f"/api/watchlist/{item.id}", json={}, headers=normal_user["headers"])
        response = client.put(
            f"/api/watchlist/{item.id}",
            json={"target_price": 700, "note": "if it drops"},
            headers=normal_user["headers"],
        )
        assert response.status_code == 200
        assert response.json()["target_price"] == 700
        assert response.json()["note"] == "if it drops"

    def test_unstarring_something_unstarred_is_not_an_error(
        self, client, normal_user, clean_db, watcher
    ):
        """The caller asked for it to be gone and it is gone."""
        _user, site = watcher
        item = Item(
            site_id=site.id,
            external_key="k3",
            url="https://s.test/3",
            title="A rifle",
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.commit()
        response = client.delete(f"/api/watchlist/{item.id}", headers=normal_user["headers"])
        assert response.status_code == 204

    def test_one_account_cannot_see_another_s(self, client, normal_user, clean_db, watcher):
        """A watch is a statement about what somebody wants, which is more
        personal than most of what this catalog holds."""
        other, site = watcher
        item = Item(
            site_id=site.id,
            external_key="k4",
            url="https://s.test/4",
            title="A rifle",
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.flush()
        clean_db.add(WatchedItem(user_id=other.id, item_id=item.id))
        clean_db.commit()

        assert client.get("/api/watchlist", headers=normal_user["headers"]).json() == []

    def test_watching_something_that_is_not_there(self, client, normal_user):
        response = client.put("/api/watchlist/999999", json={}, headers=normal_user["headers"])
        assert response.status_code == 404


class TestTheDigestCarriesIt:
    def test_a_watchlist_is_reason_enough_to_send_one(self, clean_db, watcher, app_config):
        """Somebody following one rifle and no sites at all has asked a
        narrower question, not a smaller one."""
        from app.services import digest

        user, site = watcher
        clean_db.add(EmailPreference(user_id=user.id, enabled=True, frequency_hours=24))
        _watched(clean_db, user, site, price=700, previous=900, moved_hours_ago=1)
        clean_db.commit()
        clean_db.refresh(user)

        built = digest.build_digest(clean_db, user, app_config)
        assert built is not None
        _subject, html, _images, _new, _drops, _cutoff = built
        assert "You are watching" in html
        assert "Price dropped" in html


class TestImmediateAlerts:
    """Reaching a target between digests.

    A rifle that hits $700 an hour after the daily digest sends is news
    twenty-three hours later, and on a shelf where one rifle is one rifle that
    is often too late. So an alert runs on the scan cadence instead — which
    means it has no watermark, and needs one of its own.
    """

    def _alerting(self, session, user, site, *, price, target=700.0, **kwargs):
        watch, item = _watched(session, user, site, price=price, target=target, **kwargs)
        watch.alert_immediately = True
        session.commit()
        return watch, item

    def test_a_target_reached_is_due(self, clean_db, watcher):
        user, site = watcher
        self._alerting(clean_db, user, site, price=650)
        assert list(watchlist.due_alerts(clean_db)) == [user.id]

    def test_a_price_above_it_is_not(self, clean_db, watcher):
        user, site = watcher
        self._alerting(clean_db, user, site, price=900)
        assert watchlist.due_alerts(clean_db) == {}

    def test_nor_a_watch_that_did_not_ask(self, clean_db, watcher):
        """Opt-in. An alert is an interruption, and somebody who has not asked
        for one has not asked to be interrupted."""
        user, site = watcher
        _watched(clean_db, user, site, price=650, target=700)
        assert watchlist.due_alerts(clean_db) == {}

    def test_nor_one_with_no_target_at_all(self, clean_db, watcher):
        user, site = watcher
        watch, _item = _watched(clean_db, user, site, price=650)
        watch.alert_immediately = True
        clean_db.commit()
        assert watchlist.due_alerts(clean_db) == {}

    def test_a_sold_listing_is_not_alerted_about(self, clean_db, watcher):
        """A real event, and the digest carries it — but it is not a buying
        opportunity, and interrupting somebody to say they missed one is the
        wrong side of useful."""
        user, site = watcher
        self._alerting(clean_db, user, site, price=650, sold=True)
        assert watchlist.due_alerts(clean_db) == {}


class TestTheAlertRemembersWhatItSaid:
    """Its watermark is a *price*, not a time.

    An alert fires between digests and so cannot use last_digest_cutoff.
    Without a memory of its own it would mail the same $650 on every scheduler
    tick until somebody bought the rifle.
    """

    def test_it_does_not_repeat_itself(self, clean_db, watcher):
        user, site = watcher
        watch, item = _watched(clean_db, user, site, price=650, target=700)
        watch.alert_immediately = True
        clean_db.commit()
        assert list(watchlist.due_alerts(clean_db)) == [user.id]

        watchlist.mark_alerted(watch, item, utcnow())
        clean_db.commit()
        assert watchlist.due_alerts(clean_db) == {}

    def test_but_a_new_price_is_a_new_thing_to_say(self, clean_db, watcher):
        """A price rather than a timestamp gets the awkward case right: a
        vendor who puts a price back up and drops it again has genuinely done
        something worth a second email."""
        user, site = watcher
        watch, item = _watched(clean_db, user, site, price=650, target=700)
        watch.alert_immediately = True
        watchlist.mark_alerted(watch, item, utcnow())
        clean_db.commit()
        assert watchlist.due_alerts(clean_db) == {}

        item.current_price = 600
        clean_db.commit()
        assert list(watchlist.due_alerts(clean_db)) == [user.id]

    def test_and_clearing_the_target_clears_the_memory(
        self, client, normal_user, clean_db, watcher
    ):
        """Otherwise the next target named would be judged against a price from
        the last one."""
        _user, site = watcher
        item = Item(
            site_id=site.id,
            external_key="alert",
            url="https://s.test/a",
            title="A rifle",
            current_price=650,
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.commit()

        client.put(
            f"/api/watchlist/{item.id}",
            json={"target_price": 700, "alert_immediately": True},
            headers=normal_user["headers"],
        )
        client.put(f"/api/watchlist/{item.id}", json={}, headers=normal_user["headers"])

        row = clean_db.execute(
            __import__("sqlalchemy").select(WatchedItem).where(WatchedItem.item_id == item.id)
        ).scalar_one()
        assert row.target_price is None
        assert row.alerted_price is None
        # And the flag goes with it: "tell me the moment it reaches nothing" is
        # not a request.
        assert row.alert_immediately is False


class TestARecurringSaleIsNotSilenced:
    """What counts as news again, told as the stories it has to get right.

    The watermark used to be "any price other than the one mailed", which
    silenced a recurring sale for good and mailed rises. See
    app.services.renotify.
    """

    def _told(self, session, user, site, *, price=650.0, days_ago=3):
        watch, item = _watched(session, user, site, price=price, target=700)
        watch.alert_immediately = True
        told = utcnow() - timedelta(days=days_ago)
        watchlist.mark_alerted(watch, item, told)
        session.commit()
        return watch, item, told

    def _scan_sees(self, session, item, price, when):
        item.current_price = price
        session.add(PriceHistory(item_id=item.id, price=price, observed_at=when))
        session.commit()

    def test_the_markdown_mailed_twice(self, clean_db, watcher):
        """$650 mailed, back up to $800, then $650 again: the second sale is
        news. This is the case that used to go dark."""
        user, site = watcher
        _watch, item, told = self._told(clean_db, user, site)
        assert watchlist.due_alerts(clean_db) == {}

        self._scan_sees(clean_db, item, 800.0, told + timedelta(days=1))
        assert watchlist.due_alerts(clean_db) == {}  # above the target

        self._scan_sees(clean_db, item, 650.0, told + timedelta(days=2))
        assert list(watchlist.due_alerts(clean_db)) == [user.id]

    def test_a_steady_price_stays_quiet_until_the_expiry(self, clean_db, watcher):
        user, site = watcher
        self._told(clean_db, user, site, days_ago=3)
        assert watchlist.due_alerts(clean_db) == {}

    def test_after_the_expiry_it_is_a_reminder(self, clean_db, watcher):
        user, site = watcher
        self._told(clean_db, user, site, days_ago=31)
        assert list(watchlist.due_alerts(clean_db)) == [user.id]

    def test_a_rise_under_the_target_is_never_mailed(self, clean_db, watcher):
        """$650 mailed, then $690: still under the $700 target, and worse than
        what the reader was told. It used to go out because it differed."""
        user, site = watcher
        _watch, item, told = self._told(clean_db, user, site)
        self._scan_sees(clean_db, item, 690.0, told + timedelta(hours=1))
        assert watchlist.due_alerts(clean_db) == {}

    def test_a_partial_retreat_after_a_rise_is_not_news_either(self, clean_db, watcher):
        """$650 mailed, up to $800, down to $680: lower than the peak, but not
        back to the price we mentioned."""
        user, site = watcher
        _watch, item, told = self._told(clean_db, user, site)
        self._scan_sees(clean_db, item, 800.0, told + timedelta(days=1))
        self._scan_sees(clean_db, item, 680.0, told + timedelta(days=2))
        assert watchlist.due_alerts(clean_db) == {}


class TestTheAlertEmail:
    def test_it_names_the_listing_rather_than_counting_things(self, clean_db, watcher, app_config):
        """ "Milsurp Monitor: 3 new listings" in a notification shade is not
        what somebody who asked to be interrupted at $700 needs to see."""
        from app.services import digest

        user, site = watcher
        watch, _item = _watched(clean_db, user, site, price=650, target=700)
        watch.alert_immediately = True
        clean_db.commit()

        found = watchlist.due_alerts(clean_db)[user.id]
        entry = digest.send_watch_alert(clean_db, user, found, app_config)
        # Email is off in the test configuration, so this records a failure --
        # the subject is built before the send and is what is being checked.
        assert "A rifle" in entry.subject
        assert "650" in entry.subject.replace(",", "")

    def test_it_does_not_move_the_digest_watermark(self, clean_db, watcher, app_config):
        """An alert is not the digest arriving early. Moving the cutoff would
        swallow the week's new listings to deliver one price."""
        from app.services import digest

        user, site = watcher
        preference = EmailPreference(user_id=user.id, enabled=True, frequency_hours=24)
        preference.last_digest_cutoff = utcnow() - timedelta(hours=3)
        clean_db.add(preference)
        watch, _item = _watched(clean_db, user, site, price=650, target=700)
        watch.alert_immediately = True
        clean_db.commit()
        before = preference.last_digest_cutoff

        digest.send_watch_alert(clean_db, user, watchlist.due_alerts(clean_db)[user.id], app_config)
        clean_db.refresh(preference)
        # as_utc on both sides: the column is naive and `before` was read while
        # the object was still aware, so a bare == compares tzinfo rather than
        # the instant, which is not the question.
        assert as_utc(preference.last_digest_cutoff) == as_utc(before)
        assert preference.next_send_at is None
