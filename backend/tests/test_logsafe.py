"""Untrusted values must not be able to forge log records."""

from __future__ import annotations

import logging

import pytest

from app.logsafe import MAX_LOGGED_LENGTH, scrub


class TestScrub:
    def test_ordinary_text_is_untouched(self):
        assert scrub("alice") == "alice"
        assert scrub("O'Brien-Smith jr.") == "O'Brien-Smith jr."

    def test_non_ascii_prose_survives(self):
        # Accented names and non-Latin scripts are printable and must not be
        # mangled: this is a sanitizer, not an ASCII filter.
        assert scrub("José Müller") == "José Müller"
        assert scrub("Ольга") == "Ольга"

    @pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
    def test_a_newline_cannot_start_a_new_record(self, newline):
        forged = f"attacker{newline}INFO Successful sign-in for admin"
        cleaned = scrub(forged)
        assert "\n" not in cleaned
        assert "\r" not in cleaned
        # The attempt stays legible in the log rather than vanishing.
        assert "INFO Successful sign-in for admin" in cleaned

    def test_control_characters_become_visible_escapes(self):
        assert scrub("bob\x00") == "bob\\u0000"
        # An ANSI escape could otherwise repaint the terminal of whoever tails
        # the log file.
        assert scrub("bob\x1b[2J") == "bob\\u001b[2J"

    def test_long_values_are_capped(self):
        cleaned = scrub("x" * 5000)
        assert cleaned.startswith("x" * MAX_LOGGED_LENGTH)
        assert cleaned.endswith("…(truncated)")
        assert len(cleaned) < 200

    def test_the_limit_is_adjustable(self):
        assert scrub("abcdef", limit=3) == "abc…(truncated)"

    def test_non_strings_are_accepted(self):
        assert scrub(42) == "42"
        assert scrub(None) == "None"


class TestEndpointsUseIt:
    """The sanitizer is only worth anything if it is actually on the path."""

    def test_a_failed_sign_in_logs_one_line(self, client, caplog):
        with caplog.at_level(logging.WARNING, logger="milsurp.auth"):
            response = client.post(
                "/api/auth/login",
                json={
                    "username": "admin\nWARNING Failed sign-in for someone-else",
                    "password": "wrong-password-entirely",
                },
            )
        assert response.status_code in (401, 422)
        for record in caplog.records:
            assert "\n" not in record.getMessage()
