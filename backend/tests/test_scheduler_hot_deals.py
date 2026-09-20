"""The scheduler's hot-deals tick: run the pass, then tell whoever asked.

The two go out in one breath deliberately. What makes a hot-deal email due is
the *arrival* of a hot deal, and somebody who asked to hear about bargains is
not asking to hear about them six hours after they were found — so unlike the
digest, this has no clock of its own.

Driven directly rather than by starting the thread. The loop is a `while` over
a timer and a `stop` event; what is worth testing is what one tick does, and a
test that slept waiting for one would be slow and flaky in exchange for
covering `Event.wait`.
"""

from __future__ import annotations

import pytest

from app.models import (
    EmailStatus,
    FirearmModel,
    HotDealNotice,
    Item,
    Site,
    User,
    UserRole,
    utcnow,
)
from app.scheduler import Scheduler
from app.security import hash_password
from app.services import digest, hotdeals


@pytest.fixture
def world(clean_db, app_config, monkeypatch):
    """A reader, a bargain, and a mailer that records instead of sending."""
    reader = User(
        username="reader",
        email="reader@example.test",
        password_hash=hash_password("x" * 16),
        role=UserRole.NORMAL,
    )
    model = FirearmModel(name="K31")
    a = Site(slug="a", name="Shop A", base_url="https://a.test/")
    b = Site(slug="b", name="Shop B", base_url="https://b.test/")
    clean_db.add_all([reader, model, a, b])
    clean_db.flush()

    def add(site, price, index):
        clean_db.add(
            Item(
                site_id=site.id,
                external_key=f"{site.slug}-{index}",
                url=f"{site.base_url}{index}",
                title=f"Schmidt Rubin K31 {index}",
                caliber="7.5x55mm Swiss",
                firearm_model_id=model.id,
                current_price=price,
                is_rifle=True,
            )
        )

    add(a, 500.0, 0)
    for index in range(4):
        add(b, 1000.0, index + 1)
    clean_db.commit()

    sent = []
    monkeypatch.setattr(
        digest.mailer,
        "send_html",
        lambda to, subject, body, **kwargs: sent.append((to, subject)),
    )
    return clean_db, reader, sent


@pytest.fixture
def scheduler(app_config):
    return Scheduler(app_config)


class TestOneTick:
    def test_it_finds_the_deals_and_mails_them(self, world, scheduler):
        session, reader, sent = world

        scheduler._dispatch_hot_deals()

        assert len(hotdeals.deals(session)) == 1
        assert len(sent) == 1
        assert sent[0][0] == reader.email

    def test_and_records_what_was_said_so_it_is_not_said_twice(self, world, scheduler):
        session, _reader, sent = world

        scheduler._dispatch_hot_deals()
        assert session.query(HotDealNotice).count() == 1

        # A second tick inside the interval does nothing at all: not due.
        scheduler._dispatch_hot_deals()
        assert len(sent) == 1

    def test_a_pass_that_is_not_due_is_skipped_entirely(self, world, scheduler):
        session, _reader, sent = world
        hotdeals.refresh(session)
        row = hotdeals.settings(session)
        row.last_run_at = utcnow()
        session.commit()

        scheduler._dispatch_hot_deals()
        assert sent == []

    def test_and_so_is_one_that_is_switched_off(self, world, scheduler):
        session, _reader, sent = world
        hotdeals.settings(session).enabled = False
        session.commit()

        scheduler._dispatch_hot_deals()
        assert hotdeals.deals(session) == []
        assert sent == []

    def test_somebody_who_opted_out_is_not_mailed(self, world, scheduler):
        session, reader, sent = world
        hotdeals.preference(session, reader).enabled = False
        session.commit()

        scheduler._dispatch_hot_deals()
        # The pass still ran -- opting out is about the email, not the page.
        assert len(hotdeals.deals(session)) == 1
        assert sent == []


class TestNothingHereStopsTheScans:
    def test_a_pass_that_raises_is_recorded_rather_than_propagated(
        self, world, scheduler, monkeypatch
    ):
        """A scheduler tick that raises would stop every scan on the machine."""
        session, _reader, sent = world

        def boom(*_args, **_kwargs):
            raise RuntimeError("the catalog is on fire")

        monkeypatch.setattr(hotdeals, "refresh", boom)
        scheduler._dispatch_hot_deals()

        row = hotdeals.settings(session)
        assert row.last_status == hotdeals.Status.FAILED
        assert "on fire" in row.last_error
        assert sent == []

    def test_one_readers_failed_email_does_not_cost_the_others_theirs(
        self, world, scheduler, monkeypatch
    ):
        session, reader, sent = world
        second = User(
            username="other",
            email="other@example.test",
            password_hash=hash_password("x" * 16),
            role=UserRole.NORMAL,
        )
        session.add(second)
        session.commit()

        def selective(to, subject, body, **_kwargs):
            if to == reader.email:
                raise digest.mailer.MailError("smtp said no")
            sent.append((to, subject))

        monkeypatch.setattr(digest.mailer, "send_html", selective)
        scheduler._dispatch_hot_deals()

        assert [to for to, _subject in sent] == [second.email]

    def test_and_a_failed_send_is_not_recorded_as_told(self, world, scheduler, monkeypatch):
        """So it is retried next pass rather than silently dropped."""
        session, reader, _sent = world

        def boom(*_args, **_kwargs):
            raise digest.mailer.MailError("smtp said no")

        monkeypatch.setattr(digest.mailer, "send_html", boom)
        scheduler._dispatch_hot_deals()

        assert session.query(HotDealNotice).count() == 0
        assert len(hotdeals.unsent_for(session, reader)) == 1


class TestTheEmailLog:
    def test_a_send_shows_up_where_the_admin_looks(self, world, scheduler):
        from app.models import EmailLog

        session, reader, _sent = world
        scheduler._dispatch_hot_deals()

        entry = session.query(EmailLog).filter_by(user_id=reader.id).one()
        assert entry.status is EmailStatus.SENT
        assert "below the usual price" in entry.subject
