"""Reading the vendors' mailing lists out of the notification account's inbox.

Header shapes below are the real ones, from the first mail the shops sent
after the account subscribed in September 2026.
"""

from __future__ import annotations

import dataclasses
import imaplib
from datetime import UTC, datetime, timedelta

import pytest

from app.models import InboxSetting, Site, VendorEmail, utcnow
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


def no_network(url, **_kwargs):
    raise AssertionError(f"a test tried to reach the network: {url}")


def check(session, config, *messages, now=NOW, get=no_network):
    """A check over these messages. Each is headers alone, or (headers, body).

    ``get`` refuses by default: a test that resolves a link says where it
    leads, and nothing here ever reaches a real mailing service.
    """
    fetched = [m if isinstance(m, tuple) else (m, None) for m in messages]
    return inbox.run(
        session, config, now=now, fetch=lambda _config, _since, _wanted: fetched, get=get
    )


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
        def refuse(_config, _since, _wanted):
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

        def spy(_config, since, _wanted):
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
    def test_it_is_opened_read_only_and_everything_is_peeked(self, signed_in):
        server = FakeImap([CLASSIC, APEX])
        found = inbox.fetch_messages(signed_in, NOW, lambda _h: False, connect=server)
        assert [headers for headers, _body in found] == [APEX, CLASSIC]  # newest first
        assert ("select", "INBOX", True) in server.calls
        fetches = [call for call in server.calls if call[0] == "FETCH"]
        assert fetches and all("BODY.PEEK" in call[2] for call in fetches)
        assert ("SEARCH", None, "SINCE", "26-Sep-2026") in server.calls
        assert server.calls[-1] == ("logout",)

    def test_only_wanted_messages_have_their_body_read(self, signed_in):
        """The shops' mail, never anybody else's."""
        server = FakeImap([CLASSIC, SAFEOPT])
        found = inbox.fetch_messages(
            signed_in, NOW, lambda headers: b"classicfirearms" in headers, connect=server
        )
        bodies = dict(found)
        assert bodies[CLASSIC] is not None
        assert bodies[SAFEOPT] is None
        whole = [call for call in server.calls if call[0] == "FETCH" and call[2] == "(BODY.PEEK[])"]
        assert len(whole) == 1

    def test_it_signs_in_with_the_smtp_account(self, signed_in):
        server = FakeImap([])
        inbox.fetch_messages(signed_in, NOW, lambda _h: False, connect=server)
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


class TestMarkedConfirmedByHand:
    """For a list that confirms silently: Mailchimp sends no "you're confirmed"
    message unless the list owner turned it on, so J&G stayed amber after the
    subscription was confirmed twice."""

    def test_it_settles_a_pending_request(self, clean_db, shops, signed_in):
        check(clean_db, signed_in, JG_ASKS)
        shops["jg-sales"].newsletter_confirmed_at = NOW.replace(hour=19, tzinfo=None)
        clean_db.commit()
        assert inbox.awaiting_confirmation(clean_db) == {}

    def test_but_a_new_request_after_it_is_pending_again(self, clean_db, shops, signed_in):
        """Signing up again sends a fresh request, which is news."""
        shops["jg-sales"].newsletter_confirmed_at = (NOW - timedelta(days=1)).replace(tzinfo=None)
        clean_db.commit()
        check(clean_db, signed_in, JG_ASKS)
        assert shops["jg-sales"].id in inbox.awaiting_confirmation(clean_db)

    def _seeded_jg(self, session):
        """The ``client`` fixture seeds every registered shop, J&G among them."""
        return session.query(Site).filter_by(slug="jg-sales").one()

    def test_the_endpoint_records_it_and_says_who(self, client, admin_headers, clean_db):
        from app.models import AuditEvent

        site = self._seeded_jg(clean_db)
        clean_db.add(
            VendorEmail(
                message_id="<ask@jgsales.com>",
                site_id=site.id,
                from_address="news@jgsales.com",
                subject="J&G Sales News: Please Confirm Subscription",
                asks_to_confirm=True,
                # From the real clock: the endpoint stamps the confirmation
                # with the real time, and the request must come before it.
                received_at=(utcnow() - timedelta(hours=3)).replace(tzinfo=None),
            )
        )
        clean_db.commit()
        before = client.get(f"/api/sites/{site.id}", headers=admin_headers).json()
        assert before["confirmation_requested_at"] is not None

        body = client.post(
            f"/api/sites/{site.id}/newsletter/confirmed", headers=admin_headers
        ).json()
        assert body["confirmation_requested_at"] is None
        assert body["newsletter_confirmed_at"] is not None
        actions = [event.action for event in clean_db.query(AuditEvent)]
        assert "site.newsletter_confirmed" in actions

    def test_a_reader_cannot(self, client, normal_user, clean_db):
        response = client.post(
            f"/api/sites/{self._seeded_jg(clean_db).id}/newsletter/confirmed",
            headers=normal_user["headers"],
        )
        assert response.status_code == 403

    def test_an_unknown_site(self, client, admin_headers):
        response = client.post("/api/sites/999999/newsletter/confirmed", headers=admin_headers)
        assert response.status_code == 404


def with_body(headers_bytes, html):
    """A whole message: these headers and an HTML body."""
    return (
        headers_bytes,
        headers_bytes.rstrip(b"\r\n")
        + b"\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        + html.encode(),
    )


class TestFollowingTheLinks:
    """From an email to the listings it names, and what that changes."""

    LISTING = "https://www.classicfirearms.com/m96-swedish-mauser/"

    @pytest.fixture
    def held(self, clean_db, shops):
        from app.models import Item

        item = Item(
            site_id=shops["classic-firearms"].id,
            external_key="m96",
            url=self.LISTING,
            title="Swedish M96 Mauser",
            current_price=650.0,
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.commit()
        return item

    @pytest.fixture
    def shop_page(self, monkeypatch):
        """Classic's scraper, answering a single-listing re-read."""
        from app.scrapers.base import PriceCheck

        asked = []

        class Scraper:
            def check_price(self, _ctx, url, *, key=None):
                asked.append(url)
                return PriceCheck(price=585.0)

        monkeypatch.setattr(inbox, "get_scraper", lambda _slug: Scraper())
        return asked

    def redirects(self, target):
        from test_maillinks import Redirects

        return Redirects({"https://ctrk.klclick1.com/l/A_1": target})

    EMAIL = (
        '<a href="https://ctrk.klclick1.com/l/A_1"><img alt="Image of M96 Mauser"></a>'
        '<a href="https://manage.kmail-lists.com/subscriptions/unsubscribe">Unsubscribe</a>'
    )

    def test_a_named_listing_is_re_read_and_its_new_price_stored(
        self, clean_db, shops, held, shop_page, signed_in
    ):
        result = check(
            clean_db,
            signed_in,
            with_body(CLASSIC, self.EMAIL),
            get=self.redirects(f"{self.LISTING}?utm_source=Klaviyo"),
        )
        assert (result.links, result.rechecked, result.prices_changed) == (1, 1, 1)
        assert shop_page == [self.LISTING]
        clean_db.refresh(held)
        assert held.current_price == 585.0
        assert held.previous_price == 650.0
        link = clean_db.query(inbox.VendorEmailLink).one()
        assert (link.item_id, link.outcome, link.how) == (held.id, "changed", "resolved")

    def test_a_page_we_do_not_hold_queues_a_scan(self, clean_db, shops, signed_in):
        """New sale listings are found by the shop's scraper, within the
        sections it reads -- the email only says to look now."""
        site = shops["classic-firearms"]
        site.last_scan_at = (NOW - timedelta(days=1)).replace(tzinfo=None)
        clean_db.commit()
        result = check(
            clean_db,
            signed_in,
            with_body(CLASSIC, self.EMAIL),
            get=self.redirects("https://www.classicfirearms.com/deals-and-rebates/"),
        )
        assert result.scans_queued == 1
        clean_db.refresh(site)
        assert site.next_scan_at == NOW.replace(tzinfo=None)

    def test_but_not_a_shop_scanned_a_moment_ago(self, clean_db, shops, signed_in):
        site = shops["classic-firearms"]
        site.last_scan_at = (NOW - timedelta(hours=1)).replace(tzinfo=None)
        clean_db.commit()
        result = check(
            clean_db,
            signed_in,
            with_body(CLASSIC, self.EMAIL),
            get=self.redirects("https://www.classicfirearms.com/deals-and-rebates/"),
        )
        assert result.scans_queued == 0

    def test_an_email_s_links_are_followed_once_and_its_text_kept(self, clean_db, shops, signed_in):
        get = self.redirects("https://www.classicfirearms.com/deals-and-rebates/")
        check(clean_db, signed_in, with_body(CLASSIC, self.EMAIL), get=get)
        check(
            clean_db,
            signed_in,
            with_body(CLASSIC, self.EMAIL),
            get=get,
            now=NOW + timedelta(hours=2),
        )
        assert len(get.asked) == 1
        mail = clean_db.query(VendorEmail).one()
        assert mail.links_read_at is not None
        assert "M96 Mauser" not in (mail.body_text or "")  # alt text is not body text

    def test_an_email_recorded_before_links_were_followed_is_picked_up(
        self, clean_db, shops, signed_in
    ):
        check(clean_db, signed_in, CLASSIC)  # headers only: recorded, not followed
        assert clean_db.query(VendorEmail).one().links_read_at is None
        check(
            clean_db,
            signed_in,
            with_body(CLASSIC, self.EMAIL),
            get=self.redirects("https://www.classicfirearms.com/deals-and-rebates/"),
            now=NOW + timedelta(hours=2),
        )
        assert clean_db.query(VendorEmail).one().links_read_at is not None


class TestWhichShopsHaveBeenFollowed:
    """The running record of whose mail this reader has actually worked for."""

    def test_followed_unresolved_and_waiting(self, clean_db, shops, signed_in):
        from test_maillinks import Redirects

        email = '<a href="https://ctrk.klclick1.com/l/A_1">Shop now</a>'
        check(
            clean_db,
            signed_in,
            with_body(CLASSIC, email),
            with_body(APEX, '<a href="https://www.credova.com/offer">Finance it</a>'),
            get=Redirects(
                {"https://ctrk.klclick1.com/l/A_1": "https://www.classicfirearms.com/deals/"}
            ),
        )
        status = inbox.link_status(clean_db)
        assert status[shops["classic-firearms"].id].state == "followed"
        assert status[shops["classic-firearms"].id].services == ("Klaviyo",)
        assert status[shops["apex-gun-parts"].id].state == "unresolved"
        assert status[shops["jg-sales"].id].state == "waiting"

    def test_a_confirmation_request_does_not_count(self, clean_db, shops, signed_in):
        """Its links are confirm and unsubscribe: it says nothing about the
        shop's newsletters."""
        check(
            clean_db,
            signed_in,
            with_body(
                JG_ASKS, '<a href="https://jgsales.us12.list-manage.com/subscribe/confirm">Yes</a>'
            ),
        )
        assert inbox.link_status(clean_db)[shops["jg-sales"].id].state == "waiting"
