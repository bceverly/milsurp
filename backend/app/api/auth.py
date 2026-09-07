"""Sign-in, session identity and self-service password change."""

from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Request, status

from ..deps import AppConfig, CurrentUser, DbSession
from ..logsafe import ADDRESS_PATTERN, safe_identifier
from ..models import User, utcnow
from ..schemas import LoginRequest, PasswordChangeRequest, TokenResponse, UserOut
from ..security import (
    PasswordPolicyError,
    create_access_token,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("milsurp.auth")

# --- Login throttling -------------------------------------------------------
# Argon2 already makes each guess expensive, but an unthrottled endpoint still
# lets an attacker run an online dictionary attack and pins a CPU while doing
# it. Failures are counted per (username, client IP) in memory; this is a
# single-process app, so a shared dict is sufficient and needs no Redis.
MAX_ATTEMPTS = 8
LOCKOUT_SECONDS = 300
_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()


def _client_address(request: Request) -> str:
    """The peer address, or a fixed marker when there is none.

    Read straight from the connection, so nothing here comes from the request
    body. A test client has no peer at all.

    Guarded on the way out rather than at the point it is logged, so every
    caller gets the same value and no future one has to remember. See
    :data:`ADDRESS_PATTERN` for why this is an allowlist and not an escape.
    """
    host = request.client.host if request.client else "unknown"
    return safe_identifier(host, ADDRESS_PATTERN)


def _throttle_key(username: str, request: Request) -> str:
    return f"{username.lower()}|{_client_address(request)}"


def _check_throttle(key: str) -> None:
    now = time.monotonic()
    with _attempts_lock:
        recent = [t for t in _attempts.get(key, []) if now - t < LOCKOUT_SECONDS]
        _attempts[key] = recent
        if len(recent) >= MAX_ATTEMPTS:
            wait = int(LOCKOUT_SECONDS - (now - recent[0]))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed sign-in attempts. Try again in {wait} seconds.",
                headers={"Retry-After": str(max(1, wait))},
            )


def _record_failure(key: str) -> None:
    with _attempts_lock:
        _attempts.setdefault(key, []).append(time.monotonic())


def _clear_failures(key: str) -> None:
    with _attempts_lock:
        _attempts.pop(key, None)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest, request: Request, session: DbSession, config: AppConfig
) -> TokenResponse:
    key = _throttle_key(payload.username, request)
    _check_throttle(key)

    user = session.query(User).filter(User.username == payload.username).one_or_none()

    # The same message and roughly the same work for every failure mode, so the
    # response cannot be used to enumerate valid usernames.
    if user is None or not verify_password(payload.password, user.password_hash, config):
        if user is None:
            # Spend comparable time on a dummy verify to flatten the timing
            # difference between "no such user" and "wrong password".
            hash_password("timing-equalizer", config)
        _record_failure(key)
        # The username goes through an allowlist rather than an escape: it is
        # either one of this application's account names or it is nothing.
        #
        # The client address is read from the request, not sliced back out of
        # the throttle key. The key is built as "<username>|<address>", so
        # key.split("|")[-1] carried the submitted username along with it — an
        # obscure way to obtain something the request already has, and one that
        # put attacker-controlled text into a log line that looked sanitised.
        log.warning(
            "Failed sign-in for %s from %s",
            safe_identifier(payload.username),
            # Already guarded: _client_address() allowlists on the way out.
            _client_address(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    if not user.is_active:
        _record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled. Contact an administrator.",
        )

    _clear_failures(key)

    # Transparently upgrade a hash that predates the current Argon2 cost.
    if needs_rehash(user.password_hash, config):
        user.password_hash = hash_password(payload.password, config)

    user.last_login_at = utcnow()
    session.commit()

    token, expires_at = create_access_token(user.id, user.role.value, user.token_version, config)
    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    user: CurrentUser,
    session: DbSession,
    config: AppConfig,
) -> None:
    if not verify_password(payload.current_password, user.password_hash, config):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must differ from the current one.",
        )
    try:
        validate_password(payload.new_password, config)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user.password_hash = hash_password(payload.new_password, config)
    # Retires every token issued under the old password, on every device.
    user.token_version += 1
    session.commit()
