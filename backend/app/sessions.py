"""The session cookie, and the CSRF token that has to come with it.

**Why the token moved out of JavaScript's reach.** It used to live in
``sessionStorage``, which any script running on the page can read -- so a single
cross-site scripting hole anywhere in the frontend, or in anything the frontend
loads, hands over a working session. `HttpOnly` closes that: the browser sends
the cookie and no script can see it, so stealing it requires the browser itself
to be compromised rather than one line of markup.

**And what that costs.** A cookie is attached by the browser to *every* request
to this origin, including ones another site caused -- which is cross-site
request forgery, and is exactly the attack a header-based token was immune to
by construction. Nobody can set an ``Authorization`` header on a request they
merely caused somebody else's browser to make.

So the cookie carries two defenses rather than one:

* ``SameSite=Strict`` -- the browser will not attach it to a request that
  originated anywhere but this site. This is most of the protection, and on
  its own it would nearly do.
* A **double-submit CSRF token** -- a second cookie, deliberately *not*
  HttpOnly, whose value must be echoed back in a header on every unsafe
  request. An attacker's page can cause a request, but the same-origin policy
  stops it reading our cookie to know what to echo. Belt and braces, because
  SameSite is enforced by the browser and browsers have bugs.

The two are checked in :func:`app.deps.get_current_user`, where every
authenticated route already passes.

**Requests authenticated by header are exempt from CSRF**, and that is not a
hole: a bearer token has to be put there deliberately, so a forged request
cannot carry one. The header path stays for scripts and for the tests.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import Request, Response

from .config import Config

#: Holds the JWT. HttpOnly, so no script can read it.
SESSION_COOKIE = "milsurp_session"

#: Holds the CSRF token. Readable by script *on purpose* -- the frontend has to
#: echo it back, and the protection comes from the same-origin policy stopping
#: anybody else's page from reading it, not from hiding it.
CSRF_COOKIE = "milsurp_csrf"

#: Where the echo goes.
CSRF_HEADER = "X-CSRF-Token"

#: Methods that can change something, and so need the echo. GET and HEAD do
#: not -- and if a GET here ever changes state, the bug is the GET.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Bytes of randomness in a CSRF token. 32 is the same order as the session
#: secret; it only has to be unguessable for the life of a session.
CSRF_BYTES = 32


def secure_cookies(config: Config) -> bool:
    """Whether to mark the cookies ``Secure``.

    Off in development, because ``Secure`` means "HTTPS only" and development
    runs on plain http://localhost -- a Secure cookie there is set and then
    never sent back, which looks exactly like being signed out at random.
    Production terminates TLS in front of the application, so it is on there.
    """
    return not config.is_dev


def issue(response: Response, token: str, expires_at: datetime, config: Config) -> str:
    """Put the session on the response. Returns the CSRF token that goes with it."""
    csrf = secrets.token_urlsafe(CSRF_BYTES)
    secure = secure_cookies(config)
    # max_age rather than expires: it is relative, so a client whose clock is
    # wrong still holds the session for the intended length of time.
    max_age = max(0, int((expires_at - datetime.now(expires_at.tzinfo)).total_seconds()))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    # httponly=False is the whole mechanism, not an oversight. This is the
    # double-submit half of the CSRF defense: the page reads this cookie and
    # echoes it back in a header, and a cookie no script could read could not
    # be echoed. It is not a credential -- it authenticates nothing on its own,
    # and the session beside it is HttpOnly. What protects it is the
    # same-origin policy, which stops another site's page reading it.
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,  # nosemgrep: python.fastapi.web.fastapi-cookie-httponly-false.fastapi-cookie-httponly-false
        secure=secure,
        samesite="strict",
        path="/",
    )
    return csrf


def clear(response: Response, config: Config) -> None:
    """Sign out. Both cookies, with the same attributes they were set with.

    The attributes matter: a browser matches a deletion to a cookie by name,
    path and domain, and a mismatch leaves the original in place -- a sign-out
    that appears to work and does not.
    """
    secure = secure_cookies(config)
    for name, http_only in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(name, path="/", httponly=http_only, secure=secure, samesite="strict")


def token_from(request: Request, header_value: str | None) -> tuple[str | None, bool]:
    """The session token, and whether it arrived in the cookie.

    **The header wins when both are present**, because explicit beats ambient.
    A cookie is attached by the browser to anything reaching this origin,
    whoever caused it; an ``Authorization`` header has to be set by the caller,
    and the same-origin policy means a forged cross-site request cannot set
    one. So a request carrying the header is one somebody wrote on purpose,
    which is exactly the thing CSRF cannot manufacture.

    It matters in practice as well as in theory: anything holding a cookie jar
    -- ``requests.Session``, the test client -- keeps the cookie from signing in
    and then sends both. Preferring the cookie there would force every script
    to also do the CSRF dance for no gain, since it had the stronger credential
    in hand the whole time.
    """
    if header_value:
        return header_value, False
    return request.cookies.get(SESSION_COOKIE) or None, True


def csrf_is_valid(request: Request) -> bool:
    """Whether this request echoed the CSRF cookie back in the header."""
    expected = request.cookies.get(CSRF_COOKIE)
    sent = request.headers.get(CSRF_HEADER)
    if not expected or not sent:
        return False
    return secrets.compare_digest(expected, sent)
