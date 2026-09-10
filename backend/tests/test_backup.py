"""Rolling database snapshots.

Written after the database was damaged by a bad batch update with no way back:
these tests are about the two properties that would have mattered then, which
are that a snapshot exists and that it opens.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.services import backup


@pytest.fixture
def configured(app_config, _database, tmp_path):
    """A production-mode config whose snapshots land in a temporary directory.

    Depends on the database fixture because a snapshot of a database that does
    not exist yet is not a test of anything.
    """
    return replace(
        app_config,
        mode="production",
        backups=replace(app_config.backups, directory=tmp_path / "backups"),
    )


class TestWhenItRuns:
    """The schedule is a row in the database, not a line in config.yaml.

    It moved because an administrator is the person who should decide how often
    a snapshot is taken, and editing a file on the server and restarting is not
    a thing an administrator should have to do to change a retention window.

    One consequence is worth stating: the run mode no longer overrules the
    setting. "Development never backs up" was right when the only way to change
    it was to edit the server's config -- a scratch database should not fill a
    working tree with copies of itself. It is wrong now, and this installation
    is why: it runs in development mode against a PostgreSQL database holding
    real price history.
    """

    def test_a_new_installation_has_it_switched_off(self, session, configured):
        assert backup.is_enabled(session) is False
        assert backup.is_due(session, configured) is False
        assert backup.run(session, configured) is None
        assert backup.existing(configured.backups.directory) == []

    def test_switching_it_on_is_all_it_takes(self, session, configured):
        backup.settings(session).enabled = True
        assert backup.is_due(session, configured) is True
        assert backup.run(session, configured) is not None

    def test_the_first_run_is_always_due(self, session, configured):
        backup.settings(session).enabled = True
        assert backup.is_due(session, configured) is True

    def test_it_is_not_due_again_until_the_interval_has_passed(self, session, configured):
        backup.settings(session).enabled = True
        backup.take(configured)

        assert backup.is_due(session, configured) is False
        later = datetime.now(UTC) + timedelta(hours=25)
        assert backup.is_due(session, configured, now=later) is True

    def test_the_interval_comes_from_the_row(self, session, configured):
        """Which is the whole point of moving it out of the file."""
        settings = backup.settings(session)
        settings.enabled = True
        settings.interval_hours = 6
        backup.take(configured)

        assert backup.is_due(session, configured) is False
        later = datetime.now(UTC) + timedelta(hours=7)
        assert backup.is_due(session, configured, now=later) is True

    def test_turning_it_off_turns_it_off(self, session, configured):
        backup.settings(session).enabled = False
        assert backup.run(session, configured) is None

    def test_but_asking_for_one_by_hand_works_anyway(self, session, configured):
        """The "Back up now" button. Somebody about to do something risky is a
        good enough reason, whatever the schedule says."""
        backup.settings(session).enabled = False
        assert backup.run(session, configured, force=True) is not None


class TestTheOutcomeIsRecorded:
    """A backup that has been failing quietly for a week should be visible
    where the setting is, which is where somebody would look."""

    def test_a_success_is_written_down(self, session, configured):
        backup.run(session, configured, force=True)
        settings = backup.settings(session)

        assert settings.last_status == "SUCCESS"
        assert settings.last_error is None
        assert settings.last_bytes > 0
        assert settings.last_run_at is not None

    def test_and_so_is_a_failure(self, session, configured, monkeypatch):
        def explode(*_args, **_kwargs):
            raise RuntimeError("pg_dump is not on PATH")

        monkeypatch.setattr(backup, "take", explode)
        with pytest.raises(RuntimeError):
            backup.run(session, configured, force=True)

        settings = backup.settings(session)
        assert settings.last_status == "FAILED"
        assert "pg_dump" in settings.last_error
        assert settings.last_bytes is None


class TestTheSnapshotItself:
    def test_it_is_a_database_that_opens(self, configured, seeded):
        """The point of the whole exercise, and the reason for the backup API.

        A file copied while the application is writing can catch a transaction
        halfway through, and under write-ahead logging the file on disk is not
        the whole database anyway.
        """
        destination = backup.take(configured)

        connection = sqlite3.connect(destination)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            connection.close()

        assert {"items", "sites", "users"} <= tables

    def test_it_is_readable_only_by_its_owner(self, configured):
        """It holds every email address the site knows."""
        destination = backup.take(configured)

        assert destination.stat().st_mode & 0o777 == 0o600
        assert configured.backups.directory.stat().st_mode & 0o777 == 0o700

    def test_snapshots_sort_by_name_into_age_order(self, configured):
        stamps = [datetime(2026, 3, day, 4, 5, 6, tzinfo=UTC) for day in (3, 1, 2)]
        for stamp in stamps:
            backup.take(configured, now=stamp)

        newest_first = [path.name for path in backup.existing(configured.backups.directory)]
        assert newest_first == [
            "milsurp-20260303-040506.db",
            "milsurp-20260302-040506.db",
            "milsurp-20260301-040506.db",
        ]


class TestPruning:
    def test_it_keeps_the_newest_and_drops_the_rest(self, configured):
        for day in range(1, 15):
            backup.take(configured, now=datetime(2026, 3, day, 4, 5, 6, tzinfo=UTC))

        removed = backup.prune(configured.backups.directory, keep=10)
        kept = backup.existing(configured.backups.directory)

        assert len(removed) == 4
        assert len(kept) == 10
        assert kept[0].name == "milsurp-20260314-040506.db"
        assert kept[-1].name == "milsurp-20260305-040506.db"

    def test_it_leaves_a_directory_alone_when_there_is_nothing_to_drop(self, configured):
        backup.take(configured)
        assert backup.prune(configured.backups.directory, keep=10) == []

    def test_a_run_prunes_as_it_goes(self, session, configured, seeded):
        """And "how many to keep" is read from the row, not the file."""
        settings = backup.settings(session)
        settings.enabled = True
        settings.keep = 2
        for day in range(1, 5):
            backup.run(session, configured, now=datetime(2026, 3, day, 4, 5, 6, tzinfo=UTC))

        assert len(backup.existing(configured.backups.directory)) == 2

    def test_the_previous_engine_s_snapshots_age_out_too(self, configured):
        """A cutover leaves the other engine's files in the same directory, and
        they are snapshots like any other: counted, ordered by their own
        timestamp, and dropped off the end in turn. A prune that only saw the
        current suffix would keep two SQLite files forever and quietly hold the
        real retention at three."""
        directory = configured.backups.directory
        directory.mkdir(parents=True, exist_ok=True)
        for name in ("milsurp-20260907-183958.db", "milsurp-20260908-180630.db"):
            (directory / name).write_bytes(b"from before the cutover")
        for name in ("milsurp-20260909-193649.dump", "milsurp-20260910-193649.dump"):
            (directory / name).write_bytes(b"from after it")

        removed = backup.prune(directory, keep=3)

        assert [path.name for path in removed] == ["milsurp-20260907-183958.db"]
        assert [path.name for path in backup.existing(directory)] == [
            "milsurp-20260910-193649.dump",
            "milsurp-20260909-193649.dump",
            "milsurp-20260908-180630.db",
        ]

    def test_files_that_are_not_snapshots_are_left_alone(self, configured):
        backup.take(configured)
        stray = configured.backups.directory / "notes.txt"
        stray.write_text("do not delete me")

        backup.prune(configured.backups.directory, keep=0)

        assert stray.exists()


class TestUnderPostgreSQL:
    """The same job, done by pg_dump.

    A PostgreSQL snapshot is not a file this process can write: the data lives
    on a server, and ``pg_dump`` is the supported way to get a consistent copy
    of it out. So these tests are about the argv, the file mode and the failure
    message rather than about the bytes -- the bytes are PostgreSQL's problem,
    and there is an end-to-end check of them in test_database_portability.py.
    """

    @pytest.fixture
    def on_postgres(self, configured):
        from app.config import DatabaseConfig

        return replace(
            configured,
            database=DatabaseConfig(
                engine="postgresql",
                host="db.internal",
                port=6432,
                name="milsurp",
                user="milsurp",
                password="hunter2",
            ),
        )

    def test_the_snapshot_is_named_dump_not_db(self, on_postgres, monkeypatch):
        """The two are not interchangeable: a .db opens with sqlite3 and a
        .dump only with pg_restore, so the name has to say which it is."""
        monkeypatch.setattr(backup.shutil, "which", lambda _: "/usr/bin/pg_dump")
        monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: None)

        written = backup.take(on_postgres, now=datetime(2026, 3, 1, 4, 5, 6, tzinfo=UTC))

        assert written.name == "milsurp-20260301-040506.dump"
        assert backup.existing(on_postgres.backups.directory) == [written]

    def test_the_file_is_0600_before_pg_dump_writes_a_byte_into_it(self, on_postgres, monkeypatch):
        """It holds every email address the site knows. Creating it first and
        passing --file, rather than redirecting into it, is what keeps it from
        being briefly world-readable."""
        seen = {}

        def fake_run(argv, **kwargs):
            target = next(a for a in argv if a.startswith("--file="))[len("--file=") :]
            from pathlib import Path

            seen["mode"] = Path(target).stat().st_mode & 0o777

        monkeypatch.setattr(backup.shutil, "which", lambda _: "/usr/bin/pg_dump")
        monkeypatch.setattr(backup.subprocess, "run", fake_run)

        backup.take(on_postgres)

        assert seen["mode"] == 0o600

    def test_the_password_goes_in_the_environment_not_the_command_line(
        self, on_postgres, monkeypatch
    ):
        """Anything on the argv is readable by every account on the box for as
        long as the dump runs."""
        seen = {}

        monkeypatch.setattr(backup.shutil, "which", lambda _: "/usr/bin/pg_dump")
        monkeypatch.setattr(
            backup.subprocess, "run", lambda argv, **kw: seen.update(argv=argv, env=kw.get("env"))
        )

        backup.take(on_postgres)

        assert not any("hunter2" in argument for argument in seen["argv"])
        assert seen["env"]["PGPASSWORD"] == "hunter2"
        assert "--host=db.internal" in seen["argv"]
        assert "--port=6432" in seen["argv"]
        assert seen["argv"][-1] == "milsurp"

    def test_a_missing_pg_dump_says_which_package_to_install(self, on_postgres, monkeypatch):
        monkeypatch.setattr(backup.shutil, "which", lambda _: None)

        with pytest.raises(RuntimeError, match="postgresql-client"):
            backup.take(on_postgres)

    def test_a_failed_dump_leaves_no_file_behind_to_be_believed(self, on_postgres, monkeypatch):
        """A zero-byte .dump in the backup directory is worse than no file:
        it makes is_due() say a snapshot was taken today."""
        import subprocess

        def fail(argv, **kwargs):
            raise subprocess.CalledProcessError(1, argv, stderr="FATAL: role does not exist")

        monkeypatch.setattr(backup.shutil, "which", lambda _: "/usr/bin/pg_dump")
        monkeypatch.setattr(backup.subprocess, "run", fail)

        with pytest.raises(RuntimeError, match="role does not exist"):
            backup.take(on_postgres)
        assert backup.existing(on_postgres.backups.directory) == []
