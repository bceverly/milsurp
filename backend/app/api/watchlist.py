"""The listings a user is following.

Every route is scoped to ``CurrentUser.id``, the same rule saved searches
follow: one account cannot read, change or even learn the existence of
another's watchlist. A watch is a statement about what somebody wants, which
is more personal than most of what this catalog holds.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession
from ..models import Item, Site, WatchedItem, as_utc, utcnow
from ..schemas import WatchCreate, WatchOut
from ..services import watchlist

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _since(user: CurrentUser) -> object:
    """The watermark the digest would use for this user, for the headlines.

    The page shows what the *next* email will say, so it has to ask the same
    question from the same starting point. Without a preference row there is no
    watermark, and a day is the frequency a digest defaults to.
    """
    preference = user.email_preference
    if preference is not None and preference.last_digest_cutoff is not None:
        return as_utc(preference.last_digest_cutoff)
    hours = preference.frequency_hours if preference is not None else 24
    return utcnow() - timedelta(hours=max(1, hours))


def _out(watch: WatchedItem, site_names: dict[int, str], since) -> WatchOut:
    from .items import _to_out

    news = watchlist.news_for(watch, watch.item, since) if watch.item else None
    return WatchOut(
        id=watch.id,
        item=_to_out(watch.item, site_names),
        target_price=watch.target_price,
        note=watch.note,
        created_at=watch.created_at,
        headline=watchlist.HEADLINES[news] if news else None,
    )


@router.get("", response_model=list[WatchOut])
def list_watched(user: CurrentUser, session: DbSession) -> list[WatchOut]:
    rows = watchlist.for_user(session, user)
    site_names = {
        site.id: site.name
        for site in session.execute(
            select(Site).where(Site.id.in_({row.item.site_id for row in rows if row.item}))
        ).scalars()
    }
    since = _since(user)
    return [_out(row, site_names, since) for row in rows if row.item]


@router.put("/{item_id}", response_model=WatchOut)
def watch_item(
    item_id: int, payload: WatchCreate, user: CurrentUser, session: DbSession
) -> WatchOut:
    """Start watching a listing, or change the terms of an existing watch.

    PUT rather than POST because starring is idempotent: the star is a state,
    not an event, and clicking it twice should leave one watch rather than
    fail. It doubles as the way to set a target on something already starred.
    """
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such item.")

    row = watchlist.watching(session, user, item_id)
    if row is None:
        row = WatchedItem(user_id=user.id, item_id=item_id)
        session.add(row)
    row.target_price = payload.target_price
    row.note = (payload.note or "").strip() or None
    session.commit()
    session.refresh(row)

    site = session.get(Site, item.site_id)
    return _out(row, {item.site_id: site.name} if site else {}, _since(user))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def unwatch_item(item_id: int, user: CurrentUser, session: DbSession) -> None:
    """Stop watching. Silent when it was not being watched: the caller asked
    for it to be gone and it is gone, which is what they wanted either way."""
    row = watchlist.watching(session, user, item_id)
    if row is not None:
        session.delete(row)
        session.commit()
