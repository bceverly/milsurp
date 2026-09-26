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
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Config
from ..models import (
    InboxSetting,
    Item,
    Site,
    VendorEmail,
    VendorEmailLink,
    as_utc,
    utcnow,
)
from ..scrapers import get_scraper, get_scraper_class
from ..scrapers.base import ScrapeContext
from . import cooldown, maillinks, watchpoll

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
    #: Links followed onto shops' sites, listings re-read because an email
    #: named them, how many of those had a new price, and shops queued for a
    #: scan because an email pointed at pages we do not hold.
    links: int = 0
    rechecked: int = 0
    prices_changed: int = 0
    scans_queued: int = 0


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


#: A fetched message: its headers, and its whole body when it was wanted.
Fetched = tuple[bytes, bytes | None]


def fetch_messages(
    config: Config,
    since: datetime,
    wanted: Callable[[bytes], bool],
    *,
    connect: Callable[..., imaplib.IMAP4] = imaplib.IMAP4_SSL,
) -> list[Fetched]:
    """Every inbox message since ``since``, newest first: headers always, the
    body only where ``wanted(headers)`` says so -- the shops' mail, never
    anybody else's."""
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
        found: list[Fetched] = []
        for uid in reversed(uids):
            headers = _part(client, uid.decode(), _HEADERS)
            if headers is None:
                continue
            body = _part(client, uid.decode(), "(BODY.PEEK[])") if wanted(headers) else None
            found.append((headers, body))
        return found
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            client.logout()


def _part(client: imaplib.IMAP4, uid: str, what: str) -> bytes | None:
    status, parts = client.uid("FETCH", uid, what)
    if status != "OK":
        return None
    for part in parts:
        if isinstance(part, tuple) and len(part) > 1:
            return bytes(part[1])
    return None


#: How long after a scan an email pointing at pages we do not hold is enough
#: to scan that shop again early.
RESCAN_AFTER = timedelta(hours=6)

#: Seconds between requests to a mailing service's click tracker. A
#: newsletter is forty links, and there is no call to send them all at once.
RESOLVE_PAUSE = 0.25

#: The email's text is kept to this length, for coupon codes and end dates.
MAX_BODY_TEXT = 20_000


def run(
    session: Session,
    config: Config,
    *,
    now: datetime | None = None,
    fetch: Callable[[Config, datetime, Callable[[bytes], bool]], list[Fetched]] = fetch_messages,
    get: Callable[..., requests.Response] | None = None,
) -> RunResult:
    """Check the inbox once: record what the shops have sent, and follow it."""
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
    domains = site_domains(session.execute(select(Site)).scalars())
    stored = {
        email_row.message_id: email_row
        for email_row in session.execute(select(VendorEmail)).scalars()
    }

    def wanted(headers: bytes) -> bool:
        message = parse_headers(headers)
        if message is None:
            return False
        known = stored.get(message.message_id)
        if known is not None:
            return known.links_read_at is None
        return vendor_of(message, domains) is not None

    try:
        fetched = fetch(config, since, wanted)
    except (imaplib.IMAP4.error, OSError) as exc:
        result = RunResult(status=Status.FAILED, error=f"{type(exc).__name__}: {exc}"[:500])
        _record(session, row, result, now)
        return result

    tally = _Tally()
    follower = _Follower(session, config, now, get=get)
    for headers, body in fetched:
        message = parse_headers(headers)
        if message is None:
            continue
        email_row = stored.get(message.message_id)
        if email_row is None:
            site = vendor_of(message, domains)
            if site is None:
                continue
            email_row = _store(session, message, site, now)
            stored[message.message_id] = email_row
            tally.recorded += 1
        if body is not None and email_row.links_read_at is None and email_row.site is not None:
            follower.follow(email_row, body)

    result = RunResult(
        status=Status.OK,
        looked_at=len(fetched),
        recorded=tally.recorded,
        links=follower.links,
        rechecked=follower.rechecked,
        prices_changed=follower.changed,
        scans_queued=follower.queued,
    )
    follower.close()
    _record(session, row, result, now)
    return result


@dataclass
class _Tally:
    recorded: int = 0


def _store(session: Session, message: Received, site: Site, now: datetime) -> VendorEmail:
    sent = (message.sent_at or now).astimezone(UTC)
    asks = bool(CONFIRM_REQUEST.search(message.subject))
    email_row = VendorEmail(
        message_id=message.message_id,
        site_id=site.id,
        site=site,
        from_address=message.from_address,
        subject=message.subject,
        asks_to_confirm=asks,
        received_at=sent.replace(tzinfo=None),
        recorded_at=now.replace(tzinfo=None),
    )
    session.add(email_row)
    # A confirmation request is not the list working yet; see
    # awaiting_confirmation.
    stamp = as_utc(site.marketing_email_at)
    if not asks and (stamp is None or stamp < sent):
        site.marketing_email_at = sent.replace(tzinfo=None)
    return email_row


def _parts(raw: bytes) -> tuple[str, str]:
    """An email's HTML and plain text."""
    message = email.message_from_bytes(raw)
    html: list[str] = []
    text: list[str] = []
    for part in message.walk():
        kind = part.get_content_type()
        if kind not in ("text/html", "text/plain"):
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        decoded_text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        (html if kind == "text/html" else text).append(decoded_text)
    return "\n".join(html), "\n".join(text)


class _Follower:
    """Follows one check's worth of vendor emails onto the shops' sites."""

    def __init__(
        self,
        session: Session,
        config: Config,
        now: datetime,
        *,
        get: Callable[..., requests.Response] | None,
    ) -> None:
        self.session = session
        self.config = config
        self.now = now
        self.get = get
        self.pause = RESOLVE_PAUSE if get is None else 0.0
        self.links = self.rechecked = self.changed = self.queued = 0
        self._ctx: ScrapeContext | None = None
        self._index: dict[int, dict[str, Item]] = {}

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()

    @property
    def ctx(self) -> ScrapeContext:
        if self._ctx is None:
            self._ctx = ScrapeContext(self.config)
        return self._ctx

    def listings(self, site: Site) -> dict[str, Item]:
        """This shop's active listings by address: the full address, and the
        address without its query string as a fallback."""
        if site.id not in self._index:
            index: dict[str, Item] = {}
            for item in self.session.execute(
                select(Item).where(Item.site_id == site.id, Item.is_active.is_(True))
            ).scalars():
                index.setdefault(maillinks.normalized(item.url), item)
                index.setdefault(maillinks.normalized(item.url, query=False), item)
            self._index[site.id] = index
        return self._index[site.id]

    def match(self, site: Site, url: str) -> Item | None:
        held = self.listings(site)
        return held.get(maillinks.normalized(url)) or held.get(
            maillinks.normalized(url, query=False)
        )

    def follow(self, email_row: VendorEmail, raw: bytes) -> None:
        site = email_row.site
        assert site is not None  # checked by the caller
        html, text = _parts(raw)
        email_row.body_text = (text or BeautifulSoup(html, "html.parser").get_text(" "))[
            :MAX_BODY_TEXT
        ]
        found = maillinks.html_of(html) if html else _plain_links(text)
        shop = registrable(urlparse(site.base_url).hostname or "")
        elsewhere = False
        for link in found:
            url, how = maillinks.destination(
                link.url, shop, get=self.get, user_agent=self.config.scraping.user_agent
            )
            if how == "resolved" and self.pause:
                time.sleep(self.pause)
            record = VendorEmailLink(email=email_row, link=link.url[:2048], text=link.text, how=how)
            record.url = url[:2048] if url else None
            self.session.add(record)
            if url is None:
                continue
            self.links += 1
            item = self.match(site, url)
            if item is None:
                elsewhere = True
                continue
            record.item_id = item.id
            record.outcome = self.recheck(site, item)
        if elsewhere:
            self.queue_scan(site)
        email_row.links_read_at = self.now.replace(tzinfo=None)

    def recheck(self, site: Site, item: Item) -> str:
        """Re-read one listing the email named, the way the watch poll does."""
        scraper = get_scraper(site.slug)
        if scraper is None or cooldown.paused_for(item.url) > 0:
            return "failed"
        try:
            found = scraper.check_price(self.ctx, item.url, key=item.external_key)
        except Exception:  # A shop's page failing must not stop the rest.
            return "failed"
        item.last_checked_at = self.now.replace(tzinfo=None)
        self.rechecked += 1
        if found is None:
            return "unreadable"
        outcome = "same"
        if found.sold_out and not item.is_sold:
            item.is_sold = True
            item.sold_at = self.now.replace(tzinfo=None)
            outcome = "sold"
        if watchpoll.record_price(self.session, item, found.price, self.now.replace(tzinfo=None)):
            self.changed += 1
            outcome = "changed"
        return outcome

    def queue_scan(self, site: Site) -> None:
        """Scan this shop soon: the email points at pages we do not hold."""
        if not site.enabled:
            return
        last = as_utc(site.last_scan_at)
        if last is not None and self.now - last < RESCAN_AFTER:
            return
        due = as_utc(site.next_scan_at)
        if due is not None and due <= self.now:
            return
        site.next_scan_at = self.now.replace(tzinfo=None)
        self.queued += 1


_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')]+")


def _plain_links(text: str) -> list[maillinks.Link]:
    """Links in a text-only email (AIM Surplus sends those)."""
    seen: list[str] = []
    for url in _URL_IN_TEXT.findall(text):
        if url not in seen and not maillinks.is_furniture(url):
            seen.append(url)
    return [maillinks.Link(url=url, text="") for url in seen[: maillinks.MAX_LINKS]]


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
    it was confirmed, and so does an administrator saying so
    (``sites.newsletter_confirmed_at``) for a list that sends no "confirmed"
    message of its own.
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
    settled = {
        site_id: [when for when in (mail, confirmed) if when is not None]
        for site_id, mail, confirmed in session.execute(
            select(Site.id, Site.marketing_email_at, Site.newsletter_confirmed_at).where(
                Site.id.in_(list(latest_ask))
            )
        )
    }
    pending: dict[int, datetime] = {}
    for site_id, asked in latest_ask.items():
        since = settled.get(site_id) or []
        if not since or max(since) < asked:
            pending[site_id] = asked
    return pending


#: Click trackers by host, for saying which mailing service a shop uses.
_SERVICES = (
    ("klclick", "Klaviyo"),
    ("kmail-lists", "Klaviyo"),
    ("mailchimp", "Mailchimp"),
    ("list-manage", "Mailchimp"),
    ("rs6.net", "Constant Contact"),
    ("ccsend", "Constant Contact"),
    ("sendgrid", "SendGrid"),
    ("privy", "Privy"),
)


def _service(link: str, shop_domain: str) -> str:
    host = (urlparse(link).hostname or "").lower()
    for marker, name in _SERVICES:
        if marker in host:
            return name
    if registrable(host) == shop_domain:
        # link.botach.com, enews.ima-usa.com: a tracker on the shop's own
        # domain (Listrak and its kind), or a plain link to the shop.
        return f"{host} tracker" if maillinks.is_tracker(link, shop_domain) else "direct links"
    return registrable(host)


@dataclass(frozen=True)
class LinkStatus:
    """Whether a shop's marketing email has been followed onto its site."""

    #: "followed", "unresolved" (mail read, no link reached the shop) or
    #: "waiting" (nothing read yet).
    state: str
    emails: int = 0
    followed: int = 0
    services: tuple[str, ...] = ()


def link_status(session: Session) -> dict[int, LinkStatus]:
    """Per shop, whether the links in its mail have been followed, and through
    which mailing service -- the record of which shops' mail this reader has
    actually worked for, so the ones not yet heard from can be checked when
    their first email arrives. Shops with nothing read are "waiting"."""
    found: dict[int, LinkStatus] = {}
    sites = {site.id: site for site in session.execute(select(Site)).scalars()}
    followed: dict[int, int] = {}
    services: dict[int, set[str]] = {}
    for site_id, link, url in session.execute(
        select(VendorEmail.site_id, VendorEmailLink.link, VendorEmailLink.url)
        .join(VendorEmailLink, VendorEmailLink.email_id == VendorEmail.id)
        .where(VendorEmail.asks_to_confirm.is_(False))
    ):
        if site_id is None or site_id not in sites or not url:
            continue
        shop = registrable(urlparse(sites[site_id].base_url).hostname or "")
        services.setdefault(site_id, set()).add(_service(link, shop))
        followed[site_id] = followed.get(site_id, 0) + 1
    emails: dict[int, int] = {
        site_id: count
        for site_id, count in session.execute(
            select(VendorEmail.site_id, func.count(VendorEmail.id))
            .where(
                VendorEmail.links_read_at.is_not(None),
                VendorEmail.site_id.is_not(None),
                # A "please confirm" request's links are confirm and
                # unsubscribe: it says nothing about the shop's newsletters.
                VendorEmail.asks_to_confirm.is_(False),
            )
            .group_by(VendorEmail.site_id)
        )
        if site_id is not None
    }
    for site_id in sites:
        if emails.get(site_id):
            found[site_id] = LinkStatus(
                state="followed" if followed.get(site_id) else "unresolved",
                emails=emails[site_id],
                followed=followed.get(site_id, 0),
                services=tuple(sorted(services.get(site_id, ()))),
            )
        else:
            found[site_id] = LinkStatus(state="waiting")
    return found


def recent(session: Session, limit: int = 20) -> list[VendorEmail]:
    """The newest vendor emails recorded, for the page."""
    return list(
        session.execute(
            select(VendorEmail).order_by(VendorEmail.received_at.desc()).limit(limit)
        ).scalars()
    )
