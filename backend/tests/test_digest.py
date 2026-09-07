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
        subject, body, _images, new_count, _drop_count, _cutoff = built

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
        subject, body, _images, new_count, drop_count, _ = digest.build_digest(
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

        def capture(to, subject, body, text_body=None, config=None, inline_images=None):
            sent.update(to=to, subject=subject, body=body, inline_images=inline_images)

        monkeypatch.setattr(digest.mailer, "send_html", capture)
        log = digest.send_digest_for_user(seeded, user_with_prefs, app_config)

        assert log.status == EmailStatus.SENT
        assert log.new_item_count == 1
        assert sent["to"] == user_with_prefs.email
        # The mark travels with the message; a remote <img> would be blocked.
        assert digest.MARK_CID in sent["inline_images"]
        assert f"cid:{digest.MARK_CID}" in sent["body"]
        # And what was sent is kept, so the digest page can show it later.
        assert log.body_html == sent["body"]
        assert log.body_text and "Milsurp" in log.body_text
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


class TestListingPhotographs:
    """A picture per listing, attached rather than linked.

    Mail clients block remote images by default, so a linked thumbnail is an
    empty box for most readers on first open. These travel with the message.
    """

    def _with_photo(self, session, item, store, app_config, size=(400, 300)):
        from PIL import Image

        from app.models import ItemPhoto

        relative = f"{item.site_id}/x{item.id}.jpg"
        path = store.absolute_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (90, 110, 140)).save(path, format="JPEG")
        session.add(
            ItemPhoto(
                item_id=item.id,
                source_url=f"https://vendor.test/{item.id}.jpg",
                filename=relative,
                thumb_filename=relative,
                position=0,
            )
        )
        session.commit()

    def test_a_listing_with_a_photo_carries_it(self, seeded, user_with_prefs, app_config):
        from app.services.image_store import ImageStore

        site = seeded.query(Site).first()
        add_items(seeded, site, 1)
        item = seeded.query(Item).filter(Item.site_id == site.id).one()
        self._with_photo(seeded, item, ImageStore(app_config), app_config)

        _subject, body, images, *_ = digest.build_digest(seeded, user_with_prefs, app_config)

        cid = f"item-{item.id}"
        assert cid in images
        assert f"cid:{cid}" in body
        # Shrunk for the message: the stored thumbnail is 640px and far too
        # heavy to attach twenty of.
        assert len(images[cid]) < 20_000

    def test_a_listing_without_one_is_still_listed(self, seeded, user_with_prefs, app_config):
        site = seeded.query(Site).first()
        add_items(seeded, site, 1)
        item = seeded.query(Item).filter(Item.site_id == site.id).one()

        _subject, body, images, *_ = digest.build_digest(seeded, user_with_prefs, app_config)

        assert f"item-{item.id}" not in images
        assert item.title in body

    def test_an_unreadable_file_costs_the_row_its_picture_and_nothing_else(
        self, seeded, user_with_prefs, app_config
    ):
        """A digest that failed to send because one photograph moved would be a
        poor trade."""
        from app.models import ItemPhoto

        site = seeded.query(Site).first()
        add_items(seeded, site, 1)
        item = seeded.query(Item).filter(Item.site_id == site.id).one()
        seeded.add(
            ItemPhoto(
                item_id=item.id,
                source_url="https://vendor.test/gone.jpg",
                filename="nowhere/gone.jpg",
                thumb_filename="nowhere/gone.jpg",
                position=0,
            )
        )
        seeded.commit()

        _subject, body, images, *_ = digest.build_digest(seeded, user_with_prefs, app_config)

        assert f"item-{item.id}" not in images
        assert item.title in body

    def test_the_number_of_pictures_is_bounded(
        self, seeded, user_with_prefs, app_config, monkeypatch
    ):
        """A night when four vendors all restock should not arrive as a
        megabyte of photographs on a phone."""
        from app.services.image_store import ImageStore

        monkeypatch.setattr(digest, "MAX_EMAIL_PHOTOS", 2)
        site = seeded.query(Site).first()
        add_items(seeded, site, 5)
        store = ImageStore(app_config)
        for item in seeded.query(Item).filter(Item.site_id == site.id).all():
            self._with_photo(seeded, item, store, app_config)

        _subject, _body, images, *_ = digest.build_digest(seeded, user_with_prefs, app_config)

        # Two listings plus the brand mark.
        assert len(images) == 3
