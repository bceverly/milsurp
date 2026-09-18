"""Web Push: RFC 8291 encryption and RFC 8292 identification, written by hand.

The reason to write this rather than add `pywebpush` is the reason the
two-factor code was written against RFC 6238: the Debian package vendors every
dependency, and the parts that are subtle here are subtle whoever writes them.
The reason it is *safe* to write by hand is this file — in particular
`test_an_independent_implementation_can_decrypt_it`, which seals a message with
our code and opens it with `http_ece`, a separate implementation of the same
two RFCs. A round trip against ourselves would agree with whatever we had
misread; that one cannot.

`http_ece` is a development dependency and is never shipped.
"""

from __future__ import annotations

import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.services import webpush

http_ece = pytest.importorskip("http_ece", reason="the cross-check needs the dev dependency")


@pytest.fixture
def browser():
    """Stand in for a browser: it generates the key pair and the auth secret."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return private, public, os.urandom(16)


class TestTheEncryption:
    def test_an_independent_implementation_can_decrypt_it(self, browser):
        """The test the rest of this module rests on."""
        private, public, auth = browser
        plaintext = b'{"title":"A watched listing moved","url":"/items/42"}'

        sealed = webpush.encrypt(plaintext, public, auth)

        assert http_ece.decrypt(sealed, private_key=private, auth_secret=auth) == plaintext

    def test_the_header_is_shaped_as_rfc_8188_says(self, browser):
        """salt(16) | record size(4) | key id length(1) | key id."""
        _private, public, auth = browser
        sealed = webpush.encrypt(b"x", public, auth)

        assert len(sealed[:16]) == 16
        assert int.from_bytes(sealed[16:20], "big") == webpush.RECORD_SIZE
        assert sealed[20] == 65
        assert len(sealed[21:86]) == 65

    def test_every_message_is_sealed_differently(self, browser):
        """A fresh ephemeral key and salt per message, so two identical alerts
        do not produce identical ciphertext for anyone watching the wire."""
        _private, public, auth = browser
        assert webpush.encrypt(b"same", public, auth) != webpush.encrypt(b"same", public, auth)

    def test_a_message_for_one_browser_cannot_be_opened_by_another(self):
        """What binds the key to the subscription is the `WebPush: info` string
        carrying both public keys. Without it a captured message could be
        replayed at a different device."""
        first = ec.generate_private_key(ec.SECP256R1())
        second = ec.generate_private_key(ec.SECP256R1())
        public = first.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        auth = os.urandom(16)
        sealed = webpush.encrypt(b"secret", public, auth)

        with pytest.raises(http_ece.ECEException):
            http_ece.decrypt(sealed, private_key=second, auth_secret=auth)

    def test_nor_with_the_wrong_auth_secret(self, browser):
        private, public, auth = browser
        sealed = webpush.encrypt(b"secret", public, auth)

        with pytest.raises(http_ece.ECEException):
            http_ece.decrypt(sealed, private_key=private, auth_secret=os.urandom(16))


class TestTheVapidKeys:
    def test_a_generated_pair_loads_back(self):
        private, public = webpush.generate_keys()
        keys = webpush.load_keys(private, public)
        assert keys.public_key == public
        assert len(keys.public_bytes) == 65

    def test_a_mismatched_pair_is_refused_rather_than_used(self):
        """The failure this catches reads like a network problem at the far
        end: every message would be signed with one identity and announce
        another, and push services reject that without explaining."""
        private, _public = webpush.generate_keys()
        _other_private, other_public = webpush.generate_keys()

        with pytest.raises(webpush.PushError, match="does not belong"):
            webpush.load_keys(private, other_public)

    def test_the_public_half_is_what_a_browser_expects(self):
        """An uncompressed P-256 point, base64url, which is what
        `applicationServerKey` is defined to take."""
        _private, public = webpush.generate_keys()
        raw = webpush.unb64(public)
        assert len(raw) == 65
        assert raw[0] == 0x04


class TestTheVapidHeader:
    @pytest.fixture
    def keys(self):
        private, public = webpush.generate_keys()
        return webpush.load_keys(private, public)

    def test_it_is_a_signed_assertion_naming_this_server(self, keys):
        import base64

        header = webpush._vapid_header(
            keys, "https://updates.push.services.mozilla.com/wpush/v2/abc", "mailto:a@b.test"
        )
        assert header.startswith("vapid t=")
        token = header.split("t=")[1].split(",")[0]
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))

        # The audience is the *origin*. The path would tell anyone holding the
        # token which endpoints exist.
        assert claims["aud"] == "https://updates.push.services.mozilla.com"
        assert claims["sub"] == "mailto:a@b.test"

    def test_the_signature_is_the_raw_pair_jose_wants(self, keys):
        """`cryptography` signs to DER, which is variable-length. JOSE wants
        r||s at 32 bytes each, and a push service rejects the other without a
        word of explanation."""
        header = webpush._vapid_header(keys, "https://push.test/x", "mailto:a@b.test")
        token = header.split("t=")[1].split(",")[0]
        assert len(webpush.unb64(token.split(".")[2])) == 64

    def test_the_key_travels_with_it(self, keys):
        header = webpush._vapid_header(keys, "https://push.test/x", "mailto:a@b.test")
        assert f"k={keys.public_key}" in header

    def test_the_expiry_is_within_what_the_rfc_allows(self, keys):
        import base64
        import time

        header = webpush._vapid_header(keys, "https://push.test/x", "mailto:a@b.test")
        payload = header.split("t=")[1].split(",")[0].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        assert 0 < claims["exp"] - int(time.time()) <= 24 * 60 * 60


class TestSending:
    @pytest.fixture
    def keys(self):
        private, public = webpush.generate_keys()
        return webpush.load_keys(private, public)

    def test_an_oversized_payload_is_refused_before_the_network(self, keys, browser):
        _private, public, auth = browser
        with pytest.raises(webpush.PushError, match="over the"):
            webpush.send(
                "https://push.test/x",
                webpush.b64(public),
                webpush.b64(auth),
                {"body": "x" * (webpush.MAX_PAYLOAD + 1)},
                keys=keys,
                subject="mailto:a@b.test",
            )

    @pytest.mark.parametrize("code", [404, 410])
    def test_a_gone_subscription_says_so(self, keys, browser, monkeypatch, code):
        """404 and 410 mean the browser is gone. The only correct response is
        to forget it, which the caller can only do if it is told apart from a
        push service having a bad minute."""
        _private, public, auth = browser

        class Response:
            status_code = code
            text = ""

        monkeypatch.setattr(webpush.requests, "post", lambda *a, **k: Response())
        with pytest.raises(webpush.PushError) as caught:
            webpush.send(
                "https://push.test/x",
                webpush.b64(public),
                webpush.b64(auth),
                {"body": "hi"},
                keys=keys,
                subject="mailto:a@b.test",
            )
        assert caught.value.gone is True

    def test_another_failure_is_worth_retrying(self, keys, browser, monkeypatch):
        _private, public, auth = browser

        class Response:
            status_code = 503
            text = "busy"

        monkeypatch.setattr(webpush.requests, "post", lambda *a, **k: Response())
        with pytest.raises(webpush.PushError) as caught:
            webpush.send(
                "https://push.test/x",
                webpush.b64(public),
                webpush.b64(auth),
                {"body": "hi"},
                keys=keys,
                subject="mailto:a@b.test",
            )
        assert caught.value.gone is False

    def test_the_wire_headers_are_what_a_push_service_requires(self, keys, browser, monkeypatch):
        _private, public, auth = browser
        seen: dict = {}

        class Response:
            status_code = 201
            text = ""

        def capture(url, data=None, headers=None, timeout=None):
            seen.update(url=url, data=data, headers=headers)
            return Response()

        monkeypatch.setattr(webpush.requests, "post", capture)
        webpush.send(
            "https://push.test/x",
            webpush.b64(public),
            webpush.b64(auth),
            {"body": "hi"},
            keys=keys,
            subject="mailto:a@b.test",
        )
        assert seen["headers"]["Content-Encoding"] == "aes128gcm"
        assert seen["headers"]["Authorization"].startswith("vapid t=")
        assert seen["headers"]["TTL"] == str(webpush.DEFAULT_TTL)
        assert isinstance(seen["data"], bytes)
