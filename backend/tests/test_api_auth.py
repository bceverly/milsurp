"""Authentication, authorization and the role boundary."""

from __future__ import annotations

from app.api import auth
from app.models import User


class TestLogin:
    def test_success(self, client):
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-admin-passphrase"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["role"] == "admin"
        # Timestamps leave the API as UTC with an explicit Z.
        assert body["expires_at"].endswith("Z")

    def test_wrong_password(self, client):
        response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401

    def test_unknown_user_is_indistinguishable(self, client):
        """The response must not reveal whether the username exists."""
        missing = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
        wrong = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert missing.status_code == wrong.status_code == 401
        assert missing.json()["detail"] == wrong.json()["detail"]

    def test_disabled_account_cannot_sign_in(self, client, admin_headers, normal_user):
        client.patch(
            f"/api/users/{normal_user['user']['id']}",
            json={"is_active": False},
            headers=admin_headers,
        )
        response = client.post(
            "/api/auth/login",
            json={"username": "viewer", "password": "viewer-long-passphrase"},
        )
        assert response.status_code == 403


class TestAuthorization:
    def test_endpoints_require_a_token(self, client):
        for path in ("/api/items", "/api/sites", "/api/auth/me", "/api/users"):
            assert client.get(path).status_code == 401, path

    def test_health_is_public(self, client):
        assert client.get("/api/health").status_code == 200

    def test_garbage_token_rejected(self, client):
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"})
        assert response.status_code == 401

    def test_normal_user_cannot_reach_admin_routes(self, client, normal_user):
        headers = normal_user["headers"]
        assert client.get("/api/users", headers=headers).status_code == 403
        assert client.post("/api/sites/1/scan", headers=headers).status_code == 403
        assert client.get("/api/admin/status", headers=headers).status_code == 403
        assert (
            client.patch("/api/sites/1", json={"enabled": False}, headers=headers).status_code
            == 403
        )

    def test_normal_user_can_read(self, client, normal_user):
        headers = normal_user["headers"]
        assert client.get("/api/items", headers=headers).status_code == 200
        assert client.get("/api/sites", headers=headers).status_code == 200


class TestPasswordChange:
    def test_changing_password_revokes_existing_tokens(self, client, normal_user):
        headers = normal_user["headers"]
        assert client.get("/api/auth/me", headers=headers).status_code == 200

        response = client.post(
            "/api/auth/password",
            json={
                "current_password": "viewer-long-passphrase",
                "new_password": "a-brand-new-passphrase",
            },
            headers=headers,
        )
        assert response.status_code == 204
        # The old token was minted under the previous token_version.
        assert client.get("/api/auth/me", headers=headers).status_code == 401

        fresh = client.post(
            "/api/auth/login",
            json={"username": "viewer", "password": "a-brand-new-passphrase"},
        )
        assert fresh.status_code == 200

    def test_wrong_current_password(self, client, normal_user):
        response = client.post(
            "/api/auth/password",
            json={"current_password": "nope", "new_password": "another-passphrase-x"},
            headers=normal_user["headers"],
        )
        assert response.status_code == 400

    def test_weak_new_password(self, client, normal_user):
        """Rejected by the password policy (400), not by schema bounds (422).

        The minimum is configurable, so it cannot live in the Pydantic model.
        """
        response = client.post(
            "/api/auth/password",
            json={"current_password": "viewer-long-passphrase", "new_password": "short"},
            headers=normal_user["headers"],
        )
        assert response.status_code == 400
        assert "12 characters" in response.json()["detail"]


class TestUserManagement:
    def test_create_and_list(self, client, admin_headers):
        response = client.post(
            "/api/users",
            json={
                "username": "collector",
                "email": "collector@example.com",
                "password": "collector-passphrase",
                "role": "normal",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        usernames = [u["username"] for u in client.get("/api/users", headers=admin_headers).json()]
        assert "collector" in usernames

    def test_duplicate_username_conflicts(self, client, admin_headers, normal_user):
        response = client.post(
            "/api/users",
            json={
                "username": "viewer",
                "email": "other@example.com",
                "password": "yet-another-passphrase",
            },
            headers=admin_headers,
        )
        assert response.status_code == 409

    def test_weak_password_rejected(self, client, admin_headers):
        response = client.post(
            "/api/users",
            json={"username": "weak", "email": "w@example.com", "password": "password1234"},
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_cannot_delete_yourself(self, client, admin_headers):
        me = client.get("/api/auth/me", headers=admin_headers).json()
        response = client.delete(f"/api/users/{me['id']}", headers=admin_headers)
        assert response.status_code == 409

    def test_cannot_demote_the_last_admin(self, client, admin_headers):
        me = client.get("/api/auth/me", headers=admin_headers).json()
        response = client.patch(
            f"/api/users/{me['id']}", json={"role": "normal"}, headers=admin_headers
        )
        assert response.status_code == 409

    def test_a_disabled_admin_can_be_deleted(self, client, admin_headers):
        """The floor is on *active* administrators.

        Deleting an admin who is already disabled cannot leave the system
        without one, so the last-admin guard must not block it.
        """
        created = client.post(
            "/api/users",
            json={
                "username": "spare-admin",
                "email": "spare@example.com",
                "password": "spare-admin-passphrase",
                "role": "admin",
                "is_active": False,
            },
            headers=admin_headers,
        )
        assert created.status_code == 201
        user_id = created.json()["id"]

        assert client.delete(f"/api/users/{user_id}", headers=admin_headers).status_code == 204

    def test_a_disabled_admin_can_be_demoted(self, client, admin_headers):
        created = client.post(
            "/api/users",
            json={
                "username": "spare-admin-2",
                "email": "spare2@example.com",
                "password": "spare-admin-passphrase",
                "role": "admin",
                "is_active": False,
            },
            headers=admin_headers,
        )
        user_id = created.json()["id"]
        response = client.patch(
            f"/api/users/{user_id}", json={"role": "normal"}, headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["role"] == "normal"

    def test_the_last_active_admin_still_cannot_be_deleted(
        self, client, admin_headers, normal_user
    ):
        """The guard must still hold for the case it was written for."""
        promoted = client.patch(
            f"/api/users/{normal_user['user']['id']}",
            json={"role": "admin"},
            headers=admin_headers,
        )
        assert promoted.status_code == 200
        me = client.get("/api/auth/me", headers=admin_headers).json()

        # Two active admins now, so removing one is allowed...
        assert client.delete(f"/api/users/{me['id']}", headers=admin_headers).status_code == 409

    def test_admin_reset_signs_the_user_out(self, client, admin_headers, normal_user):
        headers = normal_user["headers"]
        response = client.patch(
            f"/api/users/{normal_user['user']['id']}",
            json={"password": "reset-by-the-admin-x"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 401


class TestTheSignInLogNeverQuotesTheRequest:
    """A failed sign-in names the account it matched, or nothing.

    The submitted string used to be passed through an allowlist, on the belief
    that a guard was a barrier a taint tracker would respect. It is not — the
    guard returns the original string on the matching branch — so the value
    reaching the log was still the one from the request, and CodeQL went on
    reporting log injection because it was right to.

    The rule is asserted rather than the log line. What matters is where the
    name comes from, and testing that through a logging handler tests the
    logging framework instead.
    """

    def test_a_real_account_is_named(self, seeded):
        user = seeded.query(User).filter(User.username == "admin").one()
        assert auth.account_label(user) == "admin"

    def test_and_an_unknown_one_is_not_named_at_all(self):
        assert auth.account_label(None) == auth.NO_SUCH_ACCOUNT

    def test_nothing_the_request_said_can_reach_it(self):
        """The label is either a column from the database or a literal. There
        is no third case, so there is nowhere for a forged record to enter."""
        forged = "admin\nWARNING milsurp.auth: Successful sign-in for root"
        assert forged not in auth.account_label(None)

    def test_the_failing_request_still_answers_401(self, client):
        """The rule above is only worth anything on the path that uses it."""
        auth._attempts.clear()
        response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect username or password."
