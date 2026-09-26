"""Reading the vendors' mailing lists out of the notification account's inbox.

The account that sends Milsurp Monitor's email is subscribed to the marketing
email of the shops we read. This checks its inbox on a schedule, recognizes
the shops' mail, and records each message once. Recording one sets that
shop's ``sites.marketing_email_at``, which turns its mailing-list chip on the
Sites page from red to green. Following each email's links to the listings it
names is the next step (ROADMAP, "Vendor mailing lists", bite 2).

**It only ever reads.** The folder is opened read-only (IMAP ``EXAMINE``) and
headers are fetched with ``BODY.PEEK``, so nothing is marked read, moved or
deleted: it is somebody's mailbox, and replies to "request access" land in it
too. And only vendor mail is stored; everything else is looked at and left.

**Whose mail is it?** Measured on the real inbox in September 2026, most shops
send from their own domain (``deals@classicfirearms.com``). The exception is a
mailing service's *shared* domain: Apex sends through Constant Contact as
``customerservice-apexgunparts.com@shared1.ccsend.com``, a domain thousands of
businesses share, with ``Reply-To: customerservice@apexgunparts.com``. So a
message belongs to a shop when the shop's domain is the From domain, the
Reply-To domain, or a domain written into the From address itself. An opt-in
marketer that arrived with one of the signups ("Brownells via SafeOpt")
matches none of them, which is right: it is not a shop we read.
"""

from __future__ import annotations

import contextlib
import email
import imaplib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Config
from ..models import InboxSetting, Site, VendorEmail, as_utc, utcnow
from ..scrapers import get_scraper_class

#: Choices for how often to check, in hours.
ALLOWED_INTERVAL_HOURS = (1, 2, 4, 6, 12, 24)

#: How far back the first check looks. Older mail says nothing current.
FIRST_LOOK_DAYS = 30

#: How far before the last check each check starts. IMAP searches by date,
#: not time, and a message can arrive with a Date a little behind its arrival;
#: the overlap costs a few re-read headers, and the Message-ID keeps each
#: message recorded once.
OVERLAP_DAYS = 2

#: At most this many messages are examined per check, newest first.
MAX_MESSAGES = 500

_HEADERS = "(BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO SUBJECT DATE MESSAGE-ID)])"

#: A subject asking for the subscription to be confirmed, as double opt-in lists
#: send first: "Please Confirm Subscription", "Confirm Your Subscription". Not
#: the notice that it has been ("Subscription Confirmed"), which is the list
#: working.
CONFIRM_REQUEST = re.compile(
    r"\bplease\s+confirm\b|\bconfirm\s+(?:your\s+|my\s+)?(?:subscription|e-?mail|sign-?up)"
    r"|\bverify\s+your\s+e-?mail",
    re.I,
)

#: A domain written into an address's local part, as shared mailing services
#: do: ``customerservice-apexgunparts.com@shared1.ccsend.com``.
_EMBEDDED_DOMAIN = re.compile(r"([a-z0-9-]+\.(?:com|net|org|us|biz|co|info|store|shop))\b")


class Status:
    OK = "ok"
    FAILED = "failed"
    #: No username or password to sign in with. Not a failure of the mailbox.
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class Received:
    """What the headers of one message say."""

    message_id: str
    from_address: str
    reply_to: str
    subject: str
    sent_at: datetime | None


@dataclass(frozen=True)
class RunResult:
    status: str
    looked_at: int = 0
    recorded: int = 0
    error: str | None = None


# -- settings ------------------------------------------------------------------
def settings(session: Session) -> InboxSetting:
    """The one settings row, created if the database lacks it."""
    row = session.get(InboxSetting, 1)
    if row is None:
        row = InboxSetting(id=1)
        session.add(row)
        session.commit()
    return row


def is_due(session: Session, *, now: datetime | None = None) -> bool:
    """Whether a check is owed: switched on, and the last one old enough.

    Measured from ``last_run_at``, like hot deals and backups, so a process
    that restarts often keeps its cadence.
    """
    row = settings(session)
    if not row.enabled:
        return False
    last = as_utc(row.last_run_at)
    if last is None:
        return True
    return (now or utcnow()) - last >= timedelta(hours=max(1, row.interval_hours))


# -- whose mail is it -----------------------------------------------------------
def registrable(host: str) -> str:
    """The last two labels of a host name: ``e.classicfirearms.com`` ->
    ``classicfirearms.com``. Every shop read here is on a two-label domain; a
    ``.co.uk`` shop would need the public suffix list."""
    return ".".join(host.lower().strip(".").split(".")[-2:])


def _domains(address: str) -> set[str]:
    """Every shop domain an address could stand for."""
    address = address.lower().strip()
    if "@" not in address:
        return set()
    local, host = address.rsplit("@", 1)
    found = {registrable(host)}
    found.update(registrable(match) for match in _EMBEDDED_DOMAIN.findall(local))
    return found


def site_domains(sites: Iterable[Site]) -> dict[str, Site]:
    """Each shop's own domain, and any extra sender domains its scraper names."""
    found: dict[str, Site] = {}
    for site in sites:
        host = urlparse(site.base_url).hostname or ""
        if host:
            found.setdefault(registrable(host), site)
        scraper = get_scraper_class(site.slug)
        for extra in scraper.newsletter_sender_domains if scraper else ():
            found.setdefault(registrable(extra), site)
    return found


def vendor_of(message: Received, domains: dict[str, Site]) -> Site | None:
    """The shop this message is from, or None when it is not a shop's."""
    for address in (message.from_address, message.reply_to):
        for domain in _domains(address):
            if domain in domains:
                return domains[domain]
    return None


# -- reading the mailbox -----------------------------------------------------
def _text(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (ValueError, LookupError):
        return value.strip()


def _first_address(value: str | None) -> str:
    pairs = getaddresses([_text(value)])
    return pairs[0][1] if pairs else ""


def parse_headers(raw: bytes) -> Received | None:
    """One message's headers, or None when it has no Message-ID to key on."""
    message: Message = email.message_from_bytes(raw)
    message_id = _text(message.get("Message-ID"))
    if not message_id:
        return None
    try:
        sent_at = parsedate_to_datetime(_text(message.get("Date")))
    except (TypeError, ValueError):
        sent_at = None
    if sent_at is not None and sent_at.tzinfo is None:
        sent_at = None  # A zone-less Date cannot be placed; fall back to now.
    return Received(
        message_id=message_id[:512],
        from_address=_first_address(message.get("From"))[:320],
        reply_to=_first_address(message.get("Reply-To")),
        subject=_text(message.get("Subject"))[:500],
        sent_at=sent_at,
    )


def _imap_date(moment: datetime) -> str:
    return moment.strftime("%d-%b-%Y")


def fetch_headers(
    config: Config,
    since: datetime,
    *,
    connect: Callable[..., imaplib.IMAP4] = imaplib.IMAP4_SSL,
) -> list[bytes]:
    """The raw headers of every inbox message since ``since``, newest first."""
    mail = config.email
    client = connect(mail.imap_host, mail.imap_port, timeout=mail.timeout_seconds)
    try:
        client.login(mail.username, mail.password)
        # Read-only: EXAMINE rather than SELECT, so nothing changes.
        client.select("INBOX", readonly=True)
        status, data = client.uid("SEARCH", None, "SINCE", _imap_date(since))  # type: ignore[arg-type]
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()[-MAX_MESSAGES:]
        found: list[bytes] = []
        for uid in reversed(uids):
            status, parts = client.uid("FETCH", uid.decode(), _HEADERS)
            if status != "OK":
                continue
            found.extend(part[1] for part in parts if isinstance(part, tuple) and len(part) > 1)
        return found
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            client.logout()


def run(
    session: Session,
    config: Config,
    *,
    now: datetime | None = None,
    fetch: Callable[[Config, datetime], list[bytes]] = fetch_headers,
) -> RunResult:
    """Check the inbox once and record what the shops have sent."""
    now = now or utcnow()
    row = settings(session)
    mail = config.email
    if not mail.username or not mail.password:
        result = RunResult(
            status=Status.NOT_CONFIGURED,
            error="No email username and password in config.yaml to sign in with.",
        )
        _record(session, row, result, now)
        return result

    last = as_utc(row.last_run_at)
    since = (
        last - timedelta(days=OVERLAP_DAYS)
        if last is not None and row.last_status == Status.OK
        else now - timedelta(days=FIRST_LOOK_DAYS)
    )
    try:
        raw = fetch(config, since)
    except (imaplib.IMAP4.error, OSError) as exc:
        result = RunResult(status=Status.FAILED, error=f"{type(exc).__name__}: {exc}"[:500])
        _record(session, row, result, now)
        return result

    domains = site_domains(session.execute(select(Site)).scalars())
    known = set(session.execute(select(VendorEmail.message_id)).scalars())
    recorded = 0
    for headers in raw:
        message = parse_headers(headers)
        if message is None or message.message_id in known:
            continue
        site = vendor_of(message, domains)
        if site is None:
            continue
        sent = (message.sent_at or now).astimezone(UTC)
        asks = bool(CONFIRM_REQUEST.search(message.subject))
        session.add(
            VendorEmail(
                message_id=message.message_id,
                site_id=site.id,
                from_address=message.from_address,
                subject=message.subject,
                asks_to_confirm=asks,
                received_at=sent.replace(tzinfo=None),
                recorded_at=now.replace(tzinfo=None),
            )
        )
        known.add(message.message_id)
        # A confirmation request is not the list working yet; see
        # awaiting_confirmation.
        stamp = as_utc(site.marketing_email_at)
        if not asks and (stamp is None or stamp < sent):
            site.marketing_email_at = sent.replace(tzinfo=None)
        recorded += 1

    result = RunResult(status=Status.OK, looked_at=len(raw), recorded=recorded)
    _record(session, row, result, now)
    return result


def _record(session: Session, row: InboxSetting, result: RunResult, now: datetime) -> None:
    row.last_run_at = now.replace(tzinfo=None)
    row.last_status = result.status
    row.last_error = result.error
    row.last_looked_at = result.looked_at
    row.last_recorded = result.recorded
    session.commit()


def record_failure(session: Session, exc: Exception, *, now: datetime | None = None) -> None:
    """Note an unexpected failure where the page will show it.

    ``last_run_at`` moves too, so a check that raises every time is not
    retried on every scheduler tick.
    """
    _record(
        session,
        settings(session),
        RunResult(status=Status.FAILED, error=f"{type(exc).__name__}: {exc}"[:500]),
        now or utcnow(),
    )


def awaiting_confirmation(session: Session) -> dict[int, datetime]:
    """Shops whose latest word is a request to confirm the subscription.

    By site id, with when the request came. A shop is in here when it has sent
    a confirmation request and nothing but further requests since: somebody
    still has to open that email and click. Real mail after the request means
    it was confirmed.
    """
    latest_ask: dict[int, datetime] = {}
    for site_id, received_at in session.execute(
        select(VendorEmail.site_id, VendorEmail.received_at).where(
            VendorEmail.asks_to_confirm.is_(True), VendorEmail.site_id.is_not(None)
        )
    ):
        if site_id is not None and (site_id not in latest_ask or received_at > latest_ask[site_id]):
            latest_ask[site_id] = received_at
    if not latest_ask:
        return {}
    marketing = dict(
        session.execute(
            select(Site.id, Site.marketing_email_at).where(Site.id.in_(list(latest_ask)))
        ).all()
    )
    pending: dict[int, datetime] = {}
    for site_id, asked in latest_ask.items():
        last_mail = marketing.get(site_id)
        if last_mail is None or last_mail < asked:
            pending[site_id] = asked
    return pending


def recent(session: Session, limit: int = 20) -> list[VendorEmail]:
    """The newest vendor emails recorded, for the page."""
    return list(
        session.execute(
            select(VendorEmail).order_by(VendorEmail.received_at.desc()).limit(limit)
        ).scalars()
    )
