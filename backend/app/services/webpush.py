"""Web Push: RFC 8291 encryption and RFC 8292 identification, by hand.

A push message is not a request to a browser. It is an encrypted blob posted to
whatever push service that browser's vendor runs -- Mozilla's, Google's,
Apple's -- which holds it and wakes the service worker when the device next has
a network. The service never sees the contents: the payload is encrypted to a
key pair the *browser* generated, and this server only ever holds the public
half.

**Written against the specifications rather than added as a dependency**, which
is the same call the two-factor code made against RFC 6238 and for the same
reasons: the Debian package vendors every dependency into its own virtualenv,
`pywebpush` brings a transitive tree for work that is a hundred lines of
`cryptography` calls, and the parts that are subtle here -- the exact info
strings, the record delimiter, the JOSE signature encoding -- are subtle whether
somebody else writes them or not. What is *not* hand-rolled is the primitives:
P-256, HKDF, AES-GCM and ECDSA all come from `cryptography`.

Two independent pieces of cryptography, and it is worth keeping them apart:

**RFC 8291 -- the payload.** An ephemeral P-256 key pair is generated per
message and ECDH'd with the subscription's public key. The shared secret and
the subscription's auth secret are run through HKDF to produce a content
encryption key and a nonce, and the plaintext is sealed with AES-128-GCM. The
ephemeral public key travels in the body, so the browser can repeat the
exchange; the ephemeral private key is discarded here and never stored, which
is what makes a stolen database unable to decrypt anything ever sent.

**RFC 8292 -- who is asking.** A short-lived ES256 JWT, signed with the
server's VAPID key and addressed to the push service's own origin, says which
application server is sending and how to complain about it. It is not
authentication of the *user*: the endpoint URL is the only capability, which is
why the endpoint is the secret in this design and is treated as one.

**A subscription is a transient thing.** Browsers rotate them, users clear site
data, devices are replaced. The push service says so with 404 or 410, and the
only correct response is to forget the subscription rather than retry it --
see :func:`send`, which reports that case separately for exactly this reason.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import utils as asym_utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = logging.getLogger("milsurp.webpush")

#: The record size in the aes128gcm header. One record is enough for anything
#: this application sends -- the payload cap below is far smaller -- and a
#: single record means no continuation logic to get wrong.
RECORD_SIZE = 4096

#: What a push service will accept, and the reason the message is a summary
#: with a link rather than the listing itself. 4KB is the floor every service
#: guarantees; going over is a 413 from some of them and silence from others.
MAX_PAYLOAD = 3000

#: How long a message may wait for a device that is offline. Four hours: a
#: price alert that arrives a day late is worse than one that never arrives,
#: because the reader acts on it.
DEFAULT_TTL = 4 * 60 * 60

#: How long a VAPID assertion is good for. Twelve hours is the ceiling RFC 8292
#: sets; every service rejects more.
VAPID_LIFETIME = 12 * 60 * 60


class PushError(Exception):
    """The message could not be sent. Carries whether it is worth retrying."""

    def __init__(self, message: str, *, gone: bool = False) -> None:
        super().__init__(message)
        #: The subscription is dead and must be forgotten rather than retried.
        self.gone = gone


def b64(data: bytes) -> str:
    """Unpadded base64url, which is what every field in these two RFCs uses."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64(value: str) -> bytes:
    """The inverse, tolerant of the padding a browser may or may not include."""
    text = value.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class Keys:
    """A VAPID key pair, as the configuration file holds it."""

    private_key: ec.EllipticCurvePrivateKey
    public_bytes: bytes

    @property
    def public_key(self) -> str:
        """The value the browser needs, and the only half that leaves here."""
        return b64(self.public_bytes)


def generate_keys() -> tuple[str, str]:
    """A fresh VAPID pair as (private, public), both base64url.

    The private half is stored as the raw 32-byte scalar rather than as PEM: it
    goes into the same YAML file as the other secrets, one line each, and a PEM
    block in a config file is a multi-line value somebody's editor will reflow.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64(private), b64(public)


def load_keys(private: str, public: str) -> Keys:
    """Rebuild the pair from what the configuration holds.

    The public half is recomputed from the private one and *checked* against
    what was configured. A mismatched pair is the failure this most wants to
    catch early: every message would be signed with one identity and announce
    another, and push services reject that in ways that read like a network
    problem.
    """
    key = ec.derive_private_key(int.from_bytes(unb64(private), "big"), ec.SECP256R1())
    derived = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    if public and unb64(public) != derived:
        raise PushError(
            "The configured VAPID public key does not belong to the private key. "
            "Re-run `milsurp secrets --force` to make a matching pair, and expect "
            "every existing subscription to stop working: a browser subscribes to "
            "one application server and will not accept another."
        )
    return Keys(private_key=key, public_bytes=derived)


def _vapid_header(keys: Keys, endpoint: str, subject: str) -> str:
    """The Authorization header for one endpoint (RFC 8292).

    The audience is the push service's **origin**, not the endpoint: the same
    assertion covers every subscription at that service, and including the path
    would leak which endpoints exist to anyone who saw the token.
    """
    parts = urlsplit(endpoint)
    header = {"typ": "JWT", "alg": "ES256"}
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(time.time()) + VAPID_LIFETIME,
        "sub": subject,
    }
    signing_input = b".".join(
        b64(json.dumps(part, separators=(",", ":")).encode()).encode() for part in (header, claims)
    )
    der = keys.private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # JOSE wants the raw r||s pair, fixed width. `cryptography` signs to DER,
    # which is variable-length and would be rejected without a word of
    # explanation by every push service.
    r, s = asym_utils.decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = signing_input.decode() + "." + b64(signature)
    return f"vapid t={token}, k={keys.public_key}"


def encrypt(payload: bytes, subscriber_public: bytes, auth_secret: bytes) -> bytes:
    """Seal *payload* for one subscription (RFC 8291 with RFC 8188 framing).

    The info strings are exact and load-bearing. ``WebPush: info\\x00`` is what
    binds the derived key to *this* pair of public keys, so a message sealed for
    one subscription cannot be replayed at another; the two
    ``Content-Encoding:`` strings are what RFC 8188 specifies and are not
    interchangeable.
    """
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = ephemeral.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), subscriber_public),
    )

    # First HKDF: the auth secret is the salt, and the key material is bound to
    # both public keys so the result cannot be reused elsewhere.
    #
    # Pulled out to a name so the suppression below has a line of its own that
    # the formatter will not move. semgrep's `cryptography-insecure-random`
    # wants every HKDF salt to be freshly random; this one is the *browser's*
    # auth secret, which RFC 8291 section 3.3 names as the salt, and a random
    # value here would derive a key the browser cannot.
    binding = (
        # nosemgrep: python.cryptography.cryptography-insecure-random.cryptography-insecure-random  # noqa: ERA001
        b"WebPush: info\x00"
        + subscriber_public
        + ephemeral_public
    )
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=binding,
    ).derive(shared)

    salt = secrets.token_bytes(16)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=16,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    # Both the content key and the nonce come from the same extract over
    # (salt, ikm) and differ only in the info string -- which is what `HKDF`
    # does internally, so two calls with one salt is the whole of RFC 8291
    # section 3.3 rather than an approximation of it.
    nonce = HKDF(
        algorithm=hashes.SHA256(),
        length=12,
        salt=salt,
        # Same rule, same answer: this salt *is* freshly random -- it is the
        # secrets.token_bytes(16) above, named because the one value has to
        # reach the key, the nonce and the header alike.
        # nosemgrep: python.cryptography.cryptography-insecure-random.cryptography-insecure-random  # noqa: ERA001
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    # 0x02 marks the last record. A 0x01 here would have the browser wait for a
    # continuation that never comes, and the notification would simply not fire.
    sealed = AESGCM(key).encrypt(nonce, payload + b"\x02", None)
    header = (
        salt
        + RECORD_SIZE.to_bytes(4, "big")
        + len(ephemeral_public).to_bytes(1, "big")
        + ephemeral_public
    )
    return header + sealed


def send(
    endpoint: str,
    subscriber_public: str,
    auth_secret: str,
    payload: dict[str, object],
    *,
    keys: Keys,
    subject: str,
    ttl: int = DEFAULT_TTL,
    timeout: float = 10.0,
) -> None:
    """Post one message. Raises :class:`PushError`, with ``gone`` set when the
    subscription should be deleted rather than retried."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    if len(body) > MAX_PAYLOAD:
        raise PushError(f"payload is {len(body)} bytes, over the {MAX_PAYLOAD} limit")

    sealed = encrypt(body, unb64(subscriber_public), unb64(auth_secret))
    try:
        response = requests.post(
            endpoint,
            data=sealed,
            headers={
                "Authorization": _vapid_header(keys, endpoint, subject),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(ttl),
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PushError(f"could not reach the push service: {exc}") from exc

    # 404 and 410 are the push service saying this subscription no longer
    # exists -- the browser rotated it, the user cleared site data, the device
    # is gone. Anything else may be transient.
    if response.status_code in (404, 410):
        raise PushError(f"subscription is gone ({response.status_code})", gone=True)
    if response.status_code >= 400:
        detail = response.text.strip()[:200]
        raise PushError(f"push service refused it ({response.status_code}): {detail}")
