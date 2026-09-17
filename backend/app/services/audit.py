"""A record of what administrators did, kept where it can be read back.

Failed sign-ins were already logged. What happened *after* somebody got in was
not: creating an account, changing a role, disabling a site are each a decision
somebody made, and a log file that scrolls and rotates is not where you go to
find out who made it.

**Three rules, and each is the difference between a log and a story.**

*Append-only.* Nothing here updates or deletes a row. A log somebody can edit
answers a different question from the one it appears to answer.

*The actor is kept twice.* An id and a name. The foreign key is ``SET NULL``,
so deleting an account cannot erase what it did, and the name survives beside
it -- the row most worth reading is usually the one written by somebody who is
no longer here.

*Recording must never break the thing it records.* An audit write that raised
would turn "the log is full" into "nobody can create a user". So :func:`record`
swallows its own failures and says so in the application log instead. That is a
real trade -- a lost audit row is a real loss -- and it is the right way round:
the alternative makes the log a single point of failure for the features it
watches.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logsafe import scrub
from ..models import AuditEvent, User

log = logging.getLogger("milsurp.audit")

#: Actions, named as past-tense facts rather than commands.
#:
#: One of these trips both ruff's and bandit's hardcoded-password checks, on
#: the word "password" in a string. It is the name of a thing that happened,
#: and it is written into a log on purpose. A log says what
#: happened; a command is what somebody asked for, which is not the same thing
#: when the answer was no.
USER_CREATED = "user.created"
USER_UPDATED = "user.updated"
USER_DELETED = "user.deleted"
USER_ROLE_CHANGED = "user.role_changed"
#: Named for what it is -- a link was mailed -- rather than for the thing the
#: link eventually lets somebody change.
#:
#: It was named for the password rather than for the link, and carried
#: suppressions for both ruff's S105 and bandit's B105, because each reads a
#: constant whose name contains PASSWORD as a hardcoded credential. CodeQL then
#: read the same constant the same way and reported *clear-text logging of
#: sensitive information* against the `log.exception` below, which logs the
#: action name when an audit write fails.
#:
#: Three tools, one false positive, and no password within reach of any of
#: them: the value is the name of something that happened. Renaming it is what
#: the two suppressions were standing in for, and with the name changed both
#: linters fall silent on their own.
USER_RESET_LINK_SENT = "user.reset_link_sent"
COUNTRY_CHANGED = "country.changed"
ARMORY_EDITED = "armory.edited"
ARMORY_DELETED = "armory.deleted"
ARMORY_REVERTED = "armory.reverted"
DESIGNATION_CHANGED = "caliber_designation.changed"
CLASSIFIER_KEYWORD_CHANGED = "classifier_keyword.changed"
SITE_ENABLED = "site.enabled"
SITE_DISABLED = "site.disabled"
ITEM_OVERRIDDEN = "item.overridden"
ITEM_OVERRIDE_CLEARED = "item.override_cleared"
SESSION_REVOKED = "session.revoked"
SESSIONS_REVOKED = "session.revoked_all"

#: Caps matching the columns, so a long value is trimmed here rather than
#: rejected by the database on write -- which would be the failure this module
#: exists to avoid.
DETAIL_CHARS = 500
LABEL_CHARS = 255


def record(
    session: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str | None = None,
    target_id: object = None,
    target_label: str | None = None,
    detail: str | None = None,
    ip_address: str | None = None,
    before: dict[str, object] | None = None,
) -> AuditEvent | None:
    """Write one event. Returns None if it could not be written.

    Never raises. See the module docstring: the log must not be able to break
    the operations it is watching.
    """
    try:
        event = AuditEvent(
            actor_id=actor.id if actor else None,
            actor_name=actor.username if actor else None,
            action=action,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id)[:64],
            target_label=scrub(target_label or "", limit=LABEL_CHARS) or None,
            detail=scrub(detail or "", limit=DETAIL_CHARS) or None,
            ip_address=scrub(ip_address or "", limit=64) or None,
            # Not scrubbed and not truncated: it is JSON that has to parse when
            # it is read back, and half a document restores nothing. What goes
            # in comes from the endpoint rather than from a request body.
            before_state=json.dumps(before, default=str) if before is not None else None,
        )
        session.add(event)
        session.flush()
    except Exception:
        # Deliberately broad, and deliberately not re-raised.
        log.exception("Could not record audit event %s", action)
        return None
    else:
        return event


def recent(session: Session, *, limit: int = 100, action: str | None = None) -> list[AuditEvent]:
    """The newest events, most recent first."""
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    if action:
        query = query.where(AuditEvent.action == action)
    return list(session.execute(query.limit(limit)).scalars().all())


def actions(session: Session) -> list[str]:
    """Which actions actually appear, for a filter that offers only those.

    Read from the data rather than from the constants above: a filter listing
    actions nothing has ever done is a filter that mostly returns nothing.
    """
    rows = session.execute(select(AuditEvent.action).distinct().order_by(AuditEvent.action))
    return [row[0] for row in rows]
