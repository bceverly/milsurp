"""SMTP delivery.

Credentials come from the ``email`` section of the config file. For Gmail this
means an **App Password**, not the account password: Google blocks plain
password SMTP on accounts with 2-Step Verification, and an app password can be
revoked on its own without touching the account.
"""

from __future__ import annotations

import contextlib
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import unescape

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
    message.set_content(text_body or _html_to_text(html_body))
    message.add_alternative(html_body, subtype="html")

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


def _html_to_text(html_body: str) -> str:
    """Crude HTML-to-text for the plain alternative."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html_body)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
