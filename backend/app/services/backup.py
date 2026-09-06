"""Daily snapshots of the database, kept for a rolling window.

The database is the one part of this application that cannot be rebuilt. The
code is in version control and the photos can be fetched again, but the price
history is a record of what a vendor was asking on a day that has passed, and
nothing on the internet will give it back.

Snapshots are taken with SQLite's online backup API rather than by copying the
file. A copy taken while the application is running can catch a write halfway
through, and with write-ahead logging the file on disk is not the database
anyway -- part of it is in the -wal beside it. The backup API reads through
the same machinery the application does and produces a file that opens.

Nothing is written in development. A development database is a scratch copy
that gets deleted and re-seeded, and filling a working tree with snapshots of
it would be noise.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config

log = logging.getLogger("milsurp.backup")

#: Backups are named so that sorting them by name sorts them by age.
STAMP_FORMAT = "%Y%m%d-%H%M%S"
NAME_PATTERN = re.compile(r"^milsurp-\d{8}-\d{6}\.db$")

#: The snapshot directory is readable only by the account that runs the
#: application: it holds every email address the site knows.
SECURE_DIR_MODE = 0o700
SECURE_FILE_MODE = 0o600


def is_enabled(config: Config) -> bool:
    return config.backups.enabled and not config.is_dev


def existing(directory: Path) -> list[Path]:
    """Every snapshot in a directory, newest first."""
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.iterdir() if NAME_PATTERN.match(path.name)),
        reverse=True,
    )


def age_hours(directory: Path, *, now: datetime | None = None) -> float | None:
    """How long since the most recent snapshot, or None if there is none."""
    snapshots = existing(directory)
    if not snapshots:
        return None
    now = now or datetime.now(UTC)
    taken = datetime.fromtimestamp(snapshots[0].stat().st_mtime, UTC)
    return (now - taken).total_seconds() / 3600


def is_due(config: Config, *, now: datetime | None = None) -> bool:
    if not is_enabled(config):
        return False
    age = age_hours(config.backups.directory, now=now)
    return age is None or age >= config.backups.interval_hours


def take(config: Config, *, now: datetime | None = None) -> Path:
    """Write one snapshot and return where it went.

    Raises rather than returning None when it cannot: a backup that fails
    quietly is worse than no backup, because it is believed.
    """
    directory = config.backups.directory
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(SECURE_DIR_MODE)

    stamp = (now or datetime.now(UTC)).strftime(STAMP_FORMAT)
    destination = directory / f"milsurp-{stamp}.db"

    source = sqlite3.connect(f"file:{config.database_path}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    destination.chmod(SECURE_FILE_MODE)
    return destination


def prune(directory: Path, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` snapshots. Returns what went."""
    removed = []
    for path in existing(directory)[max(keep, 0) :]:
        path.unlink()
        removed.append(path)
    return removed


def run(config: Config, *, now: datetime | None = None) -> Path | None:
    """Take a snapshot and prune the old ones. None when backups are off."""
    if not is_enabled(config):
        return None
    destination = take(config, now=now)
    removed = prune(config.backups.directory, config.backups.keep)
    log.info(
        "Wrote %s (%.1f MB); pruned %d old snapshot(s)",
        destination.name,
        destination.stat().st_size / 1_048_576,
        len(removed),
    )
    return destination
