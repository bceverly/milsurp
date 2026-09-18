"""Turning two-factor on, checking it, and getting back in without the phone.

The admin sign-in is reachable from the internet and a password was the only
thing in front of it. What is pinned here is mostly the ways this can go wrong
for the person who owns the account rather than for an attacker: a lockout is
the likelier failure, and an application whose recovery story is "find somebody
with shell access" cannot afford one.
"""

from __future__ import annotations

import time

import pytest

from app import totp
from app.models import RecoveryCode, User, UserRole
from app.security import hash_password
from app.services import twofactor


@pytest.fixture
def user(clean_db):
    row = User(
        username="bceverly",
        email="real@theeverlys.test",
        password_hash=hash_password("x" * 16),
        role=UserRole.ADMIN,
    )
    clean_db.add(row)
    clean_db.commit()
    return row


def _code(user, config, offset: float = 0.0) -> str:
    return totp.code_at(totp.unseal(user.totp_secret, config), time.time() + offset)


class TestEnrollmentIsTwoSteps:
    def test_starting_issues_a_secret_without_turning_it_on(self, clean_db, user, app_config):
        """The gap is the point. Collapsing these into one step means a secret
        mistyped into an authenticator, or a tab closed halfway, locks the
        account out."""
        secret, uri = twofactor.begin_enrollment(user, app_config)
        clean_db.commit()
        assert secret in uri
        assert user.totp_secret is not None
        assert twofactor.is_enabled(user) is False

    def test_a_correct_code_turns_it_on(self, clean_db, user, app_config):
        twofactor.begin_enrollment(user, app_config)
        codes = twofactor.confirm_enrollment(clean_db, user, _code(user, app_config), app_config)
        clean_db.commit()
        assert twofactor.is_enabled(user) is True
        assert len(codes) == twofactor.RECOVERY_CODES

    def test_a_wrong_one_leaves_everything_alone(self, clean_db, user, app_config):
        """A mistyped digit during enrollment is the ordinary case and must not
        clear the secret somebody has just scanned."""
        twofactor.begin_enrollment(user, app_config)
        stored = user.totp_secret
        assert twofactor.confirm_enrollment(clean_db, user, "000000", app_config) is None
        assert twofactor.is_enabled(user) is False
        assert user.totp_secret == stored

    def test_starting_again_replaces_the_secret(self, clean_db, user, app_config):
        """Which is what somebody who closed the tab will do."""
        first, _uri = twofactor.begin_enrollment(user, app_config)
        second, _uri = twofactor.begin_enrollment(user, app_config)
        assert first != second
        assert totp.unseal(user.totp_secret, app_config) == second


class TestSigningIn:
    @pytest.fixture
    def enrolled(self, clean_db, user, app_config):
        twofactor.begin_enrollment(user, app_config)
        codes = twofactor.confirm_enrollment(clean_db, user, _code(user, app_config), app_config)
        clean_db.commit()
        return user, codes

    def test_the_code_from_the_phone(self, clean_db, enrolled, app_config):
        user, _codes = enrolled
        assert twofactor.check(clean_db, user, _code(user, app_config), app_config) is True

    def test_a_wrong_code(self, clean_db, enrolled, app_config):
        user, _codes = enrolled
        assert twofactor.check(clean_db, user, "000000", app_config) is False

    def test_nothing_at_all(self, clean_db, enrolled, app_config):
        user, _codes = enrolled
        assert twofactor.check(clean_db, user, "", app_config) is False


class TestRecoveryCodes:
    @pytest.fixture
    def enrolled(self, clean_db, user, app_config):
        twofactor.begin_enrollment(user, app_config)
        codes = twofactor.confirm_enrollment(clean_db, user, _code(user, app_config), app_config)
        clean_db.commit()
        return user, codes

    def test_one_gets_you_in(self, clean_db, enrolled, app_config):
        """At the same prompt as a TOTP code, not behind a separate link:
        somebody reaching for one of these has already lost their phone."""
        user, codes = enrolled
        assert twofactor.check(clean_db, user, codes[0], app_config) is True

    def test_and_only_once(self, clean_db, enrolled, app_config):
        user, codes = enrolled
        assert twofactor.check(clean_db, user, codes[0], app_config) is True
        clean_db.commit()
        assert twofactor.check(clean_db, user, codes[0], app_config) is False

    def test_the_others_still_work(self, clean_db, enrolled, app_config):
        user, codes = enrolled
        twofactor.check(clean_db, user, codes[0], app_config)
        clean_db.commit()
        assert twofactor.check(clean_db, user, codes[1], app_config) is True

    def test_they_are_never_stored_in_the_clear(self, clean_db, enrolled):
        """Password-equivalent: one of these alone is the whole second factor."""
        _user, codes = enrolled
        stored = [row.code_hash for row in clean_db.query(RecoveryCode).all()]
        for code in codes:
            assert code not in stored
            assert not any(code in blob for blob in stored)

    def test_written_down_by_hand_and_typed_back(self, clean_db, enrolled, app_config):
        """Lower case, spaces instead of the hyphen, a stray trailing space —
        all of which happen when somebody is already locked out and unhappy."""
        user, codes = enrolled
        mangled = codes[0].lower().replace("-", " ") + " "
        assert twofactor.check(clean_db, user, mangled, app_config) is True

    def test_how_many_are_left_is_answerable(self, clean_db, enrolled, app_config):
        user, codes = enrolled
        assert twofactor.recovery_codes_left(clean_db, user) == twofactor.RECOVERY_CODES
        twofactor.check(clean_db, user, codes[0], app_config)
        clean_db.commit()
        assert twofactor.recovery_codes_left(clean_db, user) == twofactor.RECOVERY_CODES - 1

    def test_they_contain_no_ambiguous_characters(self, enrolled):
        """They are read off paper: I and 1, O and 0 are the pairs that cost a
        locked-out person their remaining patience."""
        _user, codes = enrolled
        for code in codes:
            assert not set(code) & set("IO01")


class TestTurningItOff:
    def test_the_secret_goes_too(self, clean_db, user, app_config):
        """Not just the flag. A stale secret means turning two-factor back on
        later silently re-enables a code somebody's old phone can produce."""
        twofactor.begin_enrollment(user, app_config)
        twofactor.confirm_enrollment(clean_db, user, _code(user, app_config), app_config)
        clean_db.commit()

        twofactor.disable(clean_db, user)
        clean_db.commit()
        assert user.totp_secret is None
        assert twofactor.is_enabled(user) is False

    def test_and_so_do_the_recovery_codes(self, clean_db, user, app_config):
        twofactor.begin_enrollment(user, app_config)
        twofactor.confirm_enrollment(clean_db, user, _code(user, app_config), app_config)
        clean_db.commit()

        twofactor.disable(clean_db, user)
        clean_db.commit()
        assert clean_db.query(RecoveryCode).count() == 0
