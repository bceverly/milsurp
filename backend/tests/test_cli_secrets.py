"""`milsurp secrets`: generate credentials without ever showing them.

The command used to print the two values for the operator to paste. That is the
obvious design and it puts two live credentials into a terminal, a scrollback
buffer, and whatever records that terminal. It writes them to the file they are
for instead, which is fewer steps as well as fewer copies.
"""

from __future__ import annotations

import argparse

import cli
import pytest

SAMPLE = """\
security:
  password_pepper: "CHANGE-ME-run-make-secrets"
  jwt_secret: "CHANGE-ME-run-make-secrets"
  min_password_length: 12
"""


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(cli, "find_config_file", lambda: path)
    return path


def run(force: bool = False) -> int:
    return cli.cmd_secrets(argparse.Namespace(force=force))


class TestWritingTheSecrets:
    def test_placeholders_are_replaced_with_real_values(self, config_file):
        assert run() == 0
        text = config_file.read_text()
        assert "CHANGE-ME" not in text
        for name in ("password_pepper", "jwt_secret"):
            value = _value_of(text, name)
            assert len(value) >= 32
        # ...and the two are different from each other.
        assert _value_of(text, "password_pepper") != _value_of(text, "jwt_secret")

    def test_the_rest_of_the_file_is_left_alone(self, config_file):
        run()
        assert "min_password_length: 12" in config_file.read_text()

    def test_the_file_is_left_readable_only_by_its_owner(self, config_file):
        run()
        assert config_file.stat().st_mode & 0o777 == 0o600

    def test_nothing_secret_reaches_the_output(self, config_file, capsys):
        """The whole point: the values exist only in the file."""
        run()
        printed = capsys.readouterr().out
        text = config_file.read_text()
        for name in ("password_pepper", "jwt_secret"):
            assert _value_of(text, name) not in printed
        assert "deliberately not printed" in printed


class TestNotClobberingLiveSecrets:
    """Rotating either of these is destructive, and silently so."""

    def test_it_refuses_when_they_are_already_set(self, config_file, capsys):
        run()
        before = config_file.read_text()

        assert run() == 1
        assert config_file.read_text() == before
        assert "already has" in capsys.readouterr().err

    def test_force_rotates_them(self, config_file):
        run()
        before = _value_of(config_file.read_text(), "jwt_secret")

        assert run(force=True) == 0
        assert _value_of(config_file.read_text(), "jwt_secret") != before

    def test_a_placeholder_does_not_count_as_set(self, config_file):
        """Which is the bug an earlier version of the check had.

        An optional quote plus a negative lookahead let the regex backtrack
        past the quote and read "CHANGE-ME" as a real secret, so a fresh
        install could not generate its own secrets.
        """
        assert run() == 0

    def test_an_empty_value_does_not_count_as_set(self, config_file):
        config_file.write_text("security:\n  password_pepper:\n  jwt_secret:\n", encoding="utf-8")
        assert run() == 0
        assert "CHANGE-ME" not in config_file.read_text()


class TestWhenThereIsNoConfig:
    def test_it_says_so_rather_than_failing_obscurely(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "find_config_file", lambda: None)
        assert run() == 1
        assert "No configuration file found" in capsys.readouterr().err


def _value_of(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith(f"{name}:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    raise AssertionError(f"{name} not found")
