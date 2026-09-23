"""The hot-deals email, and the memory that keeps it from repeating itself.

The email is straightforward. What is not is *what goes in it*: a pass runs
every few hours and finds largely the same hundred listings each time, so
without a memory every reader would get the same message four times a day
until they filtered the sender.

The memory is a **price**, not a timestamp, and the difference is the whole
reason these tests exist. A timestamp answers "have I mentioned this listing",
which is the wrong question — a rifle that dropped again after we mentioned it
is news, and a timestamp says it is not. A price answers "have I mentioned this
*number*", which is the right one. It is the same reasoning, and the same
shape, as ``WatchedItem.alerted_price``.
"""

from __future__ import annotations

import pytest

from app.models import (
    EmailStatus,
    FirearmModel,
    Item,
    Site,
    User,
    UserRole,
)
from app.security import hash_password
from app.services import digest, hotdeals, mailer


@pytest.fixture
def world(clean_db, app_config):
    """One reader, one bargain, and enough peers across two shops to make it one."""
    reader = User(
        username="reader",
        email="reader@example.test",
        full_name="A Reader",
        password_hash=hash_password("x" * 16),
        role=UserRole.NORMAL,
    )
    model = FirearmModel(name="Walther P38")
    a = Site(slug="a", name="Shop A", base_url="https://a.test/")
    b = Site(slug="b", name="Shop B", base_url="https://b.test/")
    clean_db.add_all([reader, model, a, b])
    clean_db.flush()

    def add(site, price, index):
        item = Item(
            site_id=site.id,
            external_key=f"{site.slug}-{index}",
            url=f"{site.base_url}{index}",
            title=f"Walther P38 Pistol, Original German WWII Model {index}",
            caliber="9mm",
            firearm_model_id=model.id,
            current_price=price,
            is_rifle=False,
            is_pistol=True,
        )
        clean_db.add(item)
        return item

    bargain = add(a, 725.0, 0)
    for index in range(4):
        add(b, 1995.0, index + 1)
    clean_db.commit()
    hotdeals.refresh(clean_db)
    return clean_db, reader, bargain


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have gone out instead of sending it."""
    captured = []
    monkeypatch.setattr(
        digest.mailer,
        "send_html",
        lambda to, subject, body, **kwargs: captured.append((to, subject, body)),
    )
    return captured


class TestWhatTheEmailSays:
    def test_it_leads_with_the_saving(self, world, sent, app_config):
        """Nobody reads this to browse. They read it to find out whether
        anything is worth clicking."""
        session, reader, _bargain = world
        found = hotdeals.unsent_for(session, reader)

        digest.send_hot_deals(session, reader, found, app_config)

        _to, subject, body = sent[0]
        # 725 against a 1,995 median, which is 63.7% and reads as 64.
        assert "64% below the usual price" in body
        assert "below the usual price" in subject

    def test_and_names_the_evidence_behind_it(self, world, sent, app_config):
        """A discount with nothing behind it is a marketing claim."""
        session, reader, _bargain = world
        digest.send_hot_deals(session, reader, hotdeals.unsent_for(session, reader), app_config)

        _to, _subject, body = sent[0]
        assert "5 listed across" in body
        assert "2 shops" in body

    def test_it_groups_by_category_and_not_by_vendor(self, world, sent, app_config):
        """A digest groups by site because a digest is about sites. This is
        about the categories the reader chose."""
        session, reader, _bargain = world
        digest.send_hot_deals(session, reader, hotdeals.unsent_for(session, reader), app_config)

        _to, _subject, body = sent[0]
        assert "Handguns" in body
        assert "Shop A" in body

    def test_one_listing_is_named_in_the_subject(self, world, sent, app_config):
        session, reader, _bargain = world
        digest.send_hot_deals(session, reader, hotdeals.unsent_for(session, reader), app_config)
        assert "Walther P38" in sent[0][1]

    def test_and_several_are_counted(self, world, sent, app_config):
        session, reader, _bargain = world
        found = hotdeals.unsent_for(session, reader)
        digest.send_hot_deals(session, reader, found * 3, app_config)
        assert "3 listings well below the usual price" in sent[0][1]

    def test_it_points_at_the_page_rather_than_the_home_screen(self, world, sent, app_config):
        session, reader, _bargain = world
        digest.send_hot_deals(session, reader, hotdeals.unsent_for(session, reader), app_config)
        assert "/hot-deals" in sent[0][2]

    def test_a_crate_says_how_many_it_stands_for(self, world, sent, app_config):
        session, reader, _bargain = world
        found = hotdeals.unsent_for(session, reader)
        found[0].duplicate_count = 9
        digest.send_hot_deals(session, reader, found, app_config)
        assert "8 more like it at this shop" in sent[0][2]


class TestSending:
    def test_a_sent_message_is_logged_with_its_body(self, world, sent, app_config):
        session, reader, _bargain = world
        entry = digest.send_hot_deals(
            session, reader, hotdeals.unsent_for(session, reader), app_config
        )

        assert entry.status is EmailStatus.SENT
        assert entry.user_id == reader.id
        assert entry.body_html and entry.body_text

    def test_a_failure_is_recorded_rather_than_raised(self, world, app_config, monkeypatch):
        """A canary that dies on shop three takes the rest with it; an email
        that raises here would take the other readers' mail with it."""
        session, reader, _bargain = world

        def boom(*_args, **_kwargs):
            raise mailer.MailError("smtp is down")

        monkeypatch.setattr(digest.mailer, "send_html", boom)
        entry = digest.send_hot_deals(
            session, reader, hotdeals.unsent_for(session, reader), app_config
        )

        assert entry.status is EmailStatus.FAILED
        assert "smtp is down" in entry.error_message

    def test_and_nothing_is_marked_as_told(self, world, app_config, monkeypatch):
        """Marking is the caller's job precisely so a failed send is retried
        next pass rather than recorded as delivered."""
        session, reader, _bargain = world

        def boom(*_args, **_kwargs):
            raise mailer.MailError("smtp is down")

        monkeypatch.setattr(digest.mailer, "send_html", boom)
        digest.send_hot_deals(session, reader, hotdeals.unsent_for(session, reader), app_config)

        assert len(hotdeals.unsent_for(session, reader)) == 1

    def test_it_does_not_touch_the_digest_watermark(self, world, sent, app_config):
        """An alert is not the digest arriving early. Moving the watermark
        would silently swallow the week's new listings."""
        session, reader, _bargain = world
        digest.send_hot_deals(session, reader, hotdeals.unsent_for(session, reader), app_config)
        assert reader.email_preference is None


class TestTheSchedulerLoop:
    """The pass and the mail, as the scheduler drives them.

    They go out in the same breath deliberately: what makes a hot-deal email
    due is the arrival of a hot deal, and somebody who asked to hear about
    bargains is not asking to hear about them six hours later.
    """

    def test_a_reader_hears_once_and_then_not_again(self, world, sent, app_config):
        session, reader, _bargain = world

        found = hotdeals.unsent_for(session, reader)
        assert len(found) == 1
        result = digest.send_hot_deals(session, reader, found, app_config)
        assert result.status is EmailStatus.SENT
        hotdeals.mark_sent(session, reader, found)
        session.commit()

        # Second pass, nothing moved.
        hotdeals.refresh(session)
        assert hotdeals.unsent_for(session, reader) == []

    def test_but_hears_again_when_the_price_moves(self, world, sent, app_config):
        session, reader, bargain = world
        hotdeals.mark_sent(session, reader, hotdeals.unsent_for(session, reader))
        session.commit()

        # 700, not 650: 650 against a 1,995 median is 67% off, which is past
        # the ceiling and stops being a deal at all. That is the rule working,
        # and it makes a careless number here look like a bug in the alert.
        bargain.current_price = 700.0
        session.commit()
        hotdeals.refresh(session)

        found = hotdeals.unsent_for(session, reader)
        assert len(found) == 1
        digest.send_hot_deals(session, reader, found, app_config)
        assert "$700" in sent[-1][2]


class TestNarrowedToSavedSearches:
    """A reader can ask for only the deals their saved searches would find.

    The saved search is run by the search module itself, not re-read here, so
    "matches your search" means what clicking that search shows."""

    def _narrow(self, session, reader, *queries: str) -> None:
        from app.models import HotDealPreference, SavedSearch

        for index, query in enumerate(queries):
            session.add(SavedSearch(user_id=reader.id, name=f"search {index}", query=query))
        session.add(HotDealPreference(user_id=reader.id, match_saved_searches=True))
        session.commit()

    def test_off_by_default_nothing_changes(self, world):
        session, reader, bargain = world
        assert [d.item_id for d in hotdeals.unsent_for(session, reader)] == [bargain.id]

    def test_a_deal_a_search_matches_is_sent(self, world):
        session, reader, bargain = world
        self._narrow(session, reader, "search=Walther")
        assert [d.item_id for d in hotdeals.unsent_for(session, reader)] == [bargain.id]

    def test_a_deal_no_search_matches_is_not(self, world):
        session, reader, _bargain = world
        self._narrow(session, reader, "search=Mosin")
        assert hotdeals.unsent_for(session, reader) == []

    def test_any_one_search_is_enough(self, world):
        session, reader, bargain = world
        self._narrow(session, reader, "search=Mosin", "kind=pistol")
        assert [d.item_id for d in hotdeals.unsent_for(session, reader)] == [bargain.id]

    def test_the_search_s_own_filters_apply_not_just_its_words(self, world):
        """kind=rifle is the browse page's Type filter, and this is a pistol."""
        session, reader, _bargain = world
        self._narrow(session, reader, "kind=rifle")
        assert hotdeals.unsent_for(session, reader) == []

    def test_no_saved_searches_means_nothing(self, world):
        """The reader asked for only their searches and has none."""
        session, reader, _bargain = world
        self._narrow(session, reader)
        assert hotdeals.unsent_for(session, reader) == []

    def test_a_search_that_no_longer_parses_is_skipped_not_fatal(self, world):
        session, reader, bargain = world
        self._narrow(session, reader, "sort=not-a-sort", "search=Walther")
        assert [d.item_id for d in hotdeals.unsent_for(session, reader)] == [bargain.id]

    def test_the_categories_still_apply_on_top(self, world):
        from sqlalchemy import select

        from app.models import HotDealPreference

        session, reader, _bargain = world
        self._narrow(session, reader, "search=Walther")
        row = session.execute(
            select(HotDealPreference).where(HotDealPreference.user_id == reader.id)
        ).scalar_one()
        row.include_handguns = False
        session.commit()
        assert hotdeals.unsent_for(session, reader) == []
