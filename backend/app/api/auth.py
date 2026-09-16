"""Sign-in, session identity and self-service password change."""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from .. import sessions, totp
from ..deps import AppConfig, CurrentUser, DbSession
from ..logsafe import client_address
from ..models import User, utcnow
from ..schemas import (
    LoginRequest,
    PasswordChangeRequest,
    PasswordConfirm,
    PasswordResetCheck,
    PasswordResetRedeem,
    RecoveryCodesOut,
    SessionOut,
    TokenResponse,
    TotpConfirm,
    TotpStart,
    TotpStatus,
    TwoFactorRequired,
    UserOut,
)
from ..security import (
    PasswordPolicyError,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)
from ..services import audit, passwordreset, twofactor, usersessions

router = APIRouter(prefix="/auth", tags=["auth"])

#: Stands in for a username that matched no account.
#:
#: Fixed text, so a log line can never be written by the person failing to sign
#: in. The rate limiter still counts attempts per submitted name and address,
#: so a sweep through a list of guessed accounts is still visible as a burst of
#: these from one address — just without their contents.
NO_SUCH_ACCOUNT = "<no such account>"


def account_label(user: User | None) -> str:
    """What to call the account somebody failed to sign in to.

    The name comes from the database or it does not come at all. Never from the
    request — that is the whole point, and it is a rule worth having somewhere
    testable rather than inline in a log call.
    """
    return user.username if user is not None else NO_SUCH_ACCOUNT


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
    """The peer address. Moved to logsafe when the audit log wanted it too."""
    return client_address(request)


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


@router.post("/login", response_model=TokenResponse | TwoFactorRequired)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
    config: AppConfig,
) -> TokenResponse | JSONResponse:
    """Sign in, in one exchange or two.

    An account without two-factor gets a token straight back. One with it gets
    a ``two_factor_required`` body instead, and the page asks again with the
    code alongside the password it already has.
    """
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
        # What is logged is the account that was *matched*, read back from the
        # database — never the string that was submitted.
        #
        # The submitted name used to be passed through an allowlist, on the
        # belief that a guard was a barrier a taint tracker would respect. It
        # is not: the function returns the original string on the matching
        # branch, so the value in the log line was still the one from the
        # request, and CodeQL went on reporting log injection because it was
        # right to.
        #
        # Nothing is lost by this. A failed sign-in against a real account is
        # the line worth having, and it names that account exactly. A sign-in
        # against an account that does not exist is somebody guessing, and
        # writing their guess into the log is how the guess becomes the
        # message — so those are counted, not quoted.
        #
        # The client address is read from the request, not sliced back out of
        # the throttle key. The key is built as "<username>|<address>", so
        # key.split("|")[-1] carried the submitted username along with it — an
        # obscure way to obtain something the request already has.
        log.warning(
            "Failed sign-in for %s from %s",
            account_label(user),
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

    # --- the second factor ---------------------------------------------------
    # After the password and before anything else is decided. A code is checked
    # only once the password is known good, so this cannot be used to find out
    # which accounts have two-factor turned on.
    if twofactor.is_enabled(user):
        if not payload.totp_code:
            # Not a 401: nothing has gone wrong, and the throttle counter is
            # deliberately left alone. Counting "the password was right and I
            # have not asked for the code yet" as a failed attempt would lock
            # somebody out of their own account halfway through signing in.
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=TwoFactorRequired().model_dump(),
            )
        if not twofactor.check(session, user, payload.totp_code, config):
            session.commit()  # a spent recovery code stays spent
            _record_failure(key)
            log.warning(
                "Failed second factor for %s from %s",
                account_label(user),
                _client_address(request),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="That code was not right. Try the next one your app shows.",
            )

    _clear_failures(key)

    # Transparently upgrade a hash that predates the current Argon2 cost.
    if needs_rehash(user.password_hash, config):
        user.password_hash = hash_password(payload.password, config)

    user.last_login_at = utcnow()
    session.commit()

    # The row first, because the token has to carry its id -- that id is what
    # makes this one sign-in endable without ending the others.
    expires_at_guess = utcnow() + timedelta(minutes=config.security.access_token_minutes)
    record = usersessions.begin(
        session,
        user,
        expires_at=expires_at_guess,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_address(request),
    )
    token, expires_at = create_access_token(
        user.id, user.role.value, user.token_version, config, session_id=record.id
    )
    # The guess above is only used to create the row; the token decides the
    # real expiry, so the row is corrected rather than left approximately right.
    record.expires_at = expires_at
    session.commit()
    # The browser's copy: HttpOnly, so no script can read it. See app/sessions.
    csrf = sessions.issue(response, token, expires_at, config)
    return TokenResponse(
        access_token=token,
        csrf_token=csrf,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(config: AppConfig) -> Response:
    """Drop the session cookies.

    Needed now in a way it was not before. Signing out used to be the page
    forgetting a string it was holding; a cookie belongs to the browser, and
    only a response can ask it to let go. Unauthenticated on purpose -- someone
    holding an expired or broken session must still be able to get rid of it,
    and the worst this can do to anyone is sign them out.
    """
    # Cleared on the response that is actually returned. Setting them on an
    # injected Response and then returning a different one discards them
    # silently: a sign-out that answers 204 and leaves the session standing.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    sessions.clear(response, config)
    return response


@router.get("/reset/{token}", response_model=PasswordResetCheck)
def check_reset_link(token: str, session: DbSession, config: AppConfig) -> PasswordResetCheck:
    """Whether this link is still good, before the form is shown.

    Unauthenticated, necessarily: whoever clicked it cannot sign in. That is
    safe because the token is thirty-two random bytes -- there is nothing to
    guess -- and because a wrong one learns nothing beyond "no".

    The username is returned on a good one so the page can say whose account it
    is about. On a bad one nothing is, which is the whole of what a prober
    gets.
    """
    user = passwordreset.find_valid(session, token, config)
    if user is None:
        return PasswordResetCheck(valid=False)
    return PasswordResetCheck(valid=True, username=user.username)


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
def redeem_reset_link(payload: PasswordResetRedeem, session: DbSession, config: AppConfig) -> None:
    """Set a new password from a one-time link.

    The password rules are applied first, so a link is not spent on a password
    that was going to be refused -- somebody who has just been sent a link and
    typed something too short should get another go, not another email.
    """
    try:
        validate_password(payload.new_password, config)
    except PasswordPolicyError as exc:
        # 400, matching every other password-policy refusal in this API rather
        # than introducing a second convention for the same kind of answer.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user = passwordreset.redeem(session, payload.token, payload.new_password, config)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That link has expired or has already been used. Ask for a new one.",
        )
    session.commit()
    # The account name, never the token: this line ends up in a log file.
    # The rule fires on the word "Password" in the message template. The only
    # interpolated value is account_label(), which reads the name off the
    # database row -- the token was already redeemed and is not in scope here.
    log.info(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
        "Password reset completed for %s", account_label(user)
    )


@router.post("/totp/start", response_model=TotpStart)
def totp_start(user: CurrentUser, session: DbSession, config: AppConfig) -> TotpStart:
    """Issue a secret and show it. Does not turn anything on.

    Enrolment is two exchanges on purpose: the secret has to exist for the
    confirming code to be checked against, and the flag stays off until a code
    comes back from the phone. Collapsing them means a mistyped secret, or a
    closed tab, locks the account out.

    Calling it again simply replaces the pending secret, which is what somebody
    who closed the tab will do.
    """
    if twofactor.is_enabled(user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor is already on. Turn it off first to enrol a new device.",
        )
    secret, uri = twofactor.begin_enrolment(user, config)
    session.commit()
    return TotpStart(secret=secret, secret_grouped=totp.grouped(secret), otpauth_uri=uri)


@router.post("/totp/confirm", response_model=RecoveryCodesOut)
def totp_confirm(
    payload: TotpConfirm, user: CurrentUser, session: DbSession, config: AppConfig
) -> RecoveryCodesOut:
    """Turn it on, and hand back the recovery codes once."""
    codes = twofactor.confirm_enrolment(session, user, payload.code, config)
    if codes is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code was not right. Check the time on your phone and try the next one.",
        )
    session.commit()
    log.info("Two-factor enabled for %s", account_label(user))
    return RecoveryCodesOut(codes=codes)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
def totp_disable(
    payload: PasswordConfirm, user: CurrentUser, session: DbSession, config: AppConfig
) -> None:
    """Turn it off. The current password is required.

    Because the thing being removed is what protects the account when the
    password is already known to somebody else: letting a live session switch
    it off without proving the password would mean a stolen token is enough to
    undo the second factor.
    """
    if not verify_password(payload.password, user.password_hash, config):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="That password is not right."
        )
    twofactor.disable(session, user)
    session.commit()
    log.warning("Two-factor disabled for %s", account_label(user))


@router.get("/totp", response_model=TotpStatus)
def totp_status(user: CurrentUser, session: DbSession) -> TotpStatus:
    return TotpStatus(
        enabled=twofactor.is_enabled(user),
        confirmed_at=user.totp_confirmed_at,
        recovery_codes_left=twofactor.recovery_codes_left(session, user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


def _current_session_id(request: Request, config) -> int | None:
    """Which session row this request is using, if any.

    Read back out of the token rather than tracked somewhere: the token is
    already being decoded on every request, and a second source of truth for
    "which session is this" is a second thing that can disagree.
    """
    from ..sessions import token_from

    credentials = request.headers.get("authorization", "")
    header = credentials[7:] if credentials.lower().startswith("bearer ") else None
    token, _ = token_from(request, header)
    if not token:
        return None
    try:
        payload = decode_access_token(token, config)
    except TokenError:
        return None
    sid = payload.get("sid")
    return int(sid) if sid is not None else None


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    request: Request, user: CurrentUser, session: DbSession, config: AppConfig
) -> list[SessionOut]:
    """Where this account is signed in.

    Only ever this account's own: the sessions list is a personal security
    page, not an administrative one. An admin who needs to end somebody else's
    access disables the account, which ends all of it.
    """
    here = _current_session_id(request, config)
    out = []
    for row in usersessions.live_for(session, user):
        item = SessionOut.model_validate(row, from_attributes=True)
        out.append(item.model_copy(update={"current": row.id == here}))
    return out


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    session_id: int,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> None:
    """End one sign-in, including possibly this one."""
    if not usersessions.revoke(session, user, session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such session.",
        )
    audit.record(
        session,
        actor=user,
        action=audit.SESSION_REVOKED,
        target_type="session",
        target_id=session_id,
        ip_address=_client_address(request),
    )
    session.commit()


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
def revoke_other_sessions(
    request: Request, user: CurrentUser, session: DbSession, config: AppConfig
) -> None:
    """Sign out everywhere except here.

    The exception matters: signing yourself out as a side effect of securing
    your account reads as the button having gone wrong, and the next thing
    somebody does is sign back in and wonder whether it worked.
    """
    ended = usersessions.revoke_all(session, user, except_id=_current_session_id(request, config))
    audit.record(
        session,
        actor=user,
        action=audit.SESSIONS_REVOKED,
        target_type="session",
        detail=f"{ended} other session(s)",
        ip_address=_client_address(request),
    )
    session.commit()


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
