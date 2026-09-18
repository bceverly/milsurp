"""Sending a notification to every browser a reader has signed up.

:mod:`app.services.webpush` knows the two RFCs; this knows the application --
which subscriptions exist, what the message should say, and what to do when a
push service says a subscription is gone.

**An alternative to the email, not a replacement for it.** A watch alert is the
one thing this application sends that is worth interrupting somebody for: they
asked to be told the moment a particular rifle reaches a particular price, and
an email that arrives when they next open their laptop has missed the point. So
push runs alongside, and either channel succeeding is enough for the alert to
count as delivered -- which also means somebody with no SMTP configured at all
can still be told.

**A dead subscription is deleted, not retried.** Browsers rotate them, people
clear site data, phones are replaced. The push service says so with 404 or 410
and there is no second opinion worth having; anything else is counted, and a
subscription that has failed repeatedly goes the same way, because a message
sent into nothing forever is worse than a row nobody misses.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..logsafe import scrub
from ..models import PushSubscription, User, utcnow
from . import webpush

log = logging.getLogger("milsurp.push")

#: Consecutive failures before a subscription is dropped without being told to.
#: Generous, because the alternative to a wrong guess here is silently losing
#: somebody's notifications: three nights of a push service being unreachable
#: is a push service problem, not a dead browser.
MAX_FAILURES = 8

#: How much of a listing's title survives into a notification. A phone lock
#: screen shows about this much and truncates the rest without saying so.
TITLE_CHARS = 80


def configured(config: Config | None = None) -> bool:
    """Whether this deployment can send at all.

    False is a normal state, not an error: an installation that has not
    generated VAPID keys simply does not offer the feature, and every page that
    might have shown a Subscribe button asks this first.
    """
    security = (config or get_config()).security
    return bool(security.vapid_private_key and security.vapid_public_key)


def public_key(config: Config | None = None) -> str | None:
    """The half a browser needs in order to subscribe."""
    security = (config or get_config()).security
    return security.vapid_public_key or None


def subscriptions_for(session: Session, user: User) -> list[PushSubscription]:
    return list(
        session.execute(
            select(PushSubscription)
            .where(PushSubscription.user_id == user.id)
            .order_by(PushSubscription.created_at.desc())
        )
        .scalars()
        .all()
    )


def _subject(config: Config) -> str:
    """Who a push service should complain to.

    RFC 8292 wants a contact and a service that cannot reach anybody may stop
    delivering. Falling back to the configured from-address is better than
    falling back to nothing, and better than inventing a URL that does not
    resolve.
    """
    configured_subject = config.security.vapid_subject.strip()
    if configured_subject:
        return configured_subject
    sender = (config.email.from_address or config.email.username or "").strip()
    return f"mailto:{sender}" if sender else "mailto:admin@localhost"


def send_to_user(
    session: Session,
    user: User,
    payload: dict[str, object],
    config: Config | None = None,
) -> int:
    """Notify every browser this reader has signed up. Returns how many took it.

    Never raises. A notification that can break the thing it is reporting on is
    worse than a notification that does not arrive -- the caller is a scan or a
    scheduler tick, and neither should end because a push service had a bad
    minute.
    """
    config = config or get_config()
    if not configured(config):
        return 0
    try:
        keys = webpush.load_keys(
            config.security.vapid_private_key, config.security.vapid_public_key
        )
    except webpush.PushError as exc:
        log.warning("Push is configured but the VAPID keys are unusable: %s", exc)
        return 0

    subject = _subject(config)
    delivered = 0
    dead: list[PushSubscription] = []
    for subscription in subscriptions_for(session, user):
        try:
            webpush.send(
                subscription.endpoint,
                subscription.p256dh,
                subscription.auth,
                payload,
                keys=keys,
                subject=subject,
            )
        except webpush.PushError as exc:
            if exc.gone:
                dead.append(subscription)
                continue
            subscription.failures += 1
            if subscription.failures >= MAX_FAILURES:
                dead.append(subscription)
            # The endpoint is a capability and never goes in a log. The
            # subscription's row id says which one this was, and is not.
            log.warning("Push to subscription %s failed: %s", subscription.id, exc)
            continue
        except Exception:
            # Deliberately broad, and the docstring's promise. Something
            # unforeseen in a push service's response must not end a scheduler
            # tick -- the alert this was reporting on is more important than
            # the report. Counted as an ordinary failure so a permanently
            # broken subscription still ages out.
            subscription.failures += 1
            if subscription.failures >= MAX_FAILURES:
                dead.append(subscription)
            log.warning("Push to subscription %s raised", subscription.id, exc_info=True)
            continue
        subscription.failures = 0
        subscription.last_used_at = utcnow()
        delivered += 1

    for subscription in dead:
        log.info("Dropping push subscription %s: the browser is gone.", subscription.id)
        session.delete(subscription)
    return delivered


def watch_alert_payload(updates: list) -> dict[str, object]:
    """What a watch alert says on a lock screen.

    One line if one listing moved, a count if several: a notification is read
    in a glance and a list of five titles is a list nobody finishes. The link
    goes to the item when there is one and to the watchlist when there are
    several, so the tap lands where the next decision is.
    """
    first = updates[0]
    item = first.item
    title = scrub(item.title or "", limit=TITLE_CHARS)
    if len(updates) == 1:
        price = f"${item.current_price:,.0f}" if item.current_price is not None else "no price"
        body = f"{title} — now {price}"
        url = f"/items/{item.id}"
    else:
        body = f"{title} and {len(updates) - 1} more reached what you asked for."
        url = "/watchlist"
    return {"title": "A watched listing moved", "body": body, "url": url}
