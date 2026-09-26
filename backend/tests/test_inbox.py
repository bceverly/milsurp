"""Reading the vendors' mailing lists out of the notification account's inbox.

Header shapes below are the real ones, from the first mail the shops sent
after the account subscribed in September 2026.
"""

from __future__ import annotations

import dataclasses
import imaplib
from datetime import UTC, datetime, timedelta

import pytest

from app.models import InboxSetting, Site, VendorEmail
from app.services import inbox

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)


def headers(
    sender,
    subject="Welcome!",
    *,
    reply_to=None,
    message_id=None,
    date="Sat, 26 Sep 2026 11:17:00 -0400",
):
    lines = [
        f"From: {sender}",
        f"Subject: {subject}",
        f"Date: {date}",
        f"Message-ID: {message_id or '<' + str(abs(hash((sender, subject)))) + '@mail.test>'}",
    ]
    if reply_to:
        lines.append(f"Reply-To: {reply_to}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


CLASSIC = headers("Classic Firearms <deals@classicfirearms.com>", "Welcome To Classic Firearms")
APEX = headers(
    "APEX Gun Parts <customerservice-apexgunparts.com@shared1.ccsend.com>",
    "Hello and Welcome!",
    reply_to="customerservice@apexgunparts.com",
)
SAFEOPT = headers("Brownells via SafeOpt <offers@safeopt.com>", "Exclusive offer")
JG_ASKS = headers(
    "J&G Sales News <news@jgsales.com>", "J&G Sales News: Please Confirm Subscription"
)
JG_MAIL = headers(
    "J&G Sales News <news@jgsales.com>",
    "New surplus arrivals",
    date="Sun, 27 Sep 2026 09:00:00 -0400",
)


@pytest.fixture
def shops(clean_db):
    made = {
        slug: Site(slug=slug, name=name, base_url=url)
        for slug, name, url in [
            ("classic-firearms", "Classic Firearms", "https://www.classicfirearms.com/"),
            ("apex-gun-parts", "Apex Gun Parts", "https://www.apexgunparts.com/"),
            ("jg-sales", "J&G Sales", "https://www.jgsales.com/"),
        ]
    }
    clean_db.add_all(made.values())
    clean_db.commit()
    return made


@pytest.fixture
def signed_in(app_config):
    """A configuration with an account to read, as production has."""
    return dataclasses.replace(
        app_config,
        email=dataclasses.replace(app_config.email, username="notify@test", password="app-pass"),
    )


def check(session, config, *messages, now=NOW):
    return inbox.run(session, config, now=now, fetch=lambda _config, _since: list(messages))


class TestWhoseMailItIs:
    def domains(self, shops):
        return inbox.site_domains(shops.values())

    def test_a_shop_s_own_domain(self, shops):
        found = inbox.vendor_of(inbox.parse_headers(CLASSIC), self.domains(shops))
        assert found is shops["classic-firearms"]

    def test_a_subdomain_of_it(self, shops):
        message = inbox.parse_headers(headers("Classic <e@mail.classicfirearms.com>"))
        assert inbox.vendor_of(message, self.domains(shops)) is shops["classic-firearms"]

    def test_a_shared_mailing_service_that_names_the_shop(self, shops):
        """Constant Contact's shared domain is thousands of businesses; the
        shop is the domain written into the address, and the Reply-To."""
        found = inbox.vendor_of(inbox.parse_headers(APEX), self.domains(shops))
        assert found is shops["apex-gun-parts"]

    def test_reply_to_alone_is_enough(self, shops):
        message = inbox.parse_headers(
            headers("Deals <x@sendgrid.net>", reply_to="Sales <sales@jgsales.com>")
        )
        assert inbox.vendor_of(message, self.domains(shops)) is shops["jg-sales"]

    def test_a_marketer_that_is_not_a_shop_we_read(self, shops):
        """Arrived with one of the signups. Not a shop, so not recorded."""
        assert inbox.vendor_of(inbox.parse_headers(SAFEOPT), self.domains(shops)) is None


class TestConfirmationRequests:
    @pytest.mark.parametrize(
        "subject",
        [
            "J&G Sales News: Please Confirm Subscription",
            "Confirm Your Subscription",
            "Please verify your email address",
        ],
    )
    def test_a_request_to_confirm(self, subject):
        assert inbox.CONFIRM_REQUEST.search(subject)

    @pytest.mark.parametrize(
        "subject",
        [
            "JoeSalter.com New Arrival Updates: Subscription Confirmed",
            "Welcome To Classic Firearms",
            "Welcome! Your Discount Code is Enclosed!",
        ],
    )
    def test_not_a_request(self, subject):
        assert not inbox.CONFIRM_REQUEST.search(subject)


class TestACheck:
    def test_vendor_mail_is_recorded_and_the_rest_is_not(self, clean_db, shops, signed_in):
        result = check(clean_db, signed_in, CLASSIC, APEX, SAFEOPT)
        assert (result.status, result.looked_at, result.recorded) == ("ok", 3, 2)
        stored = {row.site_id for row in clean_db.query(VendorEmail)}
        assert stored == {shops["classic-firearms"].id, shops["apex-gun-parts"].id}

    def test_a_message_is_recorded_once(self, clean_db, shops, signed_in):
        """The search window overlaps the last check on purpose."""
        check(clean_db, signed_in, CLASSIC)
        again = check(clean_db, signed_in, CLASSIC, now=NOW + timedelta(hours=2))
        assert again.recorded == 0
        assert clean_db.query(VendorEmail).count() == 1

    def test_it_turns_the_shop_green_with_the_newest_mail(self, clean_db, shops, signed_in):
        check(clean_db, signed_in, CLASSIC)
        clean_db.refresh(shops["classic-firearms"])
        assert shops["classic-firearms"].marketing_email_at == datetime(
            2026, 9, 26, 15, 17, tzinfo=UTC
        ).replace(tzinfo=None)

    def test_a_confirmation_request_is_not_the_list_working(self, clean_db, shops, signed_in):
        check(clean_db, signed_in, JG_ASKS)
        clean_db.refresh(shops["jg-sales"])
        assert shops["jg-sales"].marketing_email_at is None
        assert shops["jg-sales"].id in inbox.awaiting_confirmation(clean_db)

    def test_real_mail_after_it_means_it_was_confirmed(self, clean_db, shops, signed_in):
        check(clean_db, signed_in, JG_ASKS, JG_MAIL)
        clean_db.refresh(shops["jg-sales"])
        assert shops["jg-sales"].marketing_email_at is not None
        assert inbox.awaiting_confirmation(clean_db) == {}

    def test_with_no_account_it_says_so_rather_than_failing(self, clean_db, shops, app_config):
        result = inbox.run(
            clean_db,
            dataclasses.replace(
                app_config, email=dataclasses.replace(app_config.email, username="", password="")
            ),
            now=NOW,
        )
        assert result.status == inbox.Status.NOT_CONFIGURED
        assert inbox.settings(clean_db).last_status == "not_configured"

    def test_a_mailbox_that_refuses_is_recorded_as_a_failure(self, clean_db, shops, signed_in):
        def refuse(_config, _since):
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

        result = inbox.run(clean_db, signed_in, now=NOW, fetch=refuse)
        assert result.status == inbox.Status.FAILED
        row = inbox.settings(clean_db)
        assert "Invalid credentials" in (row.last_error or "")
        # Moved, so a check that fails every time is not retried every tick.
        assert row.last_run_at is not None

    def test_the_first_check_looks_back_a_month_and_later_ones_overlap(
        self, clean_db, shops, signed_in
    ):
        windows = []

        def spy(_config, since):
            windows.append(since)
            return []

        inbox.run(clean_db, signed_in, now=NOW, fetch=spy)
        inbox.run(clean_db, signed_in, now=NOW + timedelta(hours=2), fetch=spy)
        assert windows[0] == NOW - timedelta(days=inbox.FIRST_LOOK_DAYS)
        assert windows[1] == NOW - timedelta(days=inbox.OVERLAP_DAYS)


class TestTheSchedule:
    def test_off_until_switched_on(self, clean_db):
        assert inbox.is_due(clean_db, now=NOW) is False

    def test_on_and_never_run_is_due(self, clean_db):
        inbox.settings(clean_db).enabled = True
        clean_db.commit()
        assert inbox.is_due(clean_db, now=NOW) is True

    def test_not_again_until_the_interval_has_passed(self, clean_db):
        row = inbox.settings(clean_db)
        row.enabled = True
        row.interval_hours = 2
        row.last_run_at = (NOW - timedelta(hours=1)).replace(tzinfo=None)
        clean_db.commit()
        assert inbox.is_due(clean_db, now=NOW) is False
        assert inbox.is_due(clean_db, now=NOW + timedelta(hours=1)) is True


class FakeImap:
    """An IMAP server with a few messages, recording what it was asked."""

    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def __call__(self, host, port, timeout=None):
        self.calls.append(("connect", host, port))
        return self

    def login(self, user, password):
        self.calls.append(("login", user))

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"3"]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(str(n).encode() for n in range(1, len(self.messages) + 1))]
        message = self.messages[int(args[0]) - 1]
        return "OK", [(b"1 (BODY[HEADER.FIELDS ...] {99}", message), b")"]

    def logout(self):
        self.calls.append(("logout",))


class TestTheMailbox:
    def test_it_is_opened_read_only_and_only_headers_are_peeked(self, signed_in):
        server = FakeImap([CLASSIC, APEX])
        found = inbox.fetch_headers(signed_in, NOW, connect=server)
        assert found == [APEX, CLASSIC]  # newest first
        assert ("select", "INBOX", True) in server.calls
        fetches = [call for call in server.calls if call[0] == "FETCH"]
        assert fetches and all("BODY.PEEK" in call[2] for call in fetches)
        assert ("SEARCH", None, "SINCE", "26-Sep-2026") in server.calls
        assert server.calls[-1] == ("logout",)

    def test_it_signs_in_with_the_smtp_account(self, signed_in):
        server = FakeImap([])
        inbox.fetch_headers(signed_in, NOW, connect=server)
        assert ("login", "notify@test") in server.calls
        assert ("connect", "imap.gmail.com", 993) in server.calls


class TestTheApi:
    def test_an_administrator_reads_it(self, client, admin_headers):
        body = client.get("/api/admin/inbox", headers=admin_headers).json()
        assert body["settings"]["enabled"] is False
        assert body["interval_choices"] == list(inbox.ALLOWED_INTERVAL_HOURS)
        assert "password" not in str(body).lower()

    def test_and_switches_it_on_at_an_allowed_interval(self, client, admin_headers):
        body = client.patch(
            "/api/admin/inbox", json={"enabled": True, "interval_hours": 6}, headers=admin_headers
        ).json()
        assert (body["settings"]["enabled"], body["settings"]["interval_hours"]) == (True, 6)

    def test_an_interval_off_the_list_is_refused(self, client, admin_headers):
        response = client.patch(
            "/api/admin/inbox", json={"interval_hours": 5}, headers=admin_headers
        )
        assert response.status_code == 400

    def test_check_now_reports_what_happened(self, client, admin_headers):
        """The test configuration has no account, and the page must say so
        rather than claim a quiet inbox."""
        body = client.post("/api/admin/inbox/check", headers=admin_headers).json()
        assert body["settings"]["last_status"] in {"not_configured", "ok", "failed"}
        assert body["settings"]["last_run_at"] is not None

    def test_a_reader_cannot(self, client, normal_user):
        assert client.get("/api/admin/inbox", headers=normal_user["headers"]).status_code == 403


def test_a_database_without_the_row_gets_one(clean_db):
    """The migration seeds it; a database built another way still works."""
    assert clean_db.get(InboxSetting, 1) is None
    assert inbox.settings(clean_db).enabled is False
