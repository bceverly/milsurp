"""Shared FastAPI dependencies: authentication and role gates."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import sessions
from .config import Config, get_config
from .database import get_db
from .models import User, UserRole, UserSession
from .security import TokenError, decode_access_token
from .services import usersessions

# auto_error=False so a missing header produces our own 401 with a useful
# message rather than FastAPI's bare "Not authenticated".
bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


CSRF_EXCEPTION = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Missing or invalid CSRF token.",
)


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_db)],
    config: Annotated[Config, Depends(get_config)],
) -> User:
    header = credentials.credentials if credentials else None
    token, from_cookie = sessions.token_from(request, header)
    if not token:
        raise CREDENTIALS_EXCEPTION

    # A cookie is attached by the browser to anything that reaches this origin,
    # including a request another site caused -- so a session that arrived that
    # way has to prove the page asking for it is ours. A bearer token needs no
    # such proof: it has to be set deliberately, and a forged request cannot.
    if (
        from_cookie
        and request.method in sessions.UNSAFE_METHODS
        and not sessions.csrf_is_valid(request)
    ):
        raise CSRF_EXCEPTION

    try:
        payload = decode_access_token(token, config)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CREDENTIALS_EXCEPTION from exc

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled or no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # A password change bumps token_version, which retires every token issued
    # before it -- including any an attacker may be holding.
    if int(payload.get("ver", 0)) != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is no longer valid; please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # And the narrower revocation: this one sign-in, ended from the sessions
    # list, without disturbing the others. A token with no `sid` predates
    # sessions or was minted by a script; those stay valid and token_version is
    # still what retires them.
    session_id = payload.get("sid")
    if session_id is not None:
        row = session.get(UserSession, int(session_id))
        if row is None or not row.is_live:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="That session was signed out.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        usersessions.touch(row)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an administrator account.",
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
DbSession = Annotated[Session, Depends(get_db)]
AppConfig = Annotated[Config, Depends(get_config)]
