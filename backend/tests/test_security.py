"""Password hashing, token issuance and the password policy."""

from __future__ import annotations

import pytest

from app.security import (
    PasswordPolicyError,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    min_password_length,
    needs_rehash,
    password_requirements,
    validate_password,
    verify_password,
)


class TestHashing:
    def test_hash_is_argon2id_and_verifies(self, app_config):
        digest = hash_password("correct-horse-battery", app_config)
        # The PHC prefix is what proves the algorithm actually in use.
        assert digest.startswith("$argon2id$")
        assert verify_password("correct-horse-battery", digest, app_config)

    def test_wrong_password_is_rejected(self, app_config):
        digest = hash_password("correct-horse-battery", app_config)
        assert not verify_password("wrong-horse-battery", digest, app_config)

    def test_same_password_hashes_differently(self, app_config):
        """Each hash carries its own random salt, so two are never equal."""
        first = hash_password("identical-passphrase", app_config)
        second = hash_password("identical-passphrase", app_config)
        assert first != second
        assert verify_password("identical-passphrase", first, app_config)
        assert verify_password("identical-passphrase", second, app_config)

    def test_pepper_changes_the_result(self, app_config):
        """A stolen database is useless without the pepper from the config."""
        import dataclasses

        digest = hash_password("shared-passphrase", app_config)
        other = dataclasses.replace(
            app_config,
            security=dataclasses.replace(
                app_config.security, password_pepper="a-completely-different-pepper"
            ),
        )
        assert not verify_password("shared-passphrase", digest, other)

    def test_garbage_hash_does_not_raise(self, app_config):
        assert not verify_password("anything", "not-a-hash", app_config)

    def test_needs_rehash_detects_a_bad_hash(self, app_config):
        assert needs_rehash("not-a-hash", app_config)
        assert not needs_rehash(hash_password("x" * 20, app_config), app_config)


class TestPasswordPolicy:
    @pytest.mark.parametrize(
        "password",
        ["short", "elevenchars", "password12345", "Changeme1234", "  padded  "],
    )
    def test_weak_passwords_rejected(self, password):
        with pytest.raises(PasswordPolicyError):
            validate_password(password)

    @pytest.mark.parametrize(
        "password",
        ["a-perfectly-fine-passphrase", "Tk9!zQr2vLm4Xw", "correct horse battery staple"],
    )
    def test_good_passwords_accepted(self, password):
        validate_password(password)


class TestConfigurablePasswordLength:
    """`security.min_password_length` drives the policy."""

    def test_default_is_twelve(self, app_config):
        assert min_password_length(app_config) == 12
        validate_password("a" * 12, app_config)
        with pytest.raises(PasswordPolicyError, match="12 characters"):
            validate_password("a" * 11, app_config)

    def test_a_higher_minimum_is_enforced(self, app_config):
        import dataclasses

        strict = dataclasses.replace(
            app_config,
            security=dataclasses.replace(app_config.security, min_password_length=20),
        )
        assert min_password_length(strict) == 20
        with pytest.raises(PasswordPolicyError, match="20 characters"):
            validate_password("a" * 19, strict)
        validate_password("a" * 20, strict)

    def test_a_lower_minimum_is_honoured(self, app_config):
        """A configured 8 must not be silently overridden by a hard-coded 12."""
        import dataclasses

        relaxed = dataclasses.replace(
            app_config,
            security=dataclasses.replace(app_config.security, min_password_length=8),
        )
        validate_password("abcdefgh", relaxed)
        with pytest.raises(PasswordPolicyError, match="8 characters"):
            validate_password("abcdefg", relaxed)

    def test_the_other_rules_still_apply(self, app_config):
        import dataclasses

        relaxed = dataclasses.replace(
            app_config,
            security=dataclasses.replace(app_config.security, min_password_length=4),
        )
        # Long enough now, but still a banned sequence.
        with pytest.raises(PasswordPolicyError, match="common word"):
            validate_password("password", relaxed)


class TestComplexityRules:
    """The rules in force are derived from the four config toggles."""

    @staticmethod
    def _with(app_config, **toggles):
        import dataclasses

        return dataclasses.replace(
            app_config, security=dataclasses.replace(app_config.security, **toggles)
        )

    def test_all_off_accepts_a_long_lowercase_passphrase(self, app_config):
        """The default: length alone. A passphrase must not be rejected."""
        relaxed = self._with(app_config)
        validate_password("correct horse battery staple", relaxed)

    def test_uppercase_required(self, app_config):
        config = self._with(app_config, require_uppercase=True)
        with pytest.raises(PasswordPolicyError, match="an uppercase letter"):
            validate_password("all lowercase here", config)
        validate_password("All lowercase here", config)

    def test_lowercase_required(self, app_config):
        config = self._with(app_config, require_lowercase=True)
        with pytest.raises(PasswordPolicyError, match="a lowercase letter"):
            validate_password("ALL UPPERCASE HERE", config)
        validate_password("ALL UPPERCASE HERe", config)

    def test_numeric_required(self, app_config):
        config = self._with(app_config, require_numeric=True)
        with pytest.raises(PasswordPolicyError, match="a number"):
            validate_password("no digits in here", config)
        validate_password("one digit in here 7", config)

    def test_special_required(self, app_config):
        config = self._with(app_config, require_special=True)
        with pytest.raises(PasswordPolicyError, match="a special character"):
            validate_password("nospecialsatall1", config)
        validate_password("one special here!", config)

    def test_every_missing_class_is_reported_at_once(self, app_config):
        """Reporting one at a time makes the user guess repeatedly."""
        config = self._with(
            app_config, require_uppercase=True, require_numeric=True, require_special=True
        )
        with pytest.raises(PasswordPolicyError) as info:
            validate_password("justlowercaseletters", config)
        message = str(info.value)
        assert "an uppercase letter" in message
        assert "a number" in message
        assert "a special character" in message

    def test_all_four_together(self, app_config):
        config = self._with(
            app_config,
            require_uppercase=True,
            require_lowercase=True,
            require_numeric=True,
            require_special=True,
        )
        validate_password("Tr0ub4dor&3xtra", config)
        with pytest.raises(PasswordPolicyError):
            validate_password("correct-horse-battery-staple", config)

    @pytest.mark.parametrize("char", ["!", "@", "#", "-", "_", ".", " ", "~", "|"])
    def test_special_is_anything_not_alphanumeric(self, app_config, char):
        """A fixed punctuation list would reject perfectly good characters.

        The character is placed mid-string because leading and trailing
        whitespace is rejected separately, and a space is a valid special.
        """
        config = self._with(app_config, require_special=True)
        validate_password(f"abcdef{char}ghijklm", config)

    def test_requirements_text_matches_what_is_enforced(self, app_config):
        config = self._with(app_config, require_uppercase=True, require_special=True)
        rules = password_requirements(config)
        assert "at least 12 characters" in rules
        assert "an uppercase letter" in rules
        assert "a special character" in rules
        # Switched off, so absent.
        assert "a number" not in rules
        assert "a lowercase letter" not in rules


class TestTokens:
    def test_round_trip(self, app_config):
        token, expires = create_access_token(42, "admin", 3, app_config)
        payload = decode_access_token(token, app_config)
        assert payload["sub"] == "42"
        assert payload["role"] == "admin"
        assert payload["ver"] == 3
        assert expires.tzinfo is not None

    def test_expired_token_rejected(self, app_config):
        token, _ = create_access_token(1, "normal", 0, app_config, expires_minutes=-1)
        with pytest.raises(TokenError):
            decode_access_token(token, app_config)

    def test_token_signed_with_another_key_rejected(self, app_config):
        """A forged token must not validate against our secret."""
        import dataclasses

        other = dataclasses.replace(
            app_config,
            security=dataclasses.replace(
                app_config.security,
                # A full-length key: PyJWT warns below 32 bytes for SHA-256,
                # and the suite treats warnings as errors.
                jwt_secret="a-different-secret-cccccccccccccccccccccccccccccccc",
            ),
        )
        token, _ = create_access_token(1, "admin", 0, other)
        with pytest.raises(TokenError):
            decode_access_token(token, app_config)

    def test_tampered_token_rejected(self, app_config):
        token, _ = create_access_token(1, "normal", 0, app_config)
        header, payload, signature = token.split(".")
        with pytest.raises(TokenError):
            decode_access_token(f"{header}.{payload}.{signature[:-2]}xx", app_config)
