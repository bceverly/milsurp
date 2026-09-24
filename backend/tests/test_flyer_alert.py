"""A new Hunter's Lodge flyer is mailed the day it is read, and only once."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import (
    EmailPreference,
    EmailPreferenceSite,
    FlyerNotice,
    Item,
    Site,
    User,
    UserRole,
)
from app.scrapers.hunters_lodge import HuntersLodgeScraper, signature_of
from app.security import hash_password
from app.services import digest, flyer_alert

JULY = "10a0ff_57a8a017e5354d569d42837e8c3b4ae5~mv2-july-2026"
AUGUST = "10a0ff_99b8a017e5354d569d42837e8c3b4ae5~mv2-august-2026"


class TestTheSignature:
    @pytest.mark.parametrize(
        "key",
        [f"{JULY}-0da474c1e7", f"{JULY}-0da474c1e7-2", f"{JULY}-whole"],
    )
    def test_it_is_the_key_less_the_listing_s_own_suffix(self, key):
        assert signature_of(key) == JULY

    def test_a_key_of_another_shape_has_none(self):
        assert signature_of("bc-12345") is None

    def test_the_scraper_announces_and_reads_it(self):
        assert HuntersLodgeScraper.announces_new_catalog is True
        assert HuntersLodgeScraper.catalog_signature(f"{JULY}-0da474c1e7") == JULY

    def test_and_is_looked_at_daily(self):
        assert HuntersLodgeScraper.default_interval_minutes == 60 * 24


@pytest.fixture
def world(clean_db):
    site = Site(slug="hunters-lodge", name="Hunter's Lodge", base_url="https://hl.test/")
    other = Site(slug="elsewhere", name="Elsewhere", base_url="https://e.test/")
    clean_db.add_all([site, other])
    clean_db.flush()

    def user(name):
        account = User(
            username=name,
            email=f"{name}@example.test",
            password_hash=hash_password("x" * 16),
            role=UserRole.NORMAL,
        )
        clean_db.add(account)
        return account

    user("everyone")  # no preferences at all: every site
    follows, ignores = user("follows"), user("ignores")
    clean_db.flush()
    for account, sites in ((follows, [site]), (ignores, [other])):
        preference = EmailPreference(user_id=account.id)
        clean_db.add(preference)
        clean_db.flush()
        for chosen in sites:
            clean_db.add(EmailPreferenceSite(preference_id=preference.id, site_id=chosen.id))
    clean_db.commit()
    return clean_db, site


def add_flyer(session, site, signature, count=3, active=True):
    for n in range(count):
        session.add(
            Item(
                site_id=site.id,
                external_key=f"{signature}-{n:010x}",
                url=site.base_url,
                title=f"LISTING {n} FROM {signature[-11:]}",
                current_price=100.0 + n,
                is_active=active,
            )
        )
    session.commit()


@pytest.fixture
def sent(monkeypatch):
    captured = []
    monkeypatch.setattr(
        digest.mailer,
        "send_html",
        lambda to, subject, body, **kwargs: captured.append((to, subject, body)),
    )
    return captured


class TestAnnouncing:
    def test_a_new_flyer_goes_to_everyone_following_the_site(self, world, sent):
        session, site = world
        add_flyer(session, site, AUGUST)
        assert flyer_alert.announce(session, site) == 2
        assert sorted(to for to, _s, _b in sent) == [
            "everyone@example.test",
            "follows@example.test",
        ]

    def test_it_names_every_listing(self, world, sent):
        session, site = world
        add_flyer(session, site, AUGUST, count=3)
        flyer_alert.announce(session, site)
        _to, subject, body = sent[0]
        assert "new Hunter's Lodge flyer, 3 listings" in subject
        for n in range(3):
            assert f"LISTING {n}" in body

    def test_it_is_sent_once(self, world, sent):
        session, site = world
        add_flyer(session, site, AUGUST)
        flyer_alert.announce(session, site)
        assert flyer_alert.announce(session, site) == 0
        assert len(sent) == 2
        notice = session.execute(select(FlyerNotice)).scalar_one()
        assert (notice.signature, notice.listings, notice.recipients) == (AUGUST, 3, 2)

    def test_an_old_flyer_already_taken_down_is_not_news(self, world, sent):
        session, site = world
        add_flyer(session, site, JULY, active=False)
        add_flyer(session, site, AUGUST)
        flyer_alert.announce(session, site)
        assert all("JULY" not in body.upper() for _to, _s, body in sent)

    def test_a_partial_read_says_so(self, world, sent):
        session, site = world
        add_flyer(session, site, AUGUST)
        flyer_alert.announce(session, site, partial=True)
        assert "read with some difficulty" in sent[0][2]

    def test_a_site_that_does_not_announce_sends_nothing(self, world, sent):
        session, _site = world
        other = session.execute(select(Site).where(Site.slug == "elsewhere")).scalar_one()
        add_flyer(session, other, AUGUST)
        assert flyer_alert.announce(session, other) == 0
        assert sent == []


class TestTheScanCallsIt:
    def test_only_when_the_scan_stored_something(self):
        """Checked against the source: an unchanged flyer reports itself
        unchanged and stores nothing, and must not reach the mailer."""
        import inspect

        from app.services import scan_service

        body = inspect.getsource(scan_service.run_scan)
        assert 'getattr(scraper, "announces_new_catalog", False) and created' in body
        assert "flyer_alert.announce(" in body
