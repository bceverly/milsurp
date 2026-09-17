"""Mailing the administrators when a shop stops scraping, and when it starts again.

The canary already probes every shop nightly and mails what it finds. It is a
separate probe, though: a scan that dies at two in the morning waits until ten
past six to be noticed, and the canary stops after three listings, so a failure
on page nine passes it while every real scan fails.

**The discipline being tested is silence.** A site broken for a fortnight must
not mail every night for a fortnight — by the third night it is a rule in
somebody's mail client, and by the fifth the next real failure lands in the
same folder. So the question is never "did this scan fail?" but "is this
different from last time?", and most of the tests below are about the messages
that are *not* sent.
"""

from __future__ import annotations

import pytest

from app.models import ScanRun, ScanStatus, Site, User, UserRole
from app.services import mailer, scanalerts


@pytest.fixture
def site(clean_db):
    row = Site(slug="alerts", name="Alerts Surplus", base_url="https://a.test/")
    clean_db.add(row)
    clean_db.commit()
    return row


@pytest.fixture
def admin(clean_db):
    row = User(
        username="boss",
        email="boss@example.test",
        role=UserRole.ADMIN,
        is_active=True,
        password_hash="x",
    )
    clean_db.add(row)
    clean_db.commit()
    return row


@pytest.fixture
def sent(monkeypatch):
    box: list[dict] = []
    monkeypatch.setattr(
        mailer,
        "send_html",
        lambda to, subject, html, **kw: box.append({"to": to, "subject": subject, "html": html}),
    )
    return box


def run_of(session, site, status, **kwargs):
    row = ScanRun(site_id=site.id, status=status, **kwargs)
    session.add(row)
    session.commit()
    return row


class TestWhenItSpeaks:
    def test_a_working_shop_that_breaks(self, clean_db, site, admin, sent):
        run_of(clean_db, site, ScanStatus.SUCCESS)
        broke = run_of(clean_db, site, ScanStatus.FAILED, error_message="HTTPError: 500")

        assert scanalerts.consider(clean_db, site, broke) == "broken"
        assert len(sent) == 1
        assert "stopped scraping" in sent[0]["subject"]
        assert "HTTPError: 500" in sent[0]["html"]

    def test_a_broken_shop_that_recovers(self, clean_db, site, admin, sent):
        run_of(clean_db, site, ScanStatus.FAILED)
        fixed = run_of(clean_db, site, ScanStatus.SUCCESS, items_found=412, items_new=7)

        assert scanalerts.consider(clean_db, site, fixed) == "recovered"
        assert "is scraping again" in sent[0]["subject"]
        assert "412" in sent[0]["html"]

    def test_a_first_ever_scan_that_fails(self, clean_db, site, admin, sent):
        """Nothing to compare against, and a shop that has never worked is
        worth hearing about."""
        broke = run_of(clean_db, site, ScanStatus.FAILED)
        assert scanalerts.consider(clean_db, site, broke) == "broken"

    def test_every_active_administrator_is_told(self, clean_db, site, admin, sent):
        clean_db.add(
            User(
                username="second",
                email="second@example.test",
                role=UserRole.ADMIN,
                is_active=True,
                password_hash="x",
            )
        )
        clean_db.commit()
        run_of(clean_db, site, ScanStatus.SUCCESS)
        broke = run_of(clean_db, site, ScanStatus.FAILED)

        scanalerts.consider(clean_db, site, broke)
        assert {message["to"] for message in sent} == {"boss@example.test", "second@example.test"}


class TestWhenItKeepsQuiet:
    def test_a_shop_that_is_still_broken(self, clean_db, site, admin, sent):
        """The one that matters. Mailing nightly for a fortnight is how the
        next real failure gets filtered into a folder unread."""
        run_of(clean_db, site, ScanStatus.FAILED)
        again = run_of(clean_db, site, ScanStatus.FAILED)

        assert scanalerts.consider(clean_db, site, again) is None
        assert sent == []

    def test_a_shop_that_is_still_working(self, clean_db, site, admin, sent):
        run_of(clean_db, site, ScanStatus.SUCCESS)
        again = run_of(clean_db, site, ScanStatus.SUCCESS)

        assert scanalerts.consider(clean_db, site, again) is None
        assert sent == []

    def test_a_first_ever_scan_that_works(self, clean_db, site, admin, sent):
        """Nobody needs telling that a thing did what it was installed to do."""
        first = run_of(clean_db, site, ScanStatus.SUCCESS)
        assert scanalerts.consider(clean_db, site, first) is None

    def test_a_partial_scan_is_not_a_broken_shop(self, clean_db, site, admin, sent):
        """Some pages or images failed and the catalog came through. That is a
        warning on the scan's own record, not a vendor that has gone quiet."""
        run_of(clean_db, site, ScanStatus.SUCCESS)
        partial = run_of(clean_db, site, ScanStatus.PARTIAL, error_message="2 images failed")

        assert scanalerts.consider(clean_db, site, partial) is None
        assert sent == []

    def test_a_canceled_scan_says_nothing_and_changes_nothing(self, clean_db, site, admin, sent):
        """An administrator pressing stop is not a vendor's doing, and must not
        count as the previous verdict either -- otherwise a cancel between two
        failures would make the second one look like news."""
        run_of(clean_db, site, ScanStatus.FAILED)
        canceled = run_of(clean_db, site, ScanStatus.CANCELED)
        assert scanalerts.consider(clean_db, site, canceled) is None

        again = run_of(clean_db, site, ScanStatus.FAILED)
        assert scanalerts.consider(clean_db, site, again) is None
        assert sent == []

    def test_another_site_breaking_does_not_speak_for_this_one(self, clean_db, site, admin, sent):
        other = Site(slug="other", name="Other", base_url="https://o.test/")
        clean_db.add(other)
        clean_db.commit()
        run_of(clean_db, other, ScanStatus.FAILED)

        run_of(clean_db, site, ScanStatus.SUCCESS)
        working = run_of(clean_db, site, ScanStatus.SUCCESS)
        assert scanalerts.consider(clean_db, site, working) is None


class TestItCannotBreakAScan:
    def test_a_mail_failure_is_logged_and_swallowed(self, clean_db, site, admin, monkeypatch):
        """Alerting that can break a scan turns a mail outage into a scraping
        outage, and the failure it reports is its own."""

        def explode(*args, **kwargs):
            raise mailer.MailError("no SMTP host")

        monkeypatch.setattr(mailer, "send_html", explode)
        run_of(clean_db, site, ScanStatus.SUCCESS)
        broke = run_of(clean_db, site, ScanStatus.FAILED)

        assert scanalerts.consider(clean_db, site, broke) == "broken"

    def test_an_unexpected_error_is_swallowed_too(self, clean_db, site, admin, monkeypatch):
        monkeypatch.setattr(
            scanalerts, "_admin_addresses", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        run_of(clean_db, site, ScanStatus.SUCCESS)
        broke = run_of(clean_db, site, ScanStatus.FAILED)

        assert scanalerts.consider(clean_db, site, broke) is None

    def test_no_administrator_with_an_address_is_not_a_crash(self, clean_db, site, sent):
        run_of(clean_db, site, ScanStatus.SUCCESS)
        broke = run_of(clean_db, site, ScanStatus.FAILED)

        assert scanalerts.consider(clean_db, site, broke) is None
        assert sent == []
