"""The session cookie, and the CSRF token that has to come with it.

The session used to live in ``sessionStorage``, where any script on the page
could read it -- so one cross-site scripting hole anywhere in the frontend, or
in anything it loads, handed over a working session for as long as it lasted.

An HttpOnly cookie closes that and opens something else, which is the whole
reason this file is careful: the browser now attaches the session to *every*
request reaching this origin, including ones another site caused. That is
cross-site request forgery, and a header-based token was immune to it by
construction. So the properties below are not decoration -- each one is the
thing standing where the old design needed nothing.
"""

from __future__ import annotations

import dataclasses

import pytest

from app import sessions


def cookie_attributes(response, name: str) -> dict[str, str]:
    """The Set-Cookie attributes for one cookie, lowercased.

    Read off the raw header because the cookie jar keeps the value and throws
    away exactly the flags this file is about.
    """
    for header in response.headers.get_list("set-cookie"):
        if not header.startswith(f"{name}="):
            continue
        parts = [p.strip() for p in header.split(";")[1:]]
        found = {}
        for part in parts:
            key, _, value = part.partition("=")
            found[key.lower()] = value
        return found
    raise AssertionError(f"no {name} cookie was set")


@pytest.fixture
def signed_in(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-passphrase"},
    )
    assert response.status_code == 200, response.text
    return response


class TestWhatSigningInSets:
    def test_the_session_cookie_is_not_readable_by_script(self, signed_in):
        """The point of the whole change."""
        assert "httponly" in cookie_attributes(signed_in, sessions.SESSION_COOKIE)

    def test_the_csrf_cookie_deliberately_is(self, signed_in):
        """It has to be, or the page could not echo it back. It is not a
        secret; it is unreadable to *other* origins, which is the defense."""
        assert "httponly" not in cookie_attributes(signed_in, sessions.CSRF_COOKIE)

    @pytest.mark.parametrize("name", [sessions.SESSION_COOKIE, sessions.CSRF_COOKIE])
    def test_neither_is_sent_to_another_site(self, signed_in, name):
        assert cookie_attributes(signed_in, name).get("samesite", "").lower() == "strict"

    def test_the_csrf_token_is_in_the_body_too(self, signed_in):
        """So the page has it without having to parse cookies on first load."""
        body = signed_in.json()
        assert body["csrf_token"]
        assert body["csrf_token"] == signed_in.cookies.get(sessions.CSRF_COOKIE)

    def test_development_does_not_mark_them_secure(self, signed_in):
        """`Secure` means HTTPS-only. Development is plain http, where a Secure
        cookie is set and never sent back -- which looks exactly like being
        signed out at random."""
        assert "secure" not in cookie_attributes(signed_in, sessions.SESSION_COOKIE)

    def test_but_production_does(self, app_config):
        production = dataclasses.replace(app_config, mode="production")
        assert sessions.secure_cookies(production)
        assert not sessions.secure_cookies(app_config)


class TestTheCookieIsEnoughToBeSignedIn:
    def test_a_read_needs_nothing_else(self, client, signed_in):
        """No Authorization header anywhere: the cookie the client kept is
        the whole credential."""
        assert client.get("/api/auth/me").status_code == 200


class TestForgeryIsWhatTheCsrfTokenStops:
    """A cookie rides along on a request another site caused. These are the
    checks that such a request cannot change anything."""

    def _payload(self, name="forged"):
        return {
            "username": name,
            "email": f"{name}@example.com",
            "password": "a-long-enough-passphrase",
            "role": "normal",
        }

    def test_a_write_with_the_cookie_alone_is_refused(self, client, signed_in):
        response = client.post("/api/users", json=self._payload())
        assert response.status_code == 403
        assert "CSRF" in response.json()["detail"]

    def test_a_write_echoing_the_token_is_allowed(self, client, signed_in):
        response = client.post(
            "/api/users",
            json=self._payload("allowed"),
            headers={sessions.CSRF_HEADER: signed_in.json()["csrf_token"]},
        )
        assert response.status_code == 201, response.text

    def test_a_wrong_token_is_refused(self, client, signed_in):
        response = client.post(
            "/api/users",
            json=self._payload("wrong"),
            headers={sessions.CSRF_HEADER: "not-the-right-token"},
        )
        assert response.status_code == 403

    def test_reads_are_not_asked_for_one(self, client, signed_in):
        """A GET that changes something is a bug in the GET, not a reason to
        make every read carry a token."""
        assert client.get("/api/users").status_code == 200

    def test_a_bearer_token_is_exempt(self, client, admin_headers):
        """Not a hole. An Authorization header has to be set deliberately, and
        the same-origin policy means a forged request cannot set one -- which
        is the entire reason the old scheme needed no CSRF defense."""
        response = client.post("/api/users", json=self._payload("bearer"), headers=admin_headers)
        assert response.status_code == 201, response.text


class TestSigningOut:
    def test_it_clears_both_cookies(self, client, signed_in):
        response = client.post("/api/auth/logout")
        assert response.status_code == 204
        cleared = response.headers.get_list("set-cookie")
        assert any(sessions.SESSION_COOKIE in c for c in cleared)
        assert any(sessions.CSRF_COOKIE in c for c in cleared)

    def test_and_the_session_no_longer_works(self, client, signed_in):
        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").status_code == 401

    def test_it_works_without_being_signed_in(self, client):
        """Somebody holding a broken or expired session still has to be able
        to get rid of it, and the worst this can do to anyone is sign them
        out."""
        assert client.post("/api/auth/logout").status_code == 204
