"""Time-based one-time passwords (RFC 6238), in the standard library.

Six digits from a shared secret and the clock, which is what every
authenticator app on a phone implements. The algorithm is an HMAC, a truncation
and a modulo -- about fifteen lines -- and writing it here rather than adding
``pyotp`` is a deliberate trade: the Debian package vendors every Python wheel
it ships, so a dependency costs build machinery and bytes on the far side, and
this one would earn neither. The tests check it against RFC 6238's own
published vectors rather than against what this file believes.

**The secret is encrypted at rest**, with a key derived from
``security.password_pepper`` -- the same secret that is HMAC'd into every
password and lives in the configuration file rather than the database. The
property that buys is the one the pepper already buys for passwords: a stolen
database on its own is not enough. Without it, a dump would hand an attacker
both factors at once, which would make the second one decorative.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from .config import Config, get_config

#: Digits in a code. Six is what every authenticator shows.
DIGITS = 6

#: Seconds each code is valid for. Thirty is the RFC's default and what the
#: apps assume; it is not configurable for that reason.
PERIOD = 30

#: How many steps either side of now are accepted.
#:
#: One, which is a thirty-second grace in each direction. Somebody reading six
#: digits off a phone and typing them takes a few seconds, and a server whose
#: clock has drifted slightly should not lock its owner out. Wider would start
#: to matter: each extra step is another window in which a code somebody
#: shoulder-surfed is still good.
DRIFT_STEPS = 1

#: Bytes of entropy in a new secret. Twenty is the RFC 4226 recommendation and
#: encodes to thirty-two base32 characters, which is what the apps expect.
SECRET_BYTES = 20


def new_secret() -> str:
    """A fresh base32 secret, in the alphabet the authenticator apps read."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def code_at(secret: str, when: float, digits: int = DIGITS, period: int = PERIOD) -> str:
    """The code this secret produces at a given moment.

    Separate from :func:`verify` so the test suite can drive it at the exact
    timestamps RFC 6238 publishes vectors for.
    """
    counter = int(when) // period
    key = base64.b32decode(_padded(secret), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    # Dynamic truncation, RFC 4226 section 5.3: the low nibble of the last byte
    # picks where to read four bytes from, and the top bit is masked off so the
    # result is positive on every platform.
    offset = digest[-1] & 0x0F
    chunk = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(chunk % (10**digits)).zfill(digits)


def verify(secret: str, code: str, *, now: float | None = None) -> bool:
    """Whether *code* is good for this secret, allowing for a little drift.

    Compared with :func:`hmac.compare_digest` rather than ``==``: the
    comparison is against a secret-derived value, and a timing difference on
    the first wrong digit is a small oracle but a real one.
    """
    cleaned = "".join(character for character in (code or "") if character.isdigit())
    if len(cleaned) != DIGITS:
        return False
    moment = time.time() if now is None else now
    for step in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
        if hmac.compare_digest(code_at(secret, moment + step * PERIOD), cleaned):
            return True
    return False


def provisioning_uri(secret: str, account: str, issuer: str = "Milsurp Monitor") -> str:
    """The ``otpauth://`` URI an authenticator app reads.

    Rendered as a link rather than a QR code, which would mean a new frontend
    dependency for one screen. On a phone the link opens the authenticator
    directly; elsewhere the secret is shown for typing in.
    """
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}"
        f"&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


def grouped(secret: str, size: int = 4) -> str:
    """The secret in blocks, for reading off a screen and typing into a phone."""
    return " ".join(secret[index : index + size] for index in range(0, len(secret), size))


def _padded(secret: str) -> str:
    """base32 wants a multiple of eight characters; the stored form has no ``=``."""
    cleaned = secret.strip().replace(" ", "").upper()
    return cleaned + "=" * (-len(cleaned) % 8)


# ---------------------------------------------------------------------------
# At rest
# ---------------------------------------------------------------------------
#: How the stored form is marked, so a future scheme can be told from this one
#: without guessing at the ciphertext. That marker is now earning its keep:
#: ``v2:`` is what gets written, ``v1:`` is still read.
_SEALED = "v2:"

#: The original marker. Rows written before the derivation below changed still
#: open, because a scheme change must not lock out everybody who already
#: enrolled -- their phone holds a secret this row is the only copy of.
_SEALED_V1 = "v1:"


def _version_of(stored: str | None) -> str | None:
    """Which scheme wrote this row, or None if nothing here did."""
    if not stored:
        return None
    return next((mark for mark in (_SEALED, _SEALED_V1) if stored.startswith(mark)), None)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """As many bytes as asked for, from HMAC in counter mode.

    A stream cipher built out of the standard library rather than a dependency,
    for the same reason the rest of this module is. It is not AES-GCM and does
    not pretend to be: what it provides is that the secret is not lying in the
    database in the clear, and what stops it being *changed* is the tag below.
    """
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _keys(config: Config, version: str = _SEALED) -> tuple[bytes, bytes]:
    """Separate keys for encrypting and for authenticating.

    Derived from the pepper rather than used directly, and two of them rather
    than one, because a key that both encrypts and signs is the shape most
    likely to be wrong in a way nobody notices.

    **The root is an HMAC, not a bare hash.** v1 computed
    ``sha256(label + pepper)``, which works and is still read below, but
    ``H(label || secret)`` is the construction every guide tells you not to
    reach for: SHA-2 is a Merkle-Damgard hash, so the digest of a prefix lets
    you extend it, and "label then secret" gives no real domain separation
    between one label and another that happens to share a boundary. HMAC is
    built to be keyed and has neither problem, and it is the extract step of
    HKDF (RFC 5869) spelled out -- salt as the key, the secret as the message.

    Nothing here was exploitable: the root never leaves this function, and the
    pepper is a random value of at least ``MIN_SECRET_BYTES``, not a chosen
    password. It is changed because the right construction costs the same.

    CodeQL reads the old line as hashing a password with a fast hash, which is
    the shape of a real mistake -- ``password_pepper`` is in the name, and a
    *user's* password does belong in Argon2 rather than SHA-256. Here it is
    key material, and key material is what HMAC takes.
    """
    pepper = (config.security.password_pepper or "").encode("utf-8")
    if not pepper:
        raise ValueError(
            "security.password_pepper is not set; a TOTP secret cannot be stored safely "
            "without it. Run 'make secrets' and set it in the configuration file."
        )
    if version == _SEALED_V1:
        root = hashlib.sha256(b"milsurp-totp-v1" + pepper).digest()
    else:
        root = hmac.new(b"milsurp-totp-v2", pepper, hashlib.sha256).digest()
    return (
        hmac.new(root, b"encrypt", hashlib.sha256).digest(),
        hmac.new(root, b"authenticate", hashlib.sha256).digest(),
    )


def seal(secret: str, config: Config | None = None) -> str:
    """Encrypt a secret for storage. See the module docstring for why."""
    config = config or get_config()
    cipher_key, mac_key = _keys(config)
    nonce = secrets.token_bytes(16)
    raw = secret.encode("ascii")
    body = bytes(a ^ b for a, b in zip(raw, _keystream(cipher_key, nonce, len(raw)), strict=True))
    tag = hmac.new(mac_key, nonce + body, hashlib.sha256).digest()[:16]
    return _SEALED + base64.urlsafe_b64encode(nonce + tag + body).decode("ascii")


def unseal(stored: str, config: Config | None = None) -> str | None:
    """The secret back, or None when it cannot be trusted.

    None rather than an exception on a bad tag: a row that will not open is a
    second factor that cannot be checked, and the caller's answer to that is to
    refuse the sign-in, not to return a 500 that says the database is odd.
    """
    version = _version_of(stored)
    if version is None:
        return None
    config = config or get_config()
    try:
        blob = base64.urlsafe_b64decode(stored[len(version) :].encode("ascii"))
    except (ValueError, TypeError):
        return None
    if len(blob) < 32:
        return None
    nonce, tag, body = blob[:16], blob[16:32], blob[32:]
    cipher_key, mac_key = _keys(config, version)
    expected = hmac.new(mac_key, nonce + body, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(expected, tag):
        return None
    raw = bytes(a ^ b for a, b in zip(body, _keystream(cipher_key, nonce, len(body)), strict=True))
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return None
