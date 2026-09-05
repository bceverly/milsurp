"""Password hashing and JWT issuance.

Passwords are hashed with **Argon2id**, the winner of the Password Hashing
Competition and the algorithm OWASP recommends first for new applications. Every
hash embeds its own cryptographically random 16-byte salt, so two users with the
same password get different hashes without any application-level bookkeeping.

The ``password_pepper`` from the config file is HMAC'd with the password before
hashing. Unlike a salt, the pepper is *not* stored in the database, so an
attacker who exfiltrates only the database cannot mount an offline attack. It is
a defense-in-depth measure layered on top of Argon2, not a replacement for it.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import Config, get_config

_hasher_cache: tuple[tuple[int, int, int], PasswordHasher] | None = None


def _hasher(config: Config) -> PasswordHasher:
    """Argon2id hasher built from the configured cost parameters."""
    global _hasher_cache
    params = (
        config.security.argon2_time_cost,
        config.security.argon2_memory_cost,
        config.security.argon2_parallelism,
    )
    if _hasher_cache is None or _hasher_cache[0] != params:
        _hasher_cache = (
            params,
            PasswordHasher(
                time_cost=params[0],
                memory_cost=params[1],
                parallelism=params[2],
                hash_len=32,
                salt_len=16,
            ),
        )
    return _hasher_cache[1]


def _peppered(password: str, config: Config) -> str:
    """Mix the server-side pepper into the password.

    HMAC rather than concatenation: it is a proper keyed construction, and it
    normalizes the input to a fixed length so Argon2's own 4 GiB input limit can
    never be reached by a pathologically long password.
    """
    pepper = config.security.password_pepper
    if not pepper:
        return password
    return hmac.new(pepper.encode("utf-8"), password.encode("utf-8"), sha256).hexdigest()


def hash_password(password: str, config: Config | None = None) -> str:
    config = config or get_config()
    return _hasher(config).hash(_peppered(password, config))


def verify_password(password: str, password_hash: str, config: Config | None = None) -> bool:
    config = config or get_config()
    try:
        return _hasher(config).verify(password_hash, _peppered(password, config))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str, config: Config | None = None) -> bool:
    """True when a stored hash predates the current cost parameters."""
    config = config or get_config()
    try:
        return _hasher(config).check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


class PasswordPolicyError(ValueError):
    """Raised when a proposed password is too weak to accept."""


def _join(parts: list[str]) -> str:
    """ "a", "a and b", "a, b and c" — for readable error messages."""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


#: Fallback when no configuration is available (a direct call in a test, say).
DEFAULT_MIN_PASSWORD_LENGTH = 12


#: Everything that is neither a letter nor a digit counts as "special". A fixed
#: punctuation list would silently reject perfectly good characters.
SPECIAL_CHARACTERS = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "


def min_password_length(config: Config | None = None) -> int:
    """The configured minimum, read fresh so a restart picks up a change."""
    config = config or get_config()
    return max(1, config.security.min_password_length)


def password_requirements(config: Config | None = None) -> list[str]:
    """The active rules, in the order they are checked.

    Derived from the config toggles: a rule that is switched off contributes
    nothing, so the policy text and the enforcement can never disagree.
    """
    config = config or get_config()
    rules = [f"at least {min_password_length(config)} characters"]
    if config.security.require_uppercase:
        rules.append("an uppercase letter")
    if config.security.require_lowercase:
        rules.append("a lowercase letter")
    if config.security.require_numeric:
        rules.append("a number")
    if config.security.require_special:
        rules.append("a special character")
    return rules


def validate_password(password: str, config: Config | None = None) -> None:
    """Reject passwords that are trivially weak.

    Length is the dominant factor in resisting offline attack, so the minimum
    (``security.min_password_length``) does most of the work. The four
    character-class rules are applied only when switched on, so the policy in
    force is derived from the configuration rather than hard-coded here.
    """
    config = config or get_config()
    minimum = min_password_length(config)
    if len(password) < minimum:
        raise PasswordPolicyError(f"Password must be at least {minimum} characters long.")
    if len(password) > 1024:
        raise PasswordPolicyError("Password must be 1024 characters or fewer.")
    if password.strip() != password:
        raise PasswordPolicyError("Password must not start or end with whitespace.")

    # Collected rather than raised one at a time, so someone missing two
    # classes is told both at once instead of discovering them in sequence.
    missing: list[str] = []
    if config.security.require_uppercase and not any(c.isupper() for c in password):
        missing.append("an uppercase letter")
    if config.security.require_lowercase and not any(c.islower() for c in password):
        missing.append("a lowercase letter")
    if config.security.require_numeric and not any(c.isdigit() for c in password):
        missing.append("a number")
    if config.security.require_special and not any(c in SPECIAL_CHARACTERS for c in password):
        missing.append("a special character")
    if missing:
        raise PasswordPolicyError(f"Password must contain {_join(missing)}.")

    lowered = password.lower()
    for weak in ("password", "changeme", "milsurp", "12345678", "qwerty"):
        if weak in lowered:
            raise PasswordPolicyError(
                "Password contains a common word or sequence; choose something less guessable."
            )


# ---------------------------------------------------------------------------
# JSON Web Tokens
# ---------------------------------------------------------------------------
class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or not trusted."""


def create_access_token(
    user_id: int,
    role: str,
    token_version: int,
    config: Config | None = None,
    expires_minutes: int | None = None,
) -> tuple[str, datetime]:
    """Issue a signed access token. Returns ``(token, expires_at_utc)``."""
    config = config or get_config()
    if not config.security.jwt_secret:
        raise TokenError(
            "security.jwt_secret is not set in the configuration file; "
            "run 'make secrets' to generate one."
        )
    minutes = expires_minutes or config.security.access_token_minutes
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        # Lets a password change invalidate every token already handed out.
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": "milsurp",
    }
    token = jwt.encode(payload, config.security.jwt_secret, algorithm=config.security.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str, config: Config | None = None) -> dict[str, Any]:
    config = config or get_config()
    if not config.security.jwt_secret:
        raise TokenError("security.jwt_secret is not set in the configuration file.")
    try:
        return jwt.decode(
            token,
            config.security.jwt_secret,
            algorithms=[config.security.jwt_algorithm],
            issuer="milsurp",
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session has expired; please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid authentication token.") from exc
