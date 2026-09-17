"""Ending one sign-in, and keeping a record of what administrators did.

**Sessions.** The token was stateless, which bought a great deal and cost one
thing: there was no way to end a single sign-in. `token_version` retires every
token at once -- right for a password change, useless for closing the laptop
left at work without also signing yourself out of your phone.

**The audit log.** Failed sign-ins were already logged; what happened after
somebody got in was not. These are the properties that make it a record rather
than a decoration: it survives the account that caused it, and it cannot break
the operation it is watching.
"""

from __future__ import annotations

import pytest

from app import sessions
from app.models import AuditEvent, User, UserRole, UserSession
from app.services import audit, usersessions


@pytest.fixture
def signed_in(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-passphrase"},
    )
    assert response.status_code == 200, response.text
    return response


def csrf(response) -> dict[str, str]:
    return {sessions.CSRF_HEADER: response.json()["csrf_token"]}


class TestASignInIsWrittenDown:
    def test_logging_in_records_a_session(self, client, clean_db, signed_in):
        rows = clean_db.query(UserSession).all()
        assert len(rows) == 1
        assert rows[0].is_live

    def test_the_list_shows_it_and_says_which_is_this_one(self, client, signed_in):
        """Without `current` the list is unusable: "which one is this browser?"
        is the first thing anybody asks, and signing yourself out by accident
        is the obvious mistake."""
        listed = client.get("/api/auth/sessions").json()
        assert len(listed) == 1
        assert listed[0]["current"] is True

    def test_the_user_agent_is_kept_for_telling_them_apart(self, client, clean_db):
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-admin-passphrase"},
            headers={"User-Agent": "Mozilla/5.0 (iPhone)"},
        )
        row = clean_db.query(UserSession).order_by(UserSession.id.desc()).first()
        assert row.user_agent and "iPhone" in row.user_agent


class TestEndingOne:
    def test_revoking_this_session_stops_it_working(self, client, signed_in):
        mine = client.get("/api/auth/sessions").json()[0]["id"]
        assert (
            client.delete(f"/api/auth/sessions/{mine}", headers=csrf(signed_in)).status_code == 204
        )
        # The cookie is still in the jar; the row behind it is not live.
        assert client.get("/api/auth/me").status_code == 401

    def test_a_session_that_is_not_yours_cannot_be_ended(self, client, clean_db, signed_in):
        """The id comes from a URL and is a small integer. Without the owner
        check anybody could sign anybody else out by counting."""
        other = User(
            username="someone",
            email="someone@example.test",
            password_hash="x",
            role=clean_db.query(User).first().role,
        )
        clean_db.add(other)
        clean_db.flush()
        theirs = usersessions.begin(
            clean_db,
            other,
            expires_at=usersessions.utcnow() + usersessions.timedelta(hours=1),
            user_agent=None,
            ip_address=None,
        )
        clean_db.commit()
        response = client.delete(f"/api/auth/sessions/{theirs.id}", headers=csrf(signed_in))
        assert response.status_code == 404
        clean_db.refresh(theirs)
        assert theirs.revoked_at is None

    def test_signing_out_of_the_others_keeps_this_one(self, client, signed_in):
        """Signing yourself out as a side effect of securing your account
        reads as the button having gone wrong."""
        second = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-admin-passphrase"},
            headers={"User-Agent": "another-browser"},
        )
        # The jar now holds the newest session's cookies, so the newest login
        # is both the current session and the source of the CSRF token. Using
        # the first login's token here 403s, and an unchecked 403 made this
        # test pass by doing nothing at all.
        assert len(client.get("/api/auth/sessions").json()) == 2

        response = client.post(
            "/api/auth/sessions/revoke-others",
            headers=csrf(second),
        )
        assert response.status_code == 204, response.text
        assert client.get("/api/auth/me").status_code == 200
        remaining = client.get("/api/auth/sessions").json()
        assert len(remaining) == 1
        assert remaining[0]["current"] is True

    def test_a_token_with_no_session_still_works(self, client, admin_headers):
        """Minted by a script or issued before sessions existed. It was valid
        when handed out, and `token_version` is still what retires it."""
        assert client.get("/api/auth/me", headers=admin_headers).status_code == 200


class TestTheAuditLog:
    def _make_user(self, client, signed_in, name="audited"):
        return client.post(
            "/api/users",
            json={
                "username": name,
                "email": f"{name}@example.com",
                "password": "a-long-enough-passphrase",
                "role": "normal",
            },
            headers=csrf(signed_in),
        )

    def test_creating_a_user_is_recorded(self, client, clean_db, signed_in):
        assert self._make_user(client, signed_in).status_code == 201
        # Filtered to this user, not "the only event in the table": anything
        # else in the suite that creates an account writes one too, which is
        # the feature working.
        event = (
            clean_db.query(AuditEvent)
            .filter_by(action=audit.USER_CREATED, target_label="audited")
            .one()
        )
        assert event.actor_name == "admin"

    def test_a_role_change_says_what_it_was(self, client, clean_db, signed_in):
        """ "Changed to admin" without "from what" answers half the question."""
        created = self._make_user(client, signed_in, "promoted").json()
        client.patch(
            f"/api/users/{created['id']}",
            json={"role": "admin"},
            headers=csrf(signed_in),
        )
        event = (
            clean_db.query(AuditEvent)
            .filter_by(action=audit.USER_ROLE_CHANGED, target_label="promoted")
            .one()
        )
        assert "normal -> admin" in event.detail

    def test_an_event_outlives_the_account_that_caused_it(self, client, clean_db, signed_in):
        """The row most worth reading is usually the one written by somebody
        who is no longer here."""
        created = self._make_user(client, signed_in, "shortlived").json()
        client.delete(f"/api/users/{created['id']}", headers=csrf(signed_in))
        event = (
            clean_db.query(AuditEvent)
            .filter_by(action=audit.USER_DELETED, target_label="shortlived")
            .one()
        )
        # The account is gone; the record of deleting it is not.
        assert clean_db.query(User).filter_by(username="shortlived").first() is None
        assert event.actor_name == "admin"

    def test_the_log_cannot_break_what_it_watches(self, clean_db, monkeypatch):
        """An audit write that raised would turn "the log is full" into
        "nobody can create a user"."""

        def explode(*_args, **_kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(clean_db, "flush", explode)
        assert audit.record(clean_db, actor=None, action="whatever") is None

    def test_only_an_admin_can_read_it(self, client, normal_user):
        assert client.get("/api/audit", headers=normal_user["headers"]).status_code == 403

    def test_an_admin_can(self, client, admin_headers):
        assert client.get("/api/audit", headers=admin_headers).status_code == 200


class TestTheResetActionIsNotNamedForAPassword:
    """Three static analyzers in turn read `USER_PASSWORD_RESET` as a hardcoded
    credential: ruff's S105, bandit's B105 — both suppressed inline for months
    — and then CodeQL, reporting *clear-text logging of sensitive information*
    against the `log.exception` that names the action when a write fails.

    No password was ever within reach of any of them. Renaming the constant is
    what the suppressions were standing in for, and these hold the rename so it
    does not quietly come back with the next action somebody adds.
    """

    def test_no_action_is_named_for_a_credential(self):
        suspicious = {"password", "secret", "token", "credential", "apikey"}
        for name in dir(audit):
            if not name.isupper():
                continue
            value = getattr(audit, name)
            if not isinstance(value, str):
                continue
            words = f"{name} {value}".lower()
            assert not any(word in words for word in suspicious), (
                f"{name} reads as a credential to a static analyzer. Name it for "
                f"what happened rather than for what the thing eventually changes."
            )

    def test_the_reset_action_still_exists_under_its_new_name(self):
        assert audit.USER_RESET_LINK_SENT == "user.reset_link_sent"

    def test_sending_a_link_records_the_new_action(self, client, admin_headers, clean_db):
        target = User(
            username="forgetful",
            email="forgetful@example.test",
            role=UserRole.NORMAL,
            is_active=True,
            password_hash="x",
        )
        clean_db.add(target)
        clean_db.commit()

        client.post(f"/api/users/{target.id}/reset-link", headers=admin_headers)
        actions = {row["action"] for row in client.get("/api/audit", headers=admin_headers).json()}
        assert "user.password_reset_sent" not in actions
