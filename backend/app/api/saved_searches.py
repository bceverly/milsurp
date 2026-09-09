"""Named browse queries, and the per-search email that goes with them.

A saved search belongs to the user who made it: there is no approval step and
no sharing, unlike the armory. Every route here is scoped to
``CurrentUser.id``, so one account cannot read or change another's — which is
the only access rule this resource needs.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..deps import AppConfig, CurrentUser, DbSession
from ..models import EmailStatus, Item, SavedSearch, User
from ..schemas import SavedSearchCreate, SavedSearchOut, SavedSearchUpdate
from ..services import digest
from ..services import search as search_service

router = APIRouter(prefix="/saved-searches", tags=["saved searches"])


def _parsed(query: str) -> search_service.SearchQuery:
    """The query, or a 400 naming what is wrong with it.

    Validation happens here, when a person is watching, and not at send time,
    when nobody is. See ``services.search.parse_query``.
    """
    try:
        return search_service.parse_query(query)
    except search_service.BadQuery as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _count(session: DbSession, parsed: search_service.SearchQuery) -> int:
    stmt = search_service.apply_filters(select(func.count(Item.id)), **parsed.filters)
    return int(session.execute(stmt).scalar_one())


def _to_out(session: DbSession, row: SavedSearch) -> SavedSearchOut:
    data = SavedSearchOut.model_validate(row)
    # The whole result set, not the email's capped view of it: the number on
    # the card answers "how big is this search", and the cap answers "how much
    # of it is mailed".
    data.match_count = _count(session, _parsed(row.query))
    return data


def _owned(session: DbSession, user: User, search_id: int) -> SavedSearch:
    row = session.get(SavedSearch, search_id)
    # 404 rather than 403 for somebody else's row: whether a given id exists is
    # not this user's business either.
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such saved search.")
    return row


@router.get("", response_model=list[SavedSearchOut])
def list_saved_searches(user: CurrentUser, session: DbSession) -> list[SavedSearchOut]:
    rows = (
        session.execute(
            select(SavedSearch)
            .where(SavedSearch.user_id == user.id)
            .order_by(func.lower(SavedSearch.name))
        )
        .scalars()
        .all()
    )
    return [_to_out(session, row) for row in rows]


@router.post("", response_model=SavedSearchOut, status_code=status.HTTP_201_CREATED)
def create_saved_search(
    payload: SavedSearchCreate, user: CurrentUser, session: DbSession
) -> SavedSearchOut:
    parsed = _parsed(payload.query)
    row = SavedSearch(
        user_id=user.id,
        name=payload.name.strip(),
        # Stored canonical, so re-saving the same search from a URL whose
        # parameters happen to be in a different order does not read as a
        # different search.
        query=parsed.as_query_string(),
        sort=parsed.sort,
        email_enabled=payload.email_enabled,
        email_item_limit=payload.email_item_limit,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a saved search called {payload.name.strip()!r}.",
        ) from exc
    return _to_out(session, row)


@router.patch("/{search_id}", response_model=SavedSearchOut)
def update_saved_search(
    search_id: int, payload: SavedSearchUpdate, user: CurrentUser, session: DbSession
) -> SavedSearchOut:
    row = _owned(session, user, search_id)

    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.query is not None:
        parsed = _parsed(payload.query)
        row.query = parsed.as_query_string()
        row.sort = parsed.sort
    if payload.email_enabled is not None:
        row.email_enabled = payload.email_enabled
    if payload.email_item_limit is not None:
        row.email_item_limit = payload.email_item_limit

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a saved search called {row.name!r}.",
        ) from exc
    return _to_out(session, row)


@router.post("/{search_id}/send", status_code=status.HTTP_202_ACCEPTED)
def send_saved_search_now(
    search_id: int, user: CurrentUser, session: DbSession, config: AppConfig
) -> dict[str, str]:
    """Mail this one search's results now.

    Deliberately not gated on ``email_enabled``: that answers "send this every
    day", and this answers "send it to me now". Seeing what a search would mail
    before committing to a daily one is most of why the button exists.

    A search matching nothing is a 409 with a message rather than an empty
    email — the screen the button is on is a better place to be told.
    """
    row = _owned(session, user, search_id)
    if not config.email.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is disabled in the server configuration (email.enabled).",
        )

    entry = digest.send_saved_search(session, user, row, config)
    if entry.status is EmailStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=entry.error_message or "Delivery failed.",
        )
    if entry.status is EmailStatus.SKIPPED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=entry.error_message or "Nothing to send.",
        )
    return {"message": f"Sent to {user.email}."}


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search(search_id: int, user: CurrentUser, session: DbSession) -> None:
    session.delete(_owned(session, user, search_id))
    session.commit()
