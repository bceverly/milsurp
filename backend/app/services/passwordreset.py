"""One-time password reset links, issued by an administrator.

Somebody cannot get in, and the admin's only tool was to set a new password and
tell them what it is -- over whatever channel was to hand, after which the admin
knows it and it has been said out loud. This replaces that: the admin presses a
button, the person gets a link, and the password they end up with is one only
they have seen.

**The issuing side stays authenticated.** The roadmap parked self-service reset
because it needs an endpoint that hands tokens to anybody who names an address;
an admin-initiated link does not, and only redeeming is open.

Four properties do the work, and each closes a way this kind of link usually
goes wrong:

* **single use** -- a link in a mailbox is a live credential until it is spent;
* **short lived** -- an hour, because the admin has just told them to expect it;
* **superseded** -- issuing a new one kills the outstanding ones, so a resend
  does not leave two live credentials in a mailbox;
* **hashed at rest** -- while it is live the token *is* the password, so a
  stolen database must not contain a working one.

**It does not bypass two-factor.** Redeeming sets the password and nothing
else; an account with an authenticator still needs it at sign-in. A reset link
that skipped the second factor would make a compromised mailbox enough to
defeat it, which is most of what the second factor is for.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..models import PasswordResetToken, User, as_utc, utcnow
from ..security import hash_password, verify_password

#: How long a link is good for.
#:
#: An hour. The admin has just told somebody to expect it, so this is not a
#: link anybody is waiting days on -- and every minute it is alive is a minute
#: a mailbox holds a working credential. A resend costs one click.
LIFETIME_MINUTES = 60

#: Bytes of entropy in the token. Thirty-two, which is not guessable and is why
#: the redeeming endpoint can be open without a throttle standing in front of
#: it doing the real work.
TOKEN_BYTES = 32


@dataclass(frozen=True)
class Issued:
    """A freshly minted link. The clear token exists only here and in the mail."""

    token: str
    url: str
    expires_at: datetime


def issue(
    session: Session, user: User, issued_by: User | None, config: Config | None = None
) -> Issued:
    """Mint a link for *user*, invalidating any outstanding one.

    Superseding matters: an admin who presses the button twice -- because the
    first mail did not arrive, which is the ordinary reason -- would otherwise
    leave two live credentials in a mailbox, and the older one is the one
    nobody is watching for.
    """
    config = config or get_config()
    _invalidate(session, user)

    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = utcnow() + timedelta(minutes=LIFETIME_MINUTES)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_password(token, config),
            expires_at=expires_at,
            issued_by_id=issued_by.id if issued_by else None,
        )
    )
    base = (config.server.public_url or "").rstrip("/")
    return Issued(token=token, url=f"{base}/reset/{token}", expires_at=expires_at)


def find_valid(session: Session, token: str, config: Config | None = None) -> User | None:
    """The account this token belongs to, or None.

    Every live row is compared rather than looked up: the hashes carry a
    per-row salt, so there is nothing to index by. The set is small -- expired
    and spent rows are excluded, and issuing supersedes -- and this path runs
    when somebody clicks a link, not on every request.
    """
    config = config or get_config()
    if not token:
        return None
    for row in _live(session):
        if verify_password(token, row.token_hash, config):
            return session.get(User, row.user_id)
    return None


def redeem(
    session: Session, token: str, new_password: str, config: Config | None = None
) -> User | None:
    """Set the password and spend the token. None when it is not good.

    The password is hashed by the caller's rules -- see security.validate_password,
    which the endpoint applies first -- and every session already open for the
    account is signed out: a reset is usually somebody saying they have lost
    control of something, and leaving live tokens alone would make this a
    smaller fix than it appears.

    Two-factor is deliberately left alone. An account with an authenticator
    still needs it at the next sign-in.
    """
    config = config or get_config()
    if not token:
        return None
    for row in _live(session):
        if not verify_password(token, row.token_hash, config):
            continue
        user = session.get(User, row.user_id)
        if user is None:
            return None
        user.password_hash = hash_password(new_password, config)
        user.token_version += 1
        row.used_at = utcnow()
        # Anything else outstanding for this account goes too: the password has
        # changed, so a second link would set it again from an older mail.
        _invalidate(session, user)
        return user
    return None


def _live(session: Session) -> list[PasswordResetToken]:
    now = utcnow()
    rows = (
        session.execute(select(PasswordResetToken).where(PasswordResetToken.used_at.is_(None)))
        .scalars()
        .all()
    )
    return [row for row in rows if (as_utc(row.expires_at) or now) > now]


def _invalidate(session: Session, user: User) -> None:
    for row in (
        session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
            )
        )
        .scalars()
        .all()
    ):
        session.delete(row)
