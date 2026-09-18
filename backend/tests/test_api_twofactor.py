"""Signing in with a second factor, over HTTP.

The service tests cover the arithmetic; these cover the exchange, and the two
properties that matter most are about what the *server tells an attacker*: that
a code is only ever asked for after the password is known good, and that being
asked is not the same as having failed.
"""

from __future__ import annotations

import time

import pytest

from app import totp
from app.models import User
from app.services import twofactor

#: What conftest's `normal_user` fixture creates. It returns the created user
#: and its headers, not the credentials, so they are named here rather than
#: reached for through the dictionary.
VIEWER = "viewer"
VIEWER_PASSWORD = "viewer-long-passphrase"


@pytest.fixture
def enrolled(client, normal_user, seeded, app_config):
    """A normal account with two-factor on, and its recovery codes."""
    user = seeded.query(User).filter_by(username=VIEWER).one()
    twofactor.begin_enrollment(user, app_config)
    secret = totp.unseal(user.totp_secret, app_config)
    codes = twofactor.confirm_enrollment(
        seeded, user, totp.code_at(secret, time.time()), app_config
    )
    seeded.commit()
    return user, secret, codes


class TestTheSignInExchange:
    def test_an_account_without_it_gets_a_token_straight_away(self, client, normal_user):
        response = client.post(
            "/api/auth/login",
            json={"username": VIEWER, "password": VIEWER_PASSWORD},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_one_with_it_is_asked_for_a_code(self, client, normal_user, enrolled):
        """A 200 saying "I need the other half", not a 401. Nothing has gone
        wrong — the password was right — and a 401 would be indistinguishable
        from a wrong password to the page and to anything reading the logs."""
        response = client.post(
            "/api/auth/login",
            json={"username": VIEWER, "password": VIEWER_PASSWORD},
        )
        assert response.status_code == 200
        body = response.json()
        assert body.get("two_factor_required") is True
        assert "access_token" not in body

    def test_and_signs_in_with_one(self, client, normal_user, enrolled):
        _user, secret, _codes = enrolled
        response = client.post(
            "/api/auth/login",
            json={
                "username": VIEWER,
                "password": VIEWER_PASSWORD,
                "totp_code": totp.code_at(secret, time.time()),
            },
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_a_recovery_code_works_at_the_same_prompt(self, client, normal_user, enrolled):
        _user, _secret, codes = enrolled
        response = client.post(
            "/api/auth/login",
            json={
                "username": VIEWER,
                "password": VIEWER_PASSWORD,
                "totp_code": codes[0],
            },
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_a_wrong_code_is_refused(self, client, normal_user, enrolled):
        response = client.post(
            "/api/auth/login",
            json={
                "username": VIEWER,
                "password": VIEWER_PASSWORD,
                "totp_code": "000000",
            },
        )
        assert response.status_code == 401
        assert "access_token" not in response.json()

    def test_a_right_code_with_a_wrong_password_is_still_refused(
        self, client, normal_user, enrolled
    ):
        """The code is checked only after the password, so this cannot be used
        to find out which accounts have two-factor turned on."""
        _user, secret, _codes = enrolled
        response = client.post(
            "/api/auth/login",
            json={
                "username": VIEWER,
                "password": "not-the-password",
                "totp_code": totp.code_at(secret, time.time()),
            },
        )
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["detail"]


class TestEnrollment:
    def test_starting_returns_a_secret_and_a_uri(self, client, normal_user):
        response = client.post("/api/auth/totp/start", headers=normal_user["headers"])
        assert response.status_code == 200
        body = response.json()
        assert len(body["secret"]) == 32
        assert body["secret"].replace("", "") in body["otpauth_uri"]
        assert body["secret_grouped"].replace(" ", "") == body["secret"]

    def test_and_does_not_turn_it_on_yet(self, client, normal_user, seeded):
        client.post("/api/auth/totp/start", headers=normal_user["headers"])
        status = client.get("/api/auth/totp", headers=normal_user["headers"]).json()
        assert status["enabled"] is False

    def test_confirming_turns_it_on_and_hands_back_codes_once(
        self, client, normal_user, seeded, app_config
    ):
        body = client.post("/api/auth/totp/start", headers=normal_user["headers"]).json()
        code = totp.code_at(body["secret"], time.time())
        response = client.post(
            "/api/auth/totp/confirm", json={"code": code}, headers=normal_user["headers"]
        )
        assert response.status_code == 200
        assert len(response.json()["codes"]) == twofactor.RECOVERY_CODES

        status = client.get("/api/auth/totp", headers=normal_user["headers"]).json()
        assert status["enabled"] is True
        assert status["recovery_codes_left"] == twofactor.RECOVERY_CODES

    def test_a_wrong_confirming_code_is_a_400(self, client, normal_user):
        client.post("/api/auth/totp/start", headers=normal_user["headers"])
        response = client.post(
            "/api/auth/totp/confirm", json={"code": "000000"}, headers=normal_user["headers"]
        )
        assert response.status_code == 400

    def test_enrolling_again_while_on_is_refused(self, client, normal_user, enrolled):
        """Rather than silently replacing a working secret with one nobody has
        scanned yet."""
        response = client.post("/api/auth/totp/start", headers=normal_user["headers"])
        assert response.status_code == 409


class TestTurningItOff:
    def test_it_needs_the_password(self, client, normal_user, enrolled):
        """The thing being removed is what protects the account when the
        password is already known to somebody else, so a live session alone
        must not be enough to undo it."""
        response = client.post(
            "/api/auth/totp/disable",
            json={"password": "not-the-password"},
            headers=normal_user["headers"],
        )
        assert response.status_code == 403

    def test_and_with_it_the_account_signs_in_without_a_code(self, client, normal_user, enrolled):
        response = client.post(
            "/api/auth/totp/disable",
            json={"password": VIEWER_PASSWORD},
            headers=normal_user["headers"],
        )
        assert response.status_code == 204

        signed_in = client.post(
            "/api/auth/login",
            json={"username": VIEWER, "password": VIEWER_PASSWORD},
        )
        assert "access_token" in signed_in.json()


class TestOnlyYourOwn:
    def test_the_status_is_the_callers_own(self, client, normal_user, admin_headers, enrolled):
        """There is no route to another account's two-factor state: the
        endpoints read CurrentUser and take no user id at all."""
        assert client.get("/api/auth/totp", headers=admin_headers).json()["enabled"] is False
        assert (
            client.get("/api/auth/totp", headers=normal_user["headers"]).json()["enabled"] is True
        )

    def test_signing_in_is_required(self, client):
        assert client.get("/api/auth/totp").status_code in (401, 403)
