"""SMTP delivery: transport selection, message shape and error translation."""

from __future__ import annotations

import dataclasses
import smtplib

import pytest

from app.services import mailer


class FakeSMTP:
    """Records what would have been sent, instead of sending it."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.started_tls = False
        self.logged_in_as = None
        self.messages = []
        self.quit_called = False
        self.ehlo_count = 0
        FakeSMTP.instances.append(self)

    def ehlo(self):
        self.ehlo_count += 1

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in_as = (username, password)

    def send_message(self, message):
        self.messages.append(message)

    def quit(self):
        self.quit_called = True


@pytest.fixture(autouse=True)
def _reset():
    FakeSMTP.instances = []
    yield
    FakeSMTP.instances = []


def email_config(app_config, **overrides):
    defaults = dict(
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_security="starttls",
        username="sender@example.com",
        password="app-password",
        from_address="sender@example.com",
        from_name="Milsurp Monitor",
    )
    defaults.update(overrides)
    return dataclasses.replace(app_config, email=dataclasses.replace(app_config.email, **defaults))


class TestTransport:
    def test_starttls_is_negotiated(self, app_config, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        mailer.send_html(
            "to@example.com", "Subject", "<p>Body</p>", config=email_config(app_config)
        )

        server = FakeSMTP.instances[0]
        assert server.started_tls is True
        assert server.logged_in_as == ("sender@example.com", "app-password")
        assert server.quit_called is True

    def test_implicit_ssl_does_not_starttls(self, app_config, monkeypatch):
        """Port 465 is TLS from the first byte; STARTTLS would be an error."""
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        config = email_config(app_config, smtp_security="ssl", smtp_port=465)
        mailer.send_html("to@example.com", "Subject", "<p>Body</p>", config=config)

        server = FakeSMTP.instances[0]
        assert server.port == 465
        assert server.started_tls is False

    def test_plain_transport(self, app_config, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        config = email_config(app_config, smtp_security="none")
        mailer.send_html("to@example.com", "S", "<p>B</p>", config=config)
        assert FakeSMTP.instances[0].started_tls is False


class TestMessage:
    def test_is_multipart_with_a_text_alternative(self, app_config, monkeypatch):
        """HTML-only mail is penalized by filters and unreadable in some clients."""
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        mailer.send_html(
            "to@example.com",
            "New listings",
            "<html><body><h1>Rifle</h1><p>$500</p></body></html>",
            config=email_config(app_config),
        )
        message = FakeSMTP.instances[0].messages[0]

        assert message["Subject"] == "New listings"
        assert message["To"] == "to@example.com"
        assert "Milsurp Monitor" in message["From"]
        # Bulk headers keep digests out of vacation-responder loops.
        assert message["Auto-Submitted"] == "auto-generated"
        assert message["Precedence"] == "bulk"

        types = {part.get_content_type() for part in message.walk()}
        assert "text/plain" in types
        assert "text/html" in types

    def test_generated_text_alternative_strips_markup(self, app_config, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        mailer.send_html(
            "to@example.com",
            "S",
            "<html><body><p>Mosin Nagant</p><style>p{color:red}</style></body></html>",
            config=email_config(app_config),
        )
        message = FakeSMTP.instances[0].messages[0]
        text = message.get_body(preferencelist=("plain",)).get_content()
        assert "Mosin Nagant" in text
        assert "<p>" not in text
        assert "color:red" not in text

    def test_explicit_text_body_is_used(self, app_config, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        mailer.send_html(
            "to@example.com",
            "S",
            "<p>html</p>",
            text_body="plain version",
            config=email_config(app_config),
        )
        message = FakeSMTP.instances[0].messages[0]
        assert "plain version" in message.get_body(preferencelist=("plain",)).get_content()


class TestErrors:
    def test_disabled_email_raises(self, app_config):
        with pytest.raises(mailer.MailError, match="disabled"):
            mailer.send_html(
                "to@example.com", "S", "<p>B</p>", config=email_config(app_config, enabled=False)
            )

    def test_missing_sender_raises(self, app_config):
        config = email_config(app_config, from_address="", username="")
        with pytest.raises(mailer.MailError, match="from_address"):
            mailer.send_html("to@example.com", "S", "<p>B</p>", config=config)

    def test_connection_failure_is_translated(self, app_config, monkeypatch):
        def refuse(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(smtplib, "SMTP", refuse)
        with pytest.raises(mailer.MailError, match="could not connect"):
            mailer.send_html("to@example.com", "S", "<p>B</p>", config=email_config(app_config))

    def test_auth_failure_mentions_app_passwords(self, app_config, monkeypatch):
        """The overwhelmingly common cause with Gmail."""

        class RejectingSMTP(FakeSMTP):
            def login(self, username, password):
                raise smtplib.SMTPAuthenticationError(535, b"Bad credentials")

        monkeypatch.setattr(smtplib, "SMTP", RejectingSMTP)
        with pytest.raises(mailer.MailError, match="App Password"):
            mailer.send_html("to@example.com", "S", "<p>B</p>", config=email_config(app_config))

    def test_send_failure_is_translated(self, app_config, monkeypatch):
        class FailingSMTP(FakeSMTP):
            def send_message(self, message):
                raise smtplib.SMTPRecipientsRefused({"to@example.com": (550, b"No such user")})

        monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
        with pytest.raises(mailer.MailError, match="delivery to"):
            mailer.send_html("to@example.com", "S", "<p>B</p>", config=email_config(app_config))


class TestVerifyConnection:
    def test_success(self, app_config, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        message = mailer.verify_connection(email_config(app_config))
        assert "smtp.example.com:587" in message
        # Verification must not send anything.
        assert FakeSMTP.instances[0].messages == []

    def test_disabled_raises(self, app_config):
        with pytest.raises(mailer.MailError, match="disabled"):
            mailer.verify_connection(email_config(app_config, enabled=False))

    def test_auth_failure_raises(self, app_config, monkeypatch):
        class RejectingSMTP(FakeSMTP):
            def login(self, username, password):
                raise smtplib.SMTPAuthenticationError(535, b"nope")

        monkeypatch.setattr(smtplib, "SMTP", RejectingSMTP)
        with pytest.raises(mailer.MailError, match="App Password"):
            mailer.verify_connection(email_config(app_config))


class TestSupportAddress:
    def test_falls_back_through_from_address_then_username(self, app_config):
        config = email_config(app_config, support_email="")
        assert config.email.support_address == "sender@example.com"

    def test_explicit_support_email_wins(self, app_config):
        config = email_config(app_config, support_email="help@example.com")
        assert config.email.support_address == "help@example.com"
