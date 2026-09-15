"""Turning two-factor on, checking it, and the way back in when a phone is gone.

The admin sign-in is reachable from the internet, and a password was the only
thing in front of it. This is the second factor; :mod:`app.totp` is the
arithmetic underneath.

**Enrolment is two steps, and the gap between them is the point.** Starting
issues a secret and shows it; only a code typed back from the phone turns the
flag on. Collapsing that into one step means a secret mistyped into an
authenticator -- or a tab closed halfway -- locks the account out of an
application whose whole recovery story is "ask the person with shell access".

**Recovery codes are password-equivalent**, so they are hashed with the same
Argon2 the passwords use. One of them alone is the entire second factor, and
storing them in the clear would undo most of what the factor is for.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import totp
from ..config import Config, get_config
from ..models import RecoveryCode, User, utcnow
from ..security import hash_password, verify_password

#: How many recovery codes are issued. Ten is the usual number: enough that
#: losing a couple does not matter, few enough to write on one line of paper.
RECOVERY_CODES = 10

#: Characters in each. Crockford-ish: no I, O, 0 or 1, because these get
#: written down by hand and read back at the moment somebody is already locked
#: out and unhappy.
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_CODE_LENGTH = 10


def is_enabled(user: User) -> bool:
    return bool(user.totp_enabled and user.totp_secret)


def begin_enrolment(user: User, config: Config | None = None) -> tuple[str, str]:
    """Issue a secret and return ``(secret, otpauth_uri)``.

    Stored immediately but **not** enabled: the secret has to exist for the
    confirming code to be checked against, and the flag stays off until it is.
    Starting again simply replaces it, which is what somebody who closed the
    tab will do.
    """
    config = config or get_config()
    secret = totp.new_secret()
    user.totp_secret = totp.seal(secret, config)
    user.totp_enabled = False
    user.totp_confirmed_at = None
    return secret, totp.provisioning_uri(secret, user.username)


def confirm_enrolment(
    session: Session, user: User, code: str, config: Config | None = None
) -> list[str] | None:
    """Turn it on if *code* is right. Returns the recovery codes, once.

    None when the code is wrong, and the flag is left alone -- a mistyped digit
    during enrolment is the ordinary case and must not clear the secret.

    The codes are returned in the clear here and nowhere else. They are shown
    on the screen that asked for them and stored only as hashes; there is
    deliberately no way to see them again, because a list of second factors
    retrievable by anybody already signed in is not a second factor.
    """
    config = config or get_config()
    secret = totp.unseal(user.totp_secret or "", config)
    if secret is None or not totp.verify(secret, code):
        return None

    user.totp_enabled = True
    user.totp_confirmed_at = utcnow()
    return _issue_recovery_codes(session, user, config)


def disable(session: Session, user: User) -> None:
    """Turn it off and forget everything about it.

    The secret goes as well as the flag. Leaving a stale secret behind means
    turning two-factor back on later silently re-enables a code somebody's old
    phone can still produce.
    """
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_confirmed_at = None
    _clear_recovery_codes(session, user)


def check(session: Session, user: User, code: str, config: Config | None = None) -> bool:
    """Whether this code gets the user in: a TOTP code, or a recovery code.

    Both are accepted at the same prompt rather than behind a "use a recovery
    code instead" link. Somebody reaching for a recovery code has already lost
    their phone; making them find a second link first is a small cruelty, and
    the two are told apart by their shape.
    """
    config = config or get_config()
    cleaned = (code or "").strip()
    if not cleaned:
        return False

    secret = totp.unseal(user.totp_secret or "", config)
    if secret is not None and totp.verify(secret, cleaned):
        return True
    return _spend_recovery_code(session, user, cleaned, config)


def recovery_codes_left(session: Session, user: User) -> int:
    return len(
        session.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
            )
        )
        .scalars()
        .all()
    )


def _issue_recovery_codes(session: Session, user: User, config: Config) -> list[str]:
    _clear_recovery_codes(session, user)
    codes = [_new_code() for _ in range(RECOVERY_CODES)]
    for code in codes:
        session.add(
            RecoveryCode(user_id=user.id, code_hash=hash_password(_normalise(code), config))
        )
    return codes


def _spend_recovery_code(session: Session, user: User, code: str, config: Config) -> bool:
    """Check a recovery code and, if it is good, use it up.

    Every unused code is compared rather than looked up, because they are
    hashed with a per-row salt and there is nothing to look up by. Ten Argon2
    verifications is deliberate work; this path runs when somebody has lost
    their phone, not on every sign-in.
    """
    candidate = _normalise(code)
    if len(candidate) != _CODE_LENGTH:
        return False
    rows = (
        session.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if verify_password(candidate, row.code_hash, config):
            row.used_at = utcnow()
            return True
    return False


def _clear_recovery_codes(session: Session, user: User) -> None:
    for row in (
        session.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id)).scalars().all()
    ):
        session.delete(row)


def _new_code() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
    # Hyphenated for reading aloud and writing down; the hyphen is not stored.
    return f"{body[:5]}-{body[5:]}"


def _normalise(code: str) -> str:
    """The comparable form: no spaces, no hyphens, one case.

    These are written on paper and typed back by somebody having a bad day.
    """
    return "".join(character for character in (code or "").upper() if character in _ALPHABET)


def last_used(session: Session, user: User) -> datetime | None:
    rows = (
        session.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_not(None)
            )
        )
        .scalars()
        .all()
    )
    return max((row.used_at for row in rows if row.used_at), default=None)
