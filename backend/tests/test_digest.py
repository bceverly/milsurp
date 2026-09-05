"""Email digest assembly: what goes in, what is capped, and what is skipped."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    EmailPreference,
    EmailPreferenceSite,
    EmailStatus,
    Item,
    Site,
    User,
    utcnow,
)
from app.services import digest, mailer


@pytest.fixture
def user_with_prefs(seeded):
    user = seeded.query(User).filter_by(username="admin").one()
    preference = seeded.query(EmailPreference).filter_by(user_id=user.id).one_or_none()
    if preference is None:
        preference = EmailPreference(user_id=user.id)
        seeded.add(preference)
        seeded.commit()
    preference.enabled = True
    preference.frequency_hours = 24
    preference.include_new_items = True
    preference.include_price_drops = True
    preference.new_items_per_site_limit = 3
    preference.price_drops_per_site_limit = 3
    seeded.commit()
    seeded.refresh(user)
    return user


def add_items(session, site, count, *, since_hours=1, prefix="new"):
    now = utcnow()
    created = []
    for index in range(count):
        item = Item(
            site_id=site.id,
            external_key=f"{prefix}-{index}",
            url=f"https://example.test/{prefix}-{index}",
            title=f"{prefix.title()} rifle {index}",
            current_price=500.0 + index,
            is_active=True,
            first_seen_at=now - timedelta(hours=since_hours),
            last_seen_at=now,
        )
        session.add(item)
        created.append(item)
    session.commit()
    return created


class TestNewItems:
    def test_collects_items_since_the_watermark(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        add_items(seeded, site, 2)
        preference = user_with_prefs.email_preference
        preference.last_digest_cutoff = utcnow() - timedelta(days=1)
        seeded.commit()

        found = digest.collect_new_items(
            seeded, preference, [site.id], preference.last_digest_cutoff
        )
        assert len(found[site.id]) == 2

    def test_per_site_limit_is_enforced(self, seeded, user_with_prefs):
        """The whole point of the cap: a big scan must not flood the email."""
        site = seeded.query(Site).first()
        add_items(seeded, site, 25)
        preference = user_with_prefs.email_preference
        preference.new_items_per_site_limit = 3
        seeded.commit()

        found = digest.collect_new_items(
            seeded, preference, [site.id], utcnow() - timedelta(days=1)
        )
        assert len(found[site.id]) == 3

    def test_older_items_are_excluded(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        add_items(seeded, site, 2, since_hours=72)
        found = digest.collect_new_items(
            seeded, user_with_prefs.email_preference, [site.id], utcnow() - timedelta(hours=24)
        )
        assert found == {}

    def test_disabled_section_collects_nothing(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        add_items(seeded, site, 2)
        preference = user_with_prefs.email_preference
        preference.include_new_items = False
        seeded.commit()
        assert (
            digest.collect_new_items(seeded, preference, [site.id], utcnow() - timedelta(days=1))
            == {}
        )


class TestPriceDrops:
    def _drop(self, session, site, was, now_price, hours_ago=1):
        item = Item(
            site_id=site.id,
            external_key=f"drop-{was}-{now_price}",
            url="https://example.test/drop",
            title="Reduced rifle",
            previous_price=was,
            current_price=now_price,
            price_changed_at=utcnow() - timedelta(hours=hours_ago),
            is_active=True,
            first_seen_at=utcnow() - timedelta(days=30),
            last_seen_at=utcnow(),
        )
        session.add(item)
        session.commit()
        return item

    def test_collects_reductions(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        self._drop(seeded, site, 900.0, 700.0)
        found = digest.collect_price_drops(
            seeded, user_with_prefs.email_preference, [site.id], utcnow() - timedelta(days=1)
        )
        assert len(found[site.id]) == 1

    def test_price_rises_are_excluded(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        self._drop(seeded, site, 500.0, 900.0)
        found = digest.collect_price_drops(
            seeded, user_with_prefs.email_preference, [site.id], utcnow() - timedelta(days=1)
        )
        assert found == {}

    def test_minimum_drop_filter(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        self._drop(seeded, site, 505.0, 500.0)  # $5 off
        self._drop(seeded, site, 900.0, 700.0)  # $200 off
        preference = user_with_prefs.email_preference
        preference.minimum_price_drop = 50.0
        seeded.commit()

        found = digest.collect_price_drops(
            seeded, preference, [site.id], utcnow() - timedelta(days=1)
        )
        assert len(found[site.id]) == 1


class TestSiteSelection:
    def test_no_selection_means_every_enabled_site(self, seeded, user_with_prefs):
        chosen = digest.selected_site_ids(seeded, user_with_prefs.email_preference)
        enabled = [s.id for s in seeded.query(Site).filter_by(enabled=True).all()]
        assert sorted(chosen) == sorted(enabled)

    def test_explicit_selection_is_honored(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        preference = user_with_prefs.email_preference
        seeded.add(EmailPreferenceSite(preference_id=preference.id, site_id=site.id))
        seeded.commit()
        seeded.refresh(preference)
        assert digest.selected_site_ids(seeded, preference) == [site.id]

    def test_disabled_sites_drop_out_of_a_selection(self, seeded, user_with_prefs):
        site = seeded.query(Site).first()
        preference = user_with_prefs.email_preference
        seeded.add(EmailPreferenceSite(preference_id=preference.id, site_id=site.id))
        site.enabled = False
        seeded.commit()
        seeded.refresh(preference)
        assert digest.selected_site_ids(seeded, preference) == []


class TestRendering:
    def test_html_contains_the_listings(self, seeded, user_with_prefs, app_config):
        site = seeded.query(Site).first()
        add_items(seeded, site, 2)
        built = digest.build_digest(seeded, user_with_prefs, app_config)
        assert built is not None
        subject, body, new_count, _drop_count, _cutoff = built

        assert new_count == 2
        assert "new listing" in subject
        assert body.startswith("<!doctype html>")
        assert "New rifle 0" in body
        assert site.name in body

    def test_titles_are_escaped(self, seeded, user_with_prefs, app_config):
        """Vendor titles are untrusted text and must not become markup."""
        site = seeded.query(Site).first()
        seeded.add(
            Item(
                site_id=site.id,
                external_key="xss",
                url="https://example.test/xss",
                title='<script>alert("x")</script>',
                current_price=100.0,
                is_active=True,
                first_seen_at=utcnow(),
                last_seen_at=utcnow(),
            )
        )
        seeded.commit()
        _subject, body, *_ = digest.build_digest(seeded, user_with_prefs, app_config)
        assert "<script>alert" not in body
        assert "&lt;script&gt;" in body

    def test_empty_digest_says_so(self, seeded, user_with_prefs, app_config):
        subject, body, new_count, drop_count, _ = digest.build_digest(
            seeded, user_with_prefs, app_config
        )
        assert new_count == 0 and drop_count == 0
        assert "nothing new" in subject
        assert "No new listings" in body


class TestSending:
    def test_empty_digest_is_skipped(self, seeded, user_with_prefs, app_config):
        user_with_prefs.email_preference.skip_when_empty = True
        seeded.commit()
        log = digest.send_digest_for_user(seeded, user_with_prefs, app_config)
        assert log.status == EmailStatus.SKIPPED
        # The schedule still advances, or the user would be re-checked forever.
        assert user_with_prefs.email_preference.next_send_at is not None

    def test_delivery_failure_is_recorded(self, seeded, user_with_prefs, app_config, monkeypatch):
        site = seeded.query(Site).first()
        add_items(seeded, site, 1)

        def boom(*args, **kwargs):
            raise mailer.MailError("smtp is down")

        monkeypatch.setattr(digest.mailer, "send_html", boom)
        log = digest.send_digest_for_user(seeded, user_with_prefs, app_config)

        assert log.status == EmailStatus.FAILED
        assert "smtp is down" in log.error_message
        # The watermark must not advance, or those listings are lost forever.
        assert user_with_prefs.email_preference.last_digest_cutoff is None

    def test_successful_send_advances_the_watermark(
        self, seeded, user_with_prefs, app_config, monkeypatch
    ):
        site = seeded.query(Site).first()
        add_items(seeded, site, 1)
        sent = {}

        def capture(to, subject, body, text_body=None, config=None):
            sent.update(to=to, subject=subject, body=body)

        monkeypatch.setattr(digest.mailer, "send_html", capture)
        log = digest.send_digest_for_user(seeded, user_with_prefs, app_config)

        assert log.status == EmailStatus.SENT
        assert log.new_item_count == 1
        assert sent["to"] == user_with_prefs.email
        assert user_with_prefs.email_preference.last_digest_cutoff is not None

    def test_force_sends_even_when_empty(self, seeded, user_with_prefs, app_config, monkeypatch):
        monkeypatch.setattr(digest.mailer, "send_html", lambda *a, **k: None)
        log = digest.send_digest_for_user(seeded, user_with_prefs, app_config, force=True)
        assert log.status == EmailStatus.SENT

    def test_due_users(self, seeded, user_with_prefs):
        assert user_with_prefs.id in digest.due_user_ids(seeded)

    def test_disabled_users_are_not_due(self, seeded, user_with_prefs):
        user_with_prefs.email_preference.enabled = False
        seeded.commit()
        assert user_with_prefs.id not in digest.due_user_ids(seeded)

    def test_future_send_time_is_not_due(self, seeded, user_with_prefs):
        user_with_prefs.email_preference.next_send_at = utcnow() + timedelta(hours=5)
        seeded.commit()
        assert user_with_prefs.id not in digest.due_user_ids(seeded)


class TestNextSendTime:
    def test_advances_by_the_frequency(self, seeded, user_with_prefs):
        preference = user_with_prefs.email_preference
        preference.frequency_hours = 12
        base = utcnow()
        assert digest.next_send_time(preference, base) == base + timedelta(hours=12)
