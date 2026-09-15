"""Seeding the first administrator, and never a second time.

The configuration file carries `admin.username`, `admin.email` and
`admin.password` so a fresh install has somebody to sign in as. Those three
lines are a bootstrap and not a source of truth, and the properties that make
them safe to leave lying in a file — or to delete — are pinned here.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from app.config import load_config
from app.models import User, UserRole
from app.security import hash_password
from app.services import bootstrap


def _config(body: str):
    directory = pathlib.Path(tempfile.mkdtemp())
    path = directory / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return load_config(path)


SEEDED = """
admin:
  username: admin
  email: someone@theeverlys.test
  password: "a-long-enough-passphrase"
"""


class TestItRunsOnce:
    def test_a_fresh_database_gets_an_administrator(self, clean_db):
        user = bootstrap.ensure_admin(clean_db, _config(SEEDED))
        assert user is not None
        assert user.role is UserRole.ADMIN
        assert user.email == "someone@theeverlys.test"

    def test_and_a_second_call_does_nothing(self, clean_db):
        bootstrap.ensure_admin(clean_db, _config(SEEDED))
        assert bootstrap.ensure_admin(clean_db, _config(SEEDED)) is None
        assert clean_db.query(User).filter_by(role=UserRole.ADMIN).count() == 1

    def test_a_changed_password_in_the_file_cannot_reset_a_live_account(self, clean_db):
        """The reason those lines are safe to leave in place. An operator who
        edits the file — or restores an old one — must not silently take over
        an account somebody is using."""
        user = bootstrap.ensure_admin(clean_db, _config(SEEDED))
        was = user.password_hash

        bootstrap.ensure_admin(
            clean_db,
            _config(SEEDED.replace("a-long-enough-passphrase", "a-completely-different-one")),
        )
        clean_db.refresh(user)
        assert user.password_hash == was

    def test_nor_change_the_address(self, clean_db):
        """Changing it on the Users page is the way, and the file must not
        quietly undo that on the next restart."""
        user = bootstrap.ensure_admin(clean_db, _config(SEEDED))
        user.email = "real@theeverlys.test"
        clean_db.commit()

        bootstrap.ensure_admin(clean_db, _config(SEEDED))
        clean_db.refresh(user)
        assert user.email == "real@theeverlys.test"

    def test_an_admin_created_by_hand_counts(self, clean_db):
        """Somebody who made their own admin and then deleted the config lines
        is in the ordinary case, not a broken one."""
        clean_db.add(
            User(
                username="bceverly",
                email="real@theeverlys.test",
                password_hash=hash_password("x" * 16),
                role=UserRole.ADMIN,
            )
        )
        clean_db.commit()
        assert bootstrap.ensure_admin(clean_db, _config(SEEDED)) is None


class TestTheLinesCanBeDeleted:
    def test_a_file_with_no_admin_block_at_all_loads(self):
        """So the two lines can be removed once a real account exists, which is
        the tidiest place for a password to not be."""
        config = _config("server:\n  host: 127.0.0.1\n")
        assert config.admin.password == ""

    def test_and_seeds_nothing_rather_than_failing(self, clean_db):
        assert bootstrap.ensure_admin(clean_db, _config("server:\n  host: 127.0.0.1\n")) is None

    def test_a_deleted_administrator_is_not_resurrected(self, clean_db):
        """The claim in ensure_admin's own docstring. With the lines deleted
        nothing can bring the account back; with them left in place it would,
        which is the better argument for deleting them than tidiness."""
        bootstrap.ensure_admin(clean_db, _config(SEEDED))
        clean_db.query(User).delete()
        clean_db.commit()

        assert bootstrap.ensure_admin(clean_db, _config("server:\n  host: 127.0.0.1\n")) is None
        assert clean_db.query(User).count() == 0


class TestThePlaceholderAddress:
    @pytest.mark.parametrize(
        "address",
        ["you@example.com", "admin@example.com", "a@example.org", "b@localhost", "c@invalid"],
    )
    def test_reserved_domains_are_recognized(self, address):
        assert bootstrap.is_placeholder_email(address) is True

    @pytest.mark.parametrize("address", ["bryan@theeverlys.com", "a@example.company", None, ""])
    def test_and_real_ones_are_not(self, address):
        assert bootstrap.is_placeholder_email(address) is False

    def test_seeding_one_is_reported_as_an_error(self, clean_db, monkeypatch):
        """config.yaml.sample ships you@example.com and the postinst copies it
        into place, so this is the default outcome rather than a mistake
        somebody has to make. Every digest, watch alert and canary report then
        bounces — which is how it was found, from a bounce message rather than
        from the alert it was meant to be.

        Asserted on the logger rather than through caplog: this record does not
        reach caplog's handler in this suite, and what matters is that the
        branch runs, not which plumbing carries it.
        """
        said: list[str] = []
        monkeypatch.setattr(
            bootstrap.log, "error", lambda message, *args: said.append(message % args)
        )
        bootstrap.ensure_admin(
            clean_db, _config(SEEDED.replace("someone@theeverlys.test", "you@example.com"))
        )
        assert any("bounce" in line.lower() for line in said)

    def test_and_a_real_address_says_nothing(self, clean_db, monkeypatch):
        said: list[str] = []
        monkeypatch.setattr(
            bootstrap.log, "error", lambda message, *args: said.append(message % args)
        )
        bootstrap.ensure_admin(clean_db, _config(SEEDED))
        assert said == []
