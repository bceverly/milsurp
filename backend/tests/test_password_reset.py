"""One-time password reset links, sent by an administrator.

The roadmap parked *self-service* reset on purpose: it needs an endpoint that
hands tokens to anybody who names an address. This keeps the issuing side
authenticated, and it is not new power either way — an admin can already set
another account's password through PATCH. What changes is that the admin never
learns the new password.

What is pinned here is mostly the ways a live credential in a mailbox goes
wrong: used twice, still working an hour later, two of them at once, or good
enough to walk past a second factor.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from app import totp
from app.models import PasswordResetToken, User, utcnow
from app.services import passwordreset, twofactor

VIEWER = "viewer"
VIEWER_PASSWORD = "viewer-long-passphrase"
NEW_PASSWORD = "a-brand-new-long-passphrase"


@pytest.fixture
def viewer(seeded, normal_user):
    return seeded.query(User).filter_by(username=VIEWER).one()


class TestIssuing:
    def test_a_link_is_minted_and_works(self, seeded, viewer, app_config):
        issued = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        assert passwordreset.find_valid(seeded, issued.token, app_config) is not None

    def test_the_token_is_never_stored_in_the_clear(self, seeded, viewer, app_config):
        """While it is live the token *is* the password."""
        issued = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        stored = [row.token_hash for row in seeded.query(PasswordResetToken).all()]
        assert issued.token not in stored
        assert not any(issued.token in blob for blob in stored)

    def test_issuing_again_supersedes_the_first(self, seeded, viewer, app_config):
        """An admin who presses the button twice — because the first mail did
        not arrive, which is the ordinary reason — must not leave two live
        credentials in a mailbox, the older of which nobody is watching for."""
        first = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        second = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()

        assert passwordreset.find_valid(seeded, first.token, app_config) is None
        assert passwordreset.find_valid(seeded, second.token, app_config) is not None

    def test_the_url_points_at_this_deployment(self, seeded, viewer, app_config):
        issued = passwordreset.issue(seeded, viewer, None, app_config)
        assert issued.url.endswith(f"/reset/{issued.token}")

    def test_who_sent_it_is_recorded(self, seeded, viewer, app_config):
        """ "Who reset this account and when" is the first question after an
        account behaves oddly."""
        admin = seeded.query(User).filter_by(username="admin").one()
        passwordreset.issue(seeded, viewer, admin, app_config)
        seeded.commit()
        assert seeded.query(PasswordResetToken).one().issued_by_id == admin.id


class TestRedeeming:
    def test_it_sets_the_password(self, seeded, viewer, app_config):
        from app.security import verify_password

        issued = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        user = passwordreset.redeem(seeded, issued.token, NEW_PASSWORD, app_config)
        seeded.commit()
        assert user is not None
        assert verify_password(NEW_PASSWORD, user.password_hash, app_config)

    def test_and_only_once(self, seeded, viewer, app_config):
        issued = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        assert passwordreset.redeem(seeded, issued.token, NEW_PASSWORD, app_config) is not None
        seeded.commit()
        assert (
            passwordreset.redeem(seeded, issued.token, "another-long-passphrase", app_config)
            is None
        )

    def test_every_open_session_is_signed_out(self, seeded, viewer, app_config):
        """A reset is usually somebody saying they have lost control of
        something. Leaving live tokens alone would make this a smaller fix than
        it looks."""
        was = viewer.token_version
        issued = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        passwordreset.redeem(seeded, issued.token, NEW_PASSWORD, app_config)
        seeded.commit()
        assert viewer.token_version == was + 1

    def test_an_expired_link_is_refused(self, seeded, viewer, app_config):
        issued = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        row = seeded.query(PasswordResetToken).one()
        row.expires_at = utcnow() - timedelta(minutes=1)
        seeded.commit()
        assert passwordreset.redeem(seeded, issued.token, NEW_PASSWORD, app_config) is None

    @pytest.mark.parametrize("token", ["", "not-a-real-token", "x" * 43])
    def test_nor_anything_that_is_not_a_link(self, seeded, viewer, token, app_config):
        passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()
        assert passwordreset.redeem(seeded, token, NEW_PASSWORD, app_config) is None


class TestItDoesNotWalkPastTwoFactor:
    def test_an_account_with_an_authenticator_still_needs_it(
        self, client, seeded, viewer, app_config
    ):
        """A reset link that skipped the second factor would make a compromised
        mailbox enough to defeat it, which is most of what it is for."""
        twofactor.begin_enrollment(viewer, app_config)
        secret = totp.unseal(viewer.totp_secret, app_config)
        twofactor.confirm_enrollment(seeded, viewer, totp.code_at(secret, time.time()), app_config)
        issued = passwordreset.issue(seeded, viewer, None, app_config)
        seeded.commit()

        passwordreset.redeem(seeded, issued.token, NEW_PASSWORD, app_config)
        seeded.commit()

        # The new password alone gets the "I need a code" answer, not a token.
        response = client.post(
            "/api/auth/login", json={"username": VIEWER, "password": NEW_PASSWORD}
        )
        assert response.json().get("two_factor_required") is True
        assert twofactor.is_enabled(viewer) is True


class TestOverHttp:
    def test_only_an_admin_can_send_one(self, client, normal_user, viewer):
        response = client.post(f"/api/users/{viewer.id}/reset-link", headers=normal_user["headers"])
        assert response.status_code == 403

    def test_an_admin_can(self, client, admin_headers, viewer):
        response = client.post(f"/api/users/{viewer.id}/reset-link", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == viewer.email
        # Email is off in the test configuration, so the link comes back for
        # the admin to pass on rather than the button silently doing nothing.
        assert body["sent"] is False
        assert "/reset/" in body["url"]

    def test_checking_a_link_says_whose_it_is(self, client, admin_headers, viewer):
        url = client.post(f"/api/users/{viewer.id}/reset-link", headers=admin_headers).json()["url"]
        token = url.rsplit("/", 1)[-1]
        body = client.get(f"/api/auth/reset/{token}").json()
        assert body == {"valid": True, "username": VIEWER}

    def test_a_bad_one_says_only_no(self, client):
        """Which is the whole of what a prober gets."""
        assert client.get("/api/auth/reset/nonsense").json() == {
            "valid": False,
            "username": None,
        }

    def test_redeeming_works_without_signing_in(self, client, admin_headers, viewer):
        url = client.post(f"/api/users/{viewer.id}/reset-link", headers=admin_headers).json()["url"]
        token = url.rsplit("/", 1)[-1]

        response = client.post(
            "/api/auth/reset", json={"token": token, "new_password": NEW_PASSWORD}
        )
        assert response.status_code == 204

        signed_in = client.post(
            "/api/auth/login", json={"username": VIEWER, "password": NEW_PASSWORD}
        )
        assert "access_token" in signed_in.json()

    def test_a_password_that_breaks_the_rules_does_not_spend_the_link(
        self, client, admin_headers, viewer
    ):
        """Somebody who has just been sent a link and typed something too short
        should get another go, not another email."""
        url = client.post(f"/api/users/{viewer.id}/reset-link", headers=admin_headers).json()["url"]
        token = url.rsplit("/", 1)[-1]

        assert (
            client.post(
                "/api/auth/reset", json={"token": token, "new_password": "short"}
            ).status_code
            == 400
        )
        assert client.get(f"/api/auth/reset/{token}").json()["valid"] is True

    def test_a_disabled_account_is_refused(self, client, admin_headers, viewer, seeded):
        viewer.is_active = False
        seeded.commit()
        response = client.post(f"/api/users/{viewer.id}/reset-link", headers=admin_headers)
        assert response.status_code == 409
