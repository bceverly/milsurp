"""Shared FastAPI dependencies: authentication and role gates."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Config, get_config
from .database import get_db
from .models import User, UserRole
from .security import TokenError, decode_access_token

# auto_error=False so a missing header produces our own 401 with a useful
# message rather than FastAPI's bare "Not authenticated".
bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_db)],
    config: Annotated[Config, Depends(get_config)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_EXCEPTION
    try:
        payload = decode_access_token(credentials.credentials, config)
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
