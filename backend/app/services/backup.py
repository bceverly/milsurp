"""Daily snapshots of the database, kept for a rolling window.

The database is the one part of this application that cannot be rebuilt. The
code is in version control and the photos can be fetched again, but the price
history is a record of what a vendor was asking on a day that has passed, and
nothing on the internet will give it back.

Under SQLite, snapshots are taken with the online backup API rather than by
copying the file. A copy taken while the application is running can catch a
write halfway through, and with write-ahead logging the file on disk is not the
database anyway -- part of it is in the -wal beside it. The backup API reads
through the same machinery the application does and produces a file that opens.

Under PostgreSQL the same job belongs to ``pg_dump``, and this shells out to it
in custom format (``-Fc``), which is compressed and is what ``pg_restore``
wants. The server does the consistent-snapshot part; there is no equivalent of
the SQLite hazard above. ``pg_dump`` has to be on PATH -- it ships with the
client package, not the server -- and the credentials are the ones already in
config.yaml, handed over in the environment rather than on the command line so
the password never appears in ``ps``.

Nothing is written in development. A development database is a scratch copy
that gets deleted and re-seeded, and filling a working tree with snapshots of
it would be noise.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3

# pg_dump, invoked below with a fixed argv and no shell.
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Config
from ..models import BackupSetting, utcnow

log = logging.getLogger("milsurp.backup")

#: Backups are named so that sorting them by name sorts them by age. The
#: suffix says which engine wrote it, because the two are not interchangeable:
#: a .db opens with sqlite3 and a .dump only with pg_restore.
STAMP_FORMAT = "%Y%m%d-%H%M%S"
NAME_PATTERN = re.compile(r"^milsurp-\d{8}-\d{6}\.(?:db|dump)$")

#: How long pg_dump is given before it is treated as hung. A snapshot of this
#: database is seconds; the ceiling is here so a wedged dump cannot hold the
#: scheduler's backup tick open forever.
PG_DUMP_TIMEOUT_SECONDS = 3600

#: The snapshot directory is readable only by the account that runs the
#: application: it holds every email address the site knows.
SECURE_DIR_MODE = 0o700
SECURE_FILE_MODE = 0o600


def settings(session: Session) -> BackupSetting:
    """The one settings row, created if a database somehow lacks it.

    Migration 0015 seeds it, so the create is for a database built some other
    way -- an old stamp, a create_all() in a test -- rather than a path anybody
    takes on purpose.
    """
    row = session.get(BackupSetting, 1)
    if row is None:
        row = BackupSetting(id=1, enabled=False, interval_hours=24, keep=10)
        session.add(row)
        session.commit()
    return row


def is_enabled(session: Session) -> bool:
    """Whether the schedule is on. The admin decides; the run mode does not.

    It used to be ``config.backups.enabled and not config.is_dev``, which was
    right when the only way to change it was to edit a file on the server: a
    development checkout should not fill its working tree with snapshots of a
    scratch database. Now that it is a switch on a page, "development" is no
    longer a reason to overrule somebody who has asked for backups -- and this
    installation, which runs in development mode against a PostgreSQL database
    holding real price history, is exactly why.
    """
    return bool(settings(session).enabled)


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


def is_due(session: Session, config: Config, *, now: datetime | None = None) -> bool:
    """Measured against the newest file on disk, not against a timer.

    A process that restarts twice a day should still produce one backup a day,
    and a timer resets on every restart while the files do not.
    """
    row = settings(session)
    if not row.enabled:
        return False
    age = age_hours(config.backups.directory, now=now)
    return age is None or age >= row.interval_hours


def take(config: Config, *, now: datetime | None = None) -> Path:
    """Write one snapshot and return where it went.

    Raises rather than returning None when it cannot: a backup that fails
    quietly is worse than no backup, because it is believed.
    """
    directory = config.backups.directory
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(SECURE_DIR_MODE)

    stamp = (now or datetime.now(UTC)).strftime(STAMP_FORMAT)
    if config.database.is_postgres:
        destination = directory / f"milsurp-{stamp}.dump"
        _pg_dump(config, destination)
    else:
        destination = directory / f"milsurp-{stamp}.db"
        _sqlite_backup(config, destination)

    destination.chmod(SECURE_FILE_MODE)
    return destination


def _sqlite_backup(config: Config, destination: Path) -> None:
    source = sqlite3.connect(f"file:{config.database_path}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _pg_dump(config: Config, destination: Path) -> None:
    """Snapshot a PostgreSQL database with pg_dump, in custom format.

    Restore one with::

        pg_restore --clean --if-exists -d milsurp milsurp-20260909-030000.dump

    The file is created mode 0600 *before* pg_dump writes into it -- with
    ``--file`` rather than a redirect -- so it is never briefly world-readable.
    """
    binary = shutil.which("pg_dump")
    if binary is None:
        raise RuntimeError(
            "pg_dump is not on PATH. Install the PostgreSQL client package "
            "(postgresql-client on Debian/Ubuntu) or set backups.enabled: false."
        )

    database = config.database
    destination.touch(mode=SECURE_FILE_MODE)
    environment = {**os.environ, "PGPASSWORD": database.password} if database.password else None
    argv = [
        binary,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={destination}",
        f"--host={database.host}",
        f"--port={database.port}",
        f"--username={database.user}",
        database.name,
    ]
    try:
        # Fixed argv, no shell: every element is built here, and the
        # database name is the only one that comes from config.yaml.
        subprocess.run(  # noqa: S603  # nosec B603
            argv,
            check=True,
            capture_output=True,
            text=True,
            timeout=PG_DUMP_TIMEOUT_SECONDS,
            env=environment,
        )
    except subprocess.CalledProcessError as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed: {exc.stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError("pg_dump did not finish within the timeout") from exc


def prune(directory: Path, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` snapshots. Returns what went."""
    removed = []
    for path in existing(directory)[max(keep, 0) :]:
        path.unlink()
        removed.append(path)
    return removed


def run(
    session: Session, config: Config, *, now: datetime | None = None, force: bool = False
) -> Path | None:
    """Take a snapshot and prune the old ones. None when backups are off.

    ``force`` is the "Back up now" button: a person asking for one is a good
    enough reason, whatever the schedule says.

    The outcome is written to the settings row either way, so the admin page
    can report what happened without anybody reading a log -- and so a backup
    that has been failing quietly for a week is visible where the setting is,
    which is the place somebody would look.
    """
    row = settings(session)
    if not (row.enabled or force):
        return None

    row.last_run_at = utcnow()
    try:
        destination = take(config, now=now)
    except Exception as exc:
        row.last_status = "FAILED"
        row.last_error = str(exc)[:500]
        row.last_bytes = None
        session.commit()
        raise

    removed = prune(config.backups.directory, row.keep)
    row.last_status = "SUCCESS"
    row.last_error = None
    row.last_bytes = destination.stat().st_size
    session.commit()

    log.info(
        "Wrote %s (%.1f MB); pruned %d old snapshot(s)",
        destination.name,
        destination.stat().st_size / 1_048_576,
        len(removed),
    )
    return destination
