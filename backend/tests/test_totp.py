"""Time-based one-time passwords, checked against the RFC rather than belief.

Written in the standard library instead of adding ``pyotp``, because the Debian
package vendors every wheel it ships and this one would not have earned the
build machinery. That trade is only defensible if the implementation is right,
so the first class here drives it at the exact timestamps RFC 6238 publishes
vectors for. If those pass, every authenticator app on every phone agrees with
this file.
"""

from __future__ import annotations

import base64
import time

import pytest

from app import totp

#: RFC 6238 Appendix B publishes its vectors for the ASCII secret
#: "12345678901234567890". The RFC prints it raw; this module speaks base32.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii").rstrip("=")

#: (unix time, expected code) for SHA-1, six digits, thirty-second steps —
#: the table in Appendix B, which is the only part of it this module implements.
RFC_VECTORS = [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
    (20000000000, "353130"),
]


class TestAgainstTheRfcsOwnVectors:
    @pytest.mark.parametrize(("when", "expected"), RFC_VECTORS)
    def test_every_published_vector(self, when, expected):
        assert totp.code_at(RFC_SECRET, when) == expected


class TestVerifying:
    def test_the_code_for_right_now(self):
        secret = totp.new_secret()
        assert totp.verify(secret, totp.code_at(secret, time.time())) is True

    def test_a_wrong_one(self):
        secret = totp.new_secret()
        assert totp.verify(secret, "000000") is False

    def test_a_little_drift_either_way(self):
        """Somebody reading six digits off a phone and typing them takes a few
        seconds, and a server whose clock has slipped should not lock its owner
        out."""
        secret = totp.new_secret()
        now = time.time()
        for offset in (-totp.PERIOD, 0, totp.PERIOD):
            assert totp.verify(secret, totp.code_at(secret, now + offset), now=now) is True

    def test_but_not_a_stale_one(self):
        """Each accepted step is another window in which a code somebody read
        over a shoulder is still good."""
        secret = totp.new_secret()
        now = time.time()
        assert totp.verify(secret, totp.code_at(secret, now - 3 * totp.PERIOD), now=now) is False

    @pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", None])
    def test_something_that_is_not_a_code(self, code):
        assert totp.verify(totp.new_secret(), code) is False

    def test_spaces_and_punctuation_are_forgiven(self):
        """Authenticators display "123 456" and people paste what they see."""
        secret = totp.new_secret()
        now = time.time()
        spaced = totp.code_at(secret, now)
        assert totp.verify(secret, f"{spaced[:3]} {spaced[3:]}", now=now) is True


class TestTheSecretItself:
    def test_a_new_one_is_base32_of_the_expected_length(self):
        secret = totp.new_secret()
        assert len(secret) == 32
        assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")

    def test_two_are_not_the_same(self):
        assert totp.new_secret() != totp.new_secret()

    def test_it_is_shown_in_blocks_for_typing(self):
        assert totp.grouped("ABCDEFGH") == "ABCD EFGH"

    def test_the_uri_carries_what_an_app_needs(self):
        uri = totp.provisioning_uri("ABCD", "bceverly")
        assert uri.startswith("otpauth://totp/")
        assert "secret=ABCD" in uri
        assert "issuer=Milsurp%20Monitor" in uri
        assert "digits=6" in uri and "period=30" in uri

    def test_a_secret_typed_back_in_with_spaces_still_works(self):
        secret = totp.new_secret()
        now = time.time()
        assert totp.code_at(totp.grouped(secret), now) == totp.code_at(secret, now)


class TestAtRest:
    """The secret is encrypted with a key derived from the pepper.

    Same property the pepper already buys for passwords: a stolen database on
    its own is not enough. Without it a dump hands an attacker both factors at
    once, which would make the second one decorative.
    """

    def test_it_survives_a_round_trip(self, app_config):
        secret = totp.new_secret()
        assert totp.unseal(totp.seal(secret, app_config), app_config) == secret

    def test_the_stored_form_does_not_contain_the_secret(self, app_config):
        secret = totp.new_secret()
        assert secret not in totp.seal(secret, app_config)

    def test_sealing_twice_gives_two_different_strings(self, app_config):
        """A fresh nonce each time, so two users with the same secret — or one
        user re-enrolling — do not produce matching rows."""
        secret = totp.new_secret()
        assert totp.seal(secret, app_config) != totp.seal(secret, app_config)

    def test_a_tampered_row_will_not_open(self, app_config):
        """None rather than a wrong secret: a row that has been edited is a
        second factor that cannot be checked, and the answer is to refuse the
        sign-in."""
        sealed = totp.seal(totp.new_secret(), app_config)
        broken = sealed[:-4] + ("AAAA" if not sealed.endswith("AAAA") else "BBBB")
        assert totp.unseal(broken, app_config) is None

    @pytest.mark.parametrize("stored", ["", None, "not-sealed-at-all", "v1:@@@", "v1:"])
    def test_nor_will_anything_else(self, stored, app_config):
        assert totp.unseal(stored, app_config) is None

    def test_a_different_pepper_cannot_read_it(self, app_config):
        """The whole point. A database restored onto a machine whose config
        holds a different pepper cannot produce the second factor."""
        import dataclasses

        sealed = totp.seal(totp.new_secret(), app_config)
        other = dataclasses.replace(
            app_config,
            security=dataclasses.replace(app_config.security, password_pepper="a-different-one"),
        )
        assert totp.unseal(sealed, other) is None

    def test_new_rows_are_written_as_v3_aes_gcm(self, app_config):
        """AES-256-GCM from ``cryptography``, not the HMAC keystream v1 and v2
        built here: MITRE's "grow-your-own crypto" (Lucky 13, item 8)."""
        import base64 as _b64

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        secret = totp.new_secret()
        sealed = totp.seal(secret, app_config)
        assert sealed.startswith("v3:")
        blob = _b64.urlsafe_b64decode(sealed[3:])
        opened = AESGCM(totp._aes_key(app_config)).decrypt(blob[:12], blob[12:], totp._AAD)
        assert opened.decode("ascii") == secret

    def test_a_v2_row_still_opens_and_is_marked_for_resealing(self, app_config):
        secret = totp.new_secret()
        old_row = _legacy_row(app_config, totp._SEALED_V2, secret)
        assert totp.unseal(old_row, app_config) == secret
        assert totp.needs_reseal(old_row)
        assert not totp.needs_reseal(totp.seal(secret, app_config))
        assert not totp.needs_reseal("nonsense")

    def test_a_tampered_v3_row_does_not_open(self, app_config):
        import base64 as _b64

        sealed = totp.seal(totp.new_secret(), app_config)
        blob = bytearray(_b64.urlsafe_b64decode(sealed[3:]))
        blob[-1] ^= 1
        assert totp.unseal("v3:" + _b64.urlsafe_b64encode(bytes(blob)).decode(), app_config) is None
        assert totp.unseal("v3:" + _b64.urlsafe_b64encode(b"short").decode(), app_config) is None

    def test_a_v1_row_still_opens(self, app_config):
        """Somebody enrolled before the derivation changed still has a phone
        holding a secret this row is the only copy of. Rejecting it would be a
        lockout dressed up as a security improvement."""
        secret = totp.new_secret()

        # Sealed the way v1 did it, against the same pepper.
        import base64 as _b64

        old_row = _legacy_row(app_config, totp._SEALED_V1, secret)
        assert _b64.urlsafe_b64decode(old_row[3:])[:16] == b"0123456789abcdef"
        assert totp.unseal(old_row, app_config) == secret

    def test_the_two_versions_derive_different_keys(self, app_config):
        """Otherwise the version marker would be decoration."""
        assert totp._keys(app_config, totp._SEALED_V2) != totp._keys(app_config, totp._SEALED_V1)

    def test_a_v1_row_is_not_readable_as_v2(self, app_config):
        """A row relabeled by hand does not open, because the tag is checked
        with the key the label asks for."""
        sealed = _legacy_row(app_config, totp._SEALED_V2, totp.new_secret())
        assert totp.unseal("v1:" + sealed[len("v2:") :], app_config) is None
        assert totp.unseal("v3:" + sealed[len("v2:") :], app_config) is None

    def test_no_pepper_at_all_is_refused_loudly(self, app_config):
        """Storing it in the clear would be the silent alternative, and the
        silent alternative is the one somebody finds out about later."""
        import dataclasses

        naked = dataclasses.replace(
            app_config, security=dataclasses.replace(app_config.security, password_pepper="")
        )
        with pytest.raises(ValueError, match="password_pepper"):
            totp.seal("ABCD", naked)


def _legacy_row(config, version: str, secret: str) -> str:
    """A row sealed the way v1 or v2 did it, before AES-GCM."""
    import base64 as _b64
    import hashlib as _h
    import hmac as _hm

    cipher_key, mac_key = totp._keys(config, version)
    nonce = b"0123456789abcdef"
    raw = secret.encode("ascii")
    body = bytes(
        a ^ b for a, b in zip(raw, totp._keystream(cipher_key, nonce, len(raw)), strict=True)
    )
    tag = _hm.new(mac_key, nonce + body, _h.sha256).digest()[:16]
    return version + _b64.urlsafe_b64encode(nonce + tag + body).decode("ascii")
