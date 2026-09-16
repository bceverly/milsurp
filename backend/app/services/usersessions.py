"""Where somebody is signed in, and how to end one of those places.

The access token was stateless, which bought a great deal and cost one thing:
there was no way to end a single sign-in. ``User.token_version`` retires every
token at once -- right for a password change, useless for closing the laptop
left at work without also signing yourself out of your phone. And nothing could
answer "where am I signed in?" at all, because nothing was written down.

A login now writes a row and the token carries its id. Everything here is about
keeping that row honest without making it expensive.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logsafe import scrub
from ..models import User, UserSession, as_utc, utcnow

#: How much of a User-Agent to keep.
#:
#: Enough to tell a phone from a laptop, which is all the list is for. It is
#: somebody else's string, so it is scrubbed as well as cut -- a newline in a
#: header is not going to forge anything here, but the rule is that attacker
#: text is cleaned at the door rather than wherever it is eventually shown.
AGENT_CHARS = 200

#: How stale ``last_seen_at`` may get before it is written again.
#:
#: Without this every authenticated request would issue an UPDATE, which turns
#: a read-only page into a write on every poll and makes the watchlist poller
#: the busiest writer in the application. A minute is finer than the list can
#: usefully show.
TOUCH_AFTER = timedelta(minutes=1)


def begin(
    session: Session,
    user: User,
    *,
    expires_at,
    user_agent: str | None,
    ip_address: str | None,
) -> UserSession:
    """Record a sign-in. The caller puts the returned id into the token."""
    row = UserSession(
        user_id=user.id,
        user_agent=scrub(user_agent or "", limit=AGENT_CHARS) or None,
        ip_address=scrub(ip_address or "", limit=64) or None,
        expires_at=expires_at,
        last_seen_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def live_for(session: Session, user: User) -> list[UserSession]:
    """Sessions this account could still be used from, newest first.

    Expired ones are left out rather than deleted here: a list is a read, and a
    read that quietly writes is a surprise. :func:`prune` does the deleting.
    """
    rows = (
        session.execute(
            select(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .order_by(UserSession.created_at.desc())
        )
        .scalars()
        .all()
    )
    # Expiry compared in Python rather than in SQL, which is the convention
    # here: the columns are naive UTC and binding an aware datetime into a
    # comparison behaves differently on the two engines this runs on.
    now = utcnow()
    return [row for row in rows if (as_utc(row.expires_at) or now) > now]


def touch(row: UserSession) -> None:
    """Note that this session was used, but not on every single request.

    No Session parameter: the row came out of one and is still attached to it,
    so changing the attribute is the whole operation.
    """
    now = utcnow()
    seen = as_utc(row.last_seen_at)
    if seen is None or (now - seen) > TOUCH_AFTER:
        row.last_seen_at = now


def revoke(session: Session, user: User, session_id: int) -> bool:
    """End one sign-in. True if there was one to end.

    Scoped to the owner: the id comes from a URL, and a session id is a small
    integer, so without the ``user_id`` check anybody could sign anybody else
    out by guessing.
    """
    row = session.get(UserSession, session_id)
    if row is None or row.user_id != user.id or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    return True


def revoke_all(session: Session, user: User, *, except_id: int | None = None) -> int:
    """End every other sign-in. Returns how many were ended.

    ``except_id`` keeps the one asking, which is what "sign out everywhere
    else" means -- signing yourself out as a side effect of securing your
    account reads as the button having gone wrong.
    """
    ended = 0
    for row in live_for(session, user):
        if except_id is not None and row.id == except_id:
            continue
        row.revoked_at = utcnow()
        ended += 1
    return ended


def is_live(session: Session, session_id: int | None) -> bool:
    """Whether a token's session is still good.

    ``None`` means the token carries no session -- one minted by a script or
    issued before this existed. Those stay valid: they were valid when they
    were handed out, and ``token_version`` is still there to retire them.
    """
    if session_id is None:
        return True
    row = session.get(UserSession, session_id)
    return row is not None and row.is_live


def prune(session: Session, *, before=None) -> int:
    """Delete sessions that expired. Returns how many went.

    Kept for a while after expiry rather than deleted the moment they lapse,
    so the list can still show "this phone, last week" -- a session ending is
    part of the history somebody may want to see.
    """
    cutoff = before or (utcnow() - timedelta(days=30))
    rows = session.execute(select(UserSession)).scalars().all()
    stale = [row for row in rows if (as_utc(row.expires_at) or cutoff) < cutoff]
    for row in stale:
        session.delete(row)
    return len(stale)
