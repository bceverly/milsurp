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

from app.models import EmailPreference, Item, Site, User, UserRole, WatchedItem, utcnow
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
