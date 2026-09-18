"""Subscribing a browser to notifications, and unsubscribing it again.

The endpoint a browser hands over is the whole capability -- anyone holding it
can notify that device -- so it is accepted, stored and never given back. The
list a reader sees describes their own devices by what the browser called
itself and when it was last used, and says nothing that would let one be
impersonated.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from ..deps import AppConfig, CurrentUser, DbSession
from ..logsafe import scrub
from ..models import PushSubscription
from ..schemas import PushStatusOut, PushSubscribeIn, PushSubscriptionOut
from ..services import pushnotify

router = APIRouter(prefix="/push", tags=["push"])

#: How much of a browser's self-description is kept. It is a string from a
#: client, it is only ever shown back to the person it came from, and the
#: useful part is at the front.
AGENT_CHARS = 200


def _out(row: PushSubscription, *, current: bool) -> PushSubscriptionOut:
    return PushSubscriptionOut(
        id=row.id,
        user_agent=row.user_agent,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        current=current,
    )


@router.get("", response_model=PushStatusOut)
def push_status(user: CurrentUser, session: DbSession, config: AppConfig) -> PushStatusOut:
    """Whether this deployment can send, and what this reader has signed up.

    The public key travels with it so the page needs one request rather than
    two, and it is not a secret: every browser that subscribes is handed it.
    """
    return PushStatusOut(
        available=pushnotify.configured(config),
        public_key=pushnotify.public_key(config),
        subscriptions=[
            _out(row, current=False) for row in pushnotify.subscriptions_for(session, user)
        ],
    )


@router.post("", response_model=PushSubscriptionOut, status_code=status.HTTP_201_CREATED)
def subscribe(
    payload: PushSubscribeIn,
    user: CurrentUser,
    request: Request,
    session: DbSession,
    config: AppConfig,
) -> PushSubscriptionOut:
    """Record one browser's subscription.

    Re-subscribing the same endpoint updates it rather than failing. A browser
    hands back the endpoint it already has whenever the page asks, so a person
    who reloads the settings page twice must not end up with a duplicate or an
    error -- and if the endpoint has moved to a different account, it belongs to
    whoever is holding it now.
    """
    if not pushnotify.configured(config):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This server has no push keys configured.",
        )

    existing = session.execute(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    ).scalar_one_or_none()
    row = existing or PushSubscription(endpoint=payload.endpoint)
    row.user_id = user.id
    row.p256dh = payload.p256dh
    row.auth = payload.auth
    row.user_agent = scrub(request.headers.get("user-agent", ""), limit=AGENT_CHARS) or None
    row.failures = 0
    row.last_used_at = None
    if existing is None:
        session.add(row)
    session.commit()
    return _out(row, current=True)


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(subscription_id: int, user: CurrentUser, session: DbSession) -> None:
    """Forget one device. Only ever your own."""
    row = session.get(PushSubscription, subscription_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such subscription.")
    session.delete(row)
    session.commit()


@router.post("/test", response_model=PushStatusOut)
def send_test(user: CurrentUser, session: DbSession, config: AppConfig) -> PushStatusOut:
    """Send this reader a notification now, so they can see it work.

    The button exists because every part of this can fail silently: permission
    granted to the wrong origin, a service worker that did not register, keys
    that do not match. One notification arriving is the only proof worth having,
    and the count of devices that took it is returned so the page can say which
    number it was.
    """
    delivered = pushnotify.send_to_user(
        session,
        user,
        {
            "title": "Milsurp Monitor",
            "body": "Notifications are working on this device.",
            "url": "/watchlist",
        },
        config,
    )
    session.commit()
    if not delivered:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "No device took the notification. If you have just turned it on, "
                "check that the browser still has permission."
            ),
        )
    return PushStatusOut(
        available=True,
        public_key=pushnotify.public_key(config),
        subscriptions=[
            _out(row, current=False) for row in pushnotify.subscriptions_for(session, user)
        ],
    )
