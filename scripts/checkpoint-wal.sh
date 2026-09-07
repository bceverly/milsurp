#!/usr/bin/env bash
#
# Fold the write-ahead log back into the database and give its disk back.
#
#   scripts/checkpoint-wal.sh            # quiet unless something changed
#   scripts/checkpoint-wal.sh --verbose  # always say what happened
#
# SQLite in WAL mode appends every write to a `-wal` sidecar and folds it back
# on a checkpoint. The automatic checkpoints are PASSIVE, which copies the
# pages across but leaves the file at its high-water mark to be reused. That is
# the right trade while the application is running and the wrong one for a file
# that sat at 36MB against a 17MB database because one large scan grew it once.
#
# Nothing here is a repair. A large WAL is not corruption and nothing is at
# risk in it: the data is committed, and any reader sees it. This reclaims
# disk, and it removes a trap -- while a WAL exists, copying `milsurp.db` on
# its own is NOT a backup, and the copy silently lacks everything not yet
# folded in.
#
# Safe at any time. A TRUNCATE checkpoint waits for readers to finish and, if
# it cannot get its turn, does as much as it can and reports busy. It never
# blocks a writer and never loses a commit. `make start` runs it while the
# application is stopped, which is when it can do the most, and it is written
# to be run from cron in production:
#
#   17 4 * * *  cd /opt/milsurp && scripts/checkpoint-wal.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$(command -v python3 || true)"
if [ -z "$VENV_PY" ] || [ ! -x "$VENV_PY" ]; then
  echo "checkpoint-wal: no usable python; skipping." >&2
  exit 0
fi

# The database location comes from the application's own configuration, so
# this follows MILSURP_ENV and MILSURP_CONFIG like everything else and needs no
# path of its own to drift out of date.
VERBOSE="$VERBOSE" "$VENV_PY" - <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "backend")

try:
    from app.config import get_config

    database = Path(get_config().database_path)
except Exception as exc:  # pragma: no cover - a misconfigured host, not a bug
    print(f"checkpoint-wal: could not read the configuration ({exc}); skipping.")
    raise SystemExit(0) from None

verbose = os.environ.get("VERBOSE") == "1"
wal = database.with_name(database.name + "-wal")

if not database.exists():
    if verbose:
        print(f"checkpoint-wal: no database at {database}; nothing to do.")
    raise SystemExit(0)

before = wal.stat().st_size if wal.exists() else 0
if before == 0:
    if verbose:
        print("checkpoint-wal: the write-ahead log is already empty.")
    raise SystemExit(0)

try:
    with sqlite3.connect(str(database), timeout=30) as connection:
        # TRUNCATE folds everything in and then empties the file. The three
        # numbers it answers with are (busy, pages in the log, pages moved
        # across); a busy of 1 means a reader held it up and some of the log
        # is still there, which is not a failure and not worth a red line in
        # a cron mail -- the next run will get it.
        busy, in_log, moved = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
except sqlite3.Error as exc:
    print(f"checkpoint-wal: {exc}", file=sys.stderr)
    raise SystemExit(1) from None

after = wal.stat().st_size if wal.exists() else 0
if verbose or after != before:
    freed = before - after
    state = " (a reader held it up; the rest waits for next time)" if busy else ""
    print(
        f"checkpoint-wal: write-ahead log {before:,} -> {after:,} bytes, "
        f"{freed:,} reclaimed{state}."
    )
PY
