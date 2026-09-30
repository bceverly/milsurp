"""Want lists: a saved search that says so the moment one appears.

Three promises, each tested here. Something that *comes to match* is news --
new, reduced into range, or back in stock. The backlog is not: switching the
alert on must not mail the forty listings the search page already shows. And a
listing is news once, however many times it moves afterwards.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    EmailStatus,
    Item,
    SavedSearch,
    SavedSearchAlert,
    Site,
    User,
    UserRole,
    utcnow,
)
from app.scheduler import Scheduler
from app.security import hash_password
from app.services import digest, wantlist


@pytest.fixture
def reader(clean_db):
    user = User(
        username="wanter",
        email="wanter@example.test",
        password_hash=hash_password("x" * 16),
        role=UserRole.NORMAL,
    )
    site = Site(slug="w", name="Shop", base_url="https://w.test/")
    clean_db.add_all([user, site])
    clean_db.flush()
    return user, site


def _item(session, site, key, *, price, title="Inland M1 Carbine", **kwargs):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"https://w.test/{key}",
        title=title,
        current_price=price,
        is_rifle=True,
        **kwargs,
    )
    session.add(item)
    session.flush()
    return item


def _want(session, user, *, query="search=carbine&max_price=1400", since_hours=24):
    row = SavedSearch(user_id=user.id, name="Carbine under 1400", query=query, sort="newest")
    wantlist.switch(row, True, now=utcnow() - timedelta(hours=since_hours))
    session.add(row)
    session.commit()
    return row


def _due_ids(session, user):
    wants = wantlist.due(session).get(user.id, [])
    return sorted(item_id for want in wants for item_id in want.ids)


class TestWhatIsNews:
    def test_a_new_listing_in_range(self, clean_db, reader):
        user, site = reader
        _want(clean_db, user)
        item = _item(clean_db, site, "new", price=1200)
        clean_db.commit()
        assert _due_ids(clean_db, user) == [item.id]

    def test_but_not_one_over_the_ceiling(self, clean_db, reader):
        user, site = reader
        _want(clean_db, user)
        _item(clean_db, site, "dear", price=1600)
        clean_db.commit()
        assert _due_ids(clean_db, user) == []

    def test_a_reduction_that_brings_one_into_range(self, clean_db, reader):
        user, site = reader
        old = _item(
            clean_db,
            site,
            "old",
            price=1350,
            previous_price=1450,
            first_seen_at=utcnow() - timedelta(days=30),
            price_changed_at=utcnow() - timedelta(hours=1),
        )
        _want(clean_db, user)
        assert _due_ids(clean_db, user) == [old.id]

    def test_a_rise_that_stays_in_range_is_not(self, clean_db, reader):
        user, site = reader
        _item(
            clean_db,
            site,
            "rose",
            price=1300,
            previous_price=1200,
            first_seen_at=utcnow() - timedelta(days=30),
            price_changed_at=utcnow() - timedelta(hours=1),
        )
        _want(clean_db, user)
        assert _due_ids(clean_db, user) == []

    def test_back_in_stock(self, clean_db, reader):
        user, site = reader
        back = _item(
            clean_db,
            site,
            "back",
            price=1200,
            first_seen_at=utcnow() - timedelta(days=30),
            restocked_at=utcnow() - timedelta(hours=2),
        )
        _want(clean_db, user)
        assert _due_ids(clean_db, user) == [back.id]

    def test_only_what_is_for_sale(self, clean_db, reader):
        """Even when the search itself asks for everything."""
        user, site = reader
        _want(clean_db, user, query="availability=all&search=carbine&max_price=1400")
        _item(clean_db, site, "gone", price=1200, is_sold=True)
        clean_db.commit()
        assert _due_ids(clean_db, user) == []


class TestTheBacklogIsNotNews:
    def test_what_already_matched_is_not_mailed(self, clean_db, reader):
        user, site = reader
        _item(clean_db, site, "shelf", price=1200, first_seen_at=utcnow() - timedelta(days=3))
        _want(clean_db, user, since_hours=1)
        assert _due_ids(clean_db, user) == []

    def test_switching_on_stamps_now_and_again_later(self, clean_db, reader):
        user, _site = reader
        row = SavedSearch(user_id=user.id, name="x", query="", sort="newest")
        wantlist.switch(row, True)
        first = row.alert_since
        wantlist.switch(row, False)
        wantlist.switch(row, True, now=first + timedelta(days=1))
        assert row.alert_since == first + timedelta(days=1)

    def test_a_search_not_switched_on_says_nothing(self, clean_db, reader):
        user, site = reader
        row = _want(clean_db, user)
        wantlist.switch(row, False)
        _item(clean_db, site, "new", price=1200)
        clean_db.commit()
        assert wantlist.due(clean_db) == {}


class TestOncePerListing:
    def test_marked_is_not_said_again(self, clean_db, reader):
        user, site = reader
        _want(clean_db, user)
        item = _item(clean_db, site, "new", price=1200)
        clean_db.commit()
        wantlist.mark(clean_db, wantlist.due(clean_db)[user.id])
        clean_db.commit()
        assert _due_ids(clean_db, user) == []

        # Reduced again, still in range: the same news.
        item.previous_price, item.current_price = 1200, 1100
        item.price_changed_at = utcnow()
        clean_db.commit()
        assert _due_ids(clean_db, user) == []

    def test_everything_found_is_marked_not_only_what_was_shown(self, clean_db, reader):
        user, site = reader
        _want(clean_db, user)
        for index in range(wantlist.MAX_PER_SEARCH + 3):
            _item(clean_db, site, f"n{index}", price=1000 + index)
        clean_db.commit()
        wants = wantlist.due(clean_db)[user.id]
        assert len(wants[0].items) == wantlist.MAX_PER_SEARCH
        assert wants[0].total == wantlist.MAX_PER_SEARCH + 3

        wantlist.mark(clean_db, wants)
        clean_db.commit()
        assert clean_db.query(SavedSearchAlert).count() == wantlist.MAX_PER_SEARCH + 3

    def test_a_listing_that_arrives_after_the_message_is_still_news(self, clean_db, reader):
        """The ids marked are the ones the message was built from."""
        user, site = reader
        _want(clean_db, user)
        _item(clean_db, site, "first", price=1200)
        clean_db.commit()
        wants = wantlist.due(clean_db)[user.id]
        late = _item(clean_db, site, "late", price=1250)
        clean_db.commit()
        wantlist.mark(clean_db, wants)
        clean_db.commit()
        assert _due_ids(clean_db, user) == [late.id]


class TestTheMessage:
    def test_one_listing_is_named(self, clean_db, reader, app_config):
        user, site = reader
        _want(clean_db, user)
        _item(clean_db, site, "new", price=1200)
        clean_db.commit()
        entry = digest.send_want_alert(clean_db, user, wantlist.due(clean_db)[user.id], app_config)
        assert "Inland M1 Carbine" in entry.subject
        assert "Carbine under 1400" in entry.subject

    def test_the_scheduler_sends_and_marks(self, clean_db, reader, app_config, monkeypatch):
        user, site = reader
        _want(clean_db, user)
        _item(clean_db, site, "new", price=1200)
        clean_db.commit()
        sent = []
        monkeypatch.setattr(
            digest.mailer, "send_html", lambda to, subject, body, **kw: sent.append(subject)
        )
        Scheduler(app_config)._dispatch_want_alerts()
        assert len(sent) == 1
        Scheduler(app_config)._dispatch_want_alerts()
        assert len(sent) == 1

    def test_a_failed_send_is_tried_again(self, clean_db, reader, app_config, monkeypatch):
        user, site = reader
        _want(clean_db, user)
        _item(clean_db, site, "new", price=1200)
        clean_db.commit()

        def refuse(*_args, **_kwargs):
            raise digest.mailer.MailError("no")

        monkeypatch.setattr(digest.mailer, "send_html", refuse)
        Scheduler(app_config)._dispatch_want_alerts()
        assert clean_db.query(SavedSearchAlert).count() == 0
        entry = digest.send_want_alert(clean_db, user, wantlist.due(clean_db)[user.id], app_config)
        assert entry.status is EmailStatus.FAILED


class TestTheApi:
    def test_switching_it_on_and_reading_the_target(self, client, normal_user):
        headers = normal_user["headers"]
        created = client.post(
            "/api/saved-searches",
            json={"name": "K31", "query": "search=k31&max_price=450", "alert_instantly": True},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["alert_instantly"] is True
        assert body["alert_since"]
        assert body["target_price"] == 450

        off = client.patch(
            f"/api/saved-searches/{body['id']}", json={"alert_instantly": False}, headers=headers
        )
        assert off.json()["alert_instantly"] is False
