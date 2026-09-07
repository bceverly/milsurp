"""SMTP delivery.

Credentials come from the ``email`` section of the config file. For Gmail this
means an **App Password**, not the account password: Google blocks plain
password SMTP on accounts with 2-Step Verification, and an app password can be
revoked on its own without touching the account.
"""

from __future__ import annotations

import contextlib
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html.parser import HTMLParser
from typing import cast

from ..config import Config, EmailConfig, get_config


class MailError(RuntimeError):
    """Delivery failed, or email is not configured."""


def _connection(cfg: EmailConfig) -> smtplib.SMTP:
    """Open an authenticated SMTP connection using the configured transport."""
    context = ssl.create_default_context()
    server: smtplib.SMTP
    if cfg.smtp_security == "ssl":
        server = smtplib.SMTP_SSL(
            cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_seconds, context=context
        )
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_seconds)
        server.ehlo()
        if cfg.smtp_security == "starttls":
            server.starttls(context=context)
            server.ehlo()
    if cfg.username:
        server.login(cfg.username, cfg.password)
    return server


def send_html(
    to_address: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    config: Config | None = None,
    inline_images: dict[str, bytes] | None = None,
) -> None:
    """Send one multipart HTML message. Raises :class:`MailError` on failure."""
    config = config or get_config()
    cfg = config.email
    if not cfg.enabled:
        raise MailError("email is disabled in the configuration file (email.enabled)")
    if not cfg.smtp_host:
        raise MailError("email.smtp_host is not set")
    sender = cfg.from_address or cfg.username
    if not sender:
        raise MailError("neither email.from_address nor email.username is set")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((cfg.from_name, sender)) if cfg.from_name else sender
    message["To"] = to_address
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    # Bulk precedence keeps digests out of vacation-responder loops.
    message["Auto-Submitted"] = "auto-generated"
    message["Precedence"] = "bulk"

    # A plain-text alternative always comes first; clients that cannot render
    # HTML, and spam filters that penalize HTML-only mail, both want it.
    message.set_content(text_body or html_to_text(html_body))
    message.add_alternative(html_body, subtype="html")

    # Anything the HTML refers to as cid: has to travel with it, in a
    # multipart/related part attached to the HTML alternative — not to the
    # message. A remote <img> would simply not render: mail clients block
    # those by default, which is why the mark used to be drawn out of CSS
    # borders and looked like it.
    if inline_images:
        # The related part hangs off the HTML alternative, not off the message.
        # get_body() is typed as the base Message, which has no add_related --
        # it is an EmailMessage here because that is what was just added.
        html_part = cast("EmailMessage", message.get_body(preferencelist=("html",)))
        for content_id, payload in inline_images.items():
            html_part.add_related(payload, maintype="image", subtype="png", cid=f"<{content_id}>")

    try:
        server = _connection(cfg)
    except smtplib.SMTPAuthenticationError as exc:
        # Login happens inside _connection(), and this is by far the most common
        # failure. It must be caught before the generic SMTPException below, or
        # the actionable advice is lost behind "could not connect".
        raise MailError(
            "SMTP authentication failed. For Gmail, email.password must be a "
            f"16-character App Password, not the account password ({exc})."
        ) from exc
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError(f"could not connect to {cfg.smtp_host}:{cfg.smtp_port}: {exc}") from exc

    try:
        server.send_message(message)
    except smtplib.SMTPException as exc:
        raise MailError(f"delivery to {to_address} failed: {exc}") from exc
    finally:
        # The message is already accepted at this point; a failure to close
        # cleanly must not turn a successful send into an error.
        with contextlib.suppress(Exception):
            server.quit()


def verify_connection(config: Config | None = None) -> str:
    """Connect and authenticate without sending. Used by the admin test button."""
    config = config or get_config()
    cfg = config.email
    if not cfg.enabled:
        raise MailError("email is disabled in the configuration file (email.enabled)")
    try:
        server = _connection(cfg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "SMTP authentication failed. For Gmail, use a 16-character App " f"Password ({exc})."
        ) from exc
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError(f"could not connect to {cfg.smtp_host}:{cfg.smtp_port}: {exc}") from exc
    try:
        return f"Connected to {cfg.smtp_host}:{cfg.smtp_port} as {cfg.username or '(anonymous)'}."
    finally:
        with contextlib.suppress(Exception):
            server.quit()


class _TextExtractor(HTMLParser):
    r"""Collects the readable prose out of an HTML document.

    A real parser rather than a chain of regular expressions. The regex version
    was quadratic on hostile input — patterns like ``<[^>]+>`` and
    ``<(script|style).*?</\1>`` rescan from every ``<`` — and a digest body
    embeds vendor-supplied titles and descriptions, so its input is not ours to
    trust. :class:`~html.parser.HTMLParser` is linear in the length of the
    document and handles character references for free.
    """

    #: Elements whose contents are markup or metadata, not prose.
    _SKIP = frozenset({"script", "style", "head", "title"})

    #: Elements that start or end a line of prose.
    _BREAK = frozenset({"br", "p", "div", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6"})

    #: Elements that separate words on the same line. Without this a row of
    #: table cells would run together as "AB".
    _SPACE = frozenset({"td", "th", "span", "a", "strong", "em", "b", "i"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, _attrs: object) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BREAK:
            self._parts.append("\n")
        elif tag in self._SPACE:
            self._parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        # The default implementation fires start *and* end, which would turn a
        # single <br/> into two line breaks.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self._BREAK:
            self._parts.append("\n")
        elif tag in self._SPACE:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self._parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self._parts)


def _collapse(text: str) -> str:
    r"""Squeeze runs of whitespace down, without a backtracking regex.

    ``str.split`` does the work a pattern like ``\n\s*\n\s*\n+`` used to,
    in one linear pass and with no way to blow up.
    """
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        # Keep at most one blank line between paragraphs.
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def html_to_text(html_body: str) -> str:
    """The plain-text alternative part for a multipart message."""
    parser = _TextExtractor()
    parser.feed(html_body)
    parser.close()
    return _collapse(parser.text)
