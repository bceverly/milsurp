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
    def test_development_never_writes_a_snapshot(self, app_config, tmp_path):
        """A development database is a scratch copy that gets re-seeded."""
        config = replace(
            app_config, mode="dev", backups=replace(app_config.backups, directory=tmp_path)
        )

        assert backup.is_enabled(config) is False
        assert backup.is_due(config) is False
        assert backup.run(config) is None
        assert backup.existing(tmp_path) == []

    def test_the_first_run_is_always_due(self, configured):
        assert backup.is_due(configured) is True

    def test_it_is_not_due_again_until_the_interval_has_passed(self, configured):
        backup.take(configured)

        assert backup.is_due(configured) is False
        later = datetime.now(UTC) + timedelta(hours=25)
        assert backup.is_due(configured, now=later) is True

    def test_turning_it_off_turns_it_off(self, configured):
        config = replace(configured, backups=replace(configured.backups, enabled=False))
        assert backup.run(config) is None


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

    def test_a_run_prunes_as_it_goes(self, configured, seeded):
        config = replace(configured, backups=replace(configured.backups, keep=2))
        for day in range(1, 5):
            backup.run(config, now=datetime(2026, 3, day, 4, 5, 6, tzinfo=UTC))

        assert len(backup.existing(config.backups.directory)) == 2

    def test_files_that_are_not_snapshots_are_left_alone(self, configured):
        backup.take(configured)
        stray = configured.backups.directory / "notes.txt"
        stray.write_text("do not delete me")

        backup.prune(configured.backups.directory, keep=0)

        assert stray.exists()
