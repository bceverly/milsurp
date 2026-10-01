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

**And a failure has to last.** A rate-limited shop whose retry works an hour
later is not news; Checkpoint Charlie's mailed "stopped" and "scraping again"
nearly every day until a failure had to outlast a grace period to be reported.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import ScanRun, ScanStatus, Site, User, UserRole, utcnow
from app.services import mailer, scanalerts

GRACE = timedelta(hours=3)


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


def run_of(session, site, status, *, hours_ago: float = 0, **kwargs):
    started = (utcnow() - timedelta(hours=hours_ago)).replace(tzinfo=None)
    row = ScanRun(site_id=site.id, status=status, started_at=started, **kwargs)
    session.add(row)
    session.commit()
    return row


def fail(session, site, *, hours_ago: float = 0, error: str = "HTTPError: 500"):
    run = run_of(session, site, ScanStatus.FAILED, hours_ago=hours_ago, error_message=error)
    scanalerts.consider(session, site, run)
    return run


def later(hours: float):
    return utcnow() + timedelta(hours=hours)


class TestAFailureThatLasts:
    def test_is_reported_once_the_grace_has_passed(self, clean_db, site, admin, sent):
        fail(clean_db, site, error="HTTPError: 500")
        assert sent == []
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(1)) == []
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == ["alerts"]
        assert len(sent) == 1
        assert "stopped scraping" in sent[0]["subject"]
        assert "HTTPError: 500" in sent[0]["html"]
        assert "1 scan without one that worked" in sent[0]["html"]

    def test_only_once_however_long_it_lasts(self, clean_db, site, admin, sent):
        """The one that matters. Mailing nightly for a fortnight is how the
        next real failure gets filtered into a folder unread."""
        fail(clean_db, site)
        scanalerts.report_overdue(clean_db, GRACE, now=later(4))
        fail(clean_db, site)
        scanalerts.report_overdue(clean_db, GRACE, now=later(30))
        assert len(sent) == 1

    def test_the_message_counts_the_failed_scans_and_quotes_the_last(
        self, clean_db, site, admin, sent
    ):
        fail(clean_db, site, hours_ago=2, error="first")
        fail(clean_db, site, hours_ago=1, error="second")
        scanalerts.report_overdue(clean_db, GRACE, now=later(2))
        assert "2 scans without one that worked" in sent[0]["html"]
        assert "second" in sent[0]["html"]

    def test_then_recovery_is_reported(self, clean_db, site, admin, sent):
        fail(clean_db, site)
        scanalerts.report_overdue(clean_db, GRACE, now=later(4))
        fixed = run_of(clean_db, site, ScanStatus.SUCCESS, items_found=412, items_new=7)
        assert scanalerts.consider(clean_db, site, fixed) == "recovered"
        assert "is scraping again" in sent[-1]["subject"]
        assert "412" in sent[-1]["html"]
        assert (site.scan_failing_since, site.scan_failure_reported) == (None, False)

    def test_a_first_ever_scan_that_fails_counts_too(self, clean_db, site, admin, sent):
        """Nothing to compare against, and a shop that has never worked is
        worth hearing about -- once it has kept failing."""
        fail(clean_db, site)
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == ["alerts"]

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
        fail(clean_db, site)
        scanalerts.report_overdue(clean_db, GRACE, now=later(4))
        assert {message["to"] for message in sent} == {"boss@example.test", "second@example.test"}


class TestWhenItKeepsQuiet:
    def test_a_failure_that_recovers_inside_the_grace(self, clean_db, site, admin, sent):
        """The rate-limited shop whose retry works: neither "stopped" nor
        "scraping again"."""
        fail(clean_db, site)
        fixed = run_of(clean_db, site, ScanStatus.SUCCESS)
        assert scanalerts.consider(clean_db, site, fixed) is None
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == []
        assert sent == []

    def test_a_shop_that_is_still_working(self, clean_db, site, admin, sent):
        run_of(clean_db, site, ScanStatus.SUCCESS)
        again = run_of(clean_db, site, ScanStatus.SUCCESS)
        assert scanalerts.consider(clean_db, site, again) is None
        assert sent == []

    def test_a_partial_scan_is_not_a_broken_shop(self, clean_db, site, admin, sent):
        """Some pages or images failed and the catalog came through. That is a
        warning on the scan's own record, not a vendor that has gone quiet."""
        partial = run_of(clean_db, site, ScanStatus.PARTIAL, error_message="2 images failed")
        assert scanalerts.consider(clean_db, site, partial) is None
        assert site.scan_failing_since is None

    def test_a_canceled_scan_says_nothing_and_changes_nothing(self, clean_db, site, admin, sent):
        """An administrator pressing stop is not a vendor's doing, and must not
        clear a failure in progress either."""
        fail(clean_db, site)
        canceled = run_of(clean_db, site, ScanStatus.CANCELED)
        assert scanalerts.consider(clean_db, site, canceled) is None
        assert site.scan_failing_since is not None
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == ["alerts"]

    def test_the_clock_starts_at_the_first_failure(self, clean_db, site, admin, sent):
        first = fail(clean_db, site, hours_ago=2)
        fail(clean_db, site)
        assert site.scan_failing_since == first.started_at

    def test_a_disabled_shop_is_not_reported(self, clean_db, site, admin, sent):
        fail(clean_db, site)
        site.enabled = False
        clean_db.commit()
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == []

    def test_another_site_breaking_does_not_speak_for_this_one(self, clean_db, site, admin, sent):
        other = Site(slug="other", name="Other", base_url="https://o.test/")
        clean_db.add(other)
        clean_db.commit()
        fail(clean_db, other)
        working = run_of(clean_db, site, ScanStatus.SUCCESS)
        assert scanalerts.consider(clean_db, site, working) is None
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == ["other"]


class TestItCannotBreakAScan:
    def test_a_mail_failure_is_logged_and_swallowed(self, clean_db, site, admin, monkeypatch):
        """Alerting that can break a scan turns a mail outage into a scraping
        outage, and the failure it reports is its own. And it is not retried
        every tick: the next change of state will try again."""

        def explode(*args, **kwargs):
            raise mailer.MailError("no SMTP host")

        monkeypatch.setattr(mailer, "send_html", explode)
        fail(clean_db, site)
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == ["alerts"]
        assert site.scan_failure_reported

    def test_an_unexpected_error_is_swallowed_too(self, clean_db, site, admin, monkeypatch):
        monkeypatch.setattr(
            scanalerts, "_admin_addresses", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        fail(clean_db, site)
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == []
        site.scan_failure_reported = True
        clean_db.commit()
        fixed = run_of(clean_db, site, ScanStatus.SUCCESS)
        assert scanalerts.consider(clean_db, site, fixed) is None

    def test_no_administrator_with_an_address_is_not_a_crash(self, clean_db, site, sent):
        fail(clean_db, site)
        assert scanalerts.report_overdue(clean_db, GRACE, now=later(4)) == []
        assert site.scan_failure_reported
        fixed = run_of(clean_db, site, ScanStatus.SUCCESS)
        assert scanalerts.consider(clean_db, site, fixed) is None
        assert sent == []

    def test_a_failure_with_no_failed_run_left_is_marked_and_skipped(
        self, clean_db, site, admin, sent
    ):
        site.scan_failing_since = (utcnow() - timedelta(hours=5)).replace(tzinfo=None)
        clean_db.commit()
        assert scanalerts.report_overdue(clean_db, GRACE) == []
        assert site.scan_failure_reported and sent == []

    def test_the_scheduler_reports_on_its_tick(self, clean_db, site, admin, sent, app_config):
        from app.scheduler import Scheduler

        fail(clean_db, site, hours_ago=5)
        Scheduler(app_config)._report_failing_shops()
        clean_db.refresh(site)
        assert site.scan_failure_reported
        assert len(sent) == 1
