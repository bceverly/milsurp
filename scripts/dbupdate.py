#!/usr/bin/env python3
"""Create or upgrade the Milsurp Monitor database.

This is the single supported way to touch the schema, in every environment:

    make migrate                      # development (wraps this script)
    scripts/dbupdate.py               # production (run it directly)

It resolves the database location the same way the application does, so it
always targets the right file:

    dev         <repo root>/milsurp.db
    production  /etc/milsurp/milsurp.db

...or whatever ``database.path`` in config.yaml says, which wins in both modes.
Set ``MILSURP_ENV=dev`` for development; anything else means production.

The schema itself is built entirely by Alembic, including on a brand new
install, so a fresh database and an upgraded one are produced by the same
migration chain and cannot drift apart.

Options:
    --status        show the current and head revision, then exit
    --check         exit non-zero if migrations are outstanding (for CI)
    --revision REV  upgrade (or downgrade) to a specific revision
    --sql           print the SQL instead of running it
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# scripts/dbupdate.py -> repo root -> backend
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import migrations  # noqa: E402
from app.config import get_config  # noqa: E402

SQLITE_DIR_MODE = 0o750
SQLITE_FILE_MODE = 0o640


def ensure_database_file(database_path: Path) -> bool:
    """Make sure the database file exists and is writable.

    Alembic connects through SQLAlchemy, which will happily create an empty
    SQLite file on its own -- but only if the *directory* exists and is
    writable. On a production box /etc/milsurp usually does not exist yet, so
    that part is done here, along with tightening the permissions: the database
    holds password hashes and must not be world-readable.

    Returns True when a new database file was created.
    """
    parent = database_path.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
            parent.chmod(SQLITE_DIR_MODE)
        except PermissionError:
            print(
                f"error: cannot create {parent} — run this as a user who can "
                f"write there (production usually needs sudo, or the directory "
                f"pre-created and chowned to the service account).",
                file=sys.stderr,
            )
            raise SystemExit(1) from None

    if database_path.exists():
        if not os.access(database_path, os.W_OK):
            print(f"error: {database_path} exists but is not writable.", file=sys.stderr)
            raise SystemExit(1)
        return False

    # Create the empty file explicitly so its permissions are ours from the
    # start, rather than whatever the process umask happens to be when
    # SQLAlchemy creates it.
    try:
        database_path.touch(mode=SQLITE_FILE_MODE, exist_ok=True)
        database_path.chmod(SQLITE_FILE_MODE)
    except PermissionError:
        print(f"error: cannot create {database_path}.", file=sys.stderr)
        raise SystemExit(1) from None
    return True


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912 - CLI dispatch
    parser = argparse.ArgumentParser(
        description="Create or upgrade the Milsurp Monitor database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", help="Path to a config.yaml (overrides the search path).")
    parser.add_argument("--status", action="store_true", help="Show revisions and exit.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if migrations are outstanding; changes nothing.",
    )
    parser.add_argument("--revision", default="head", help="Target revision (default: head).")
    parser.add_argument("--downgrade", action="store_true", help="Downgrade to --revision instead.")
    parser.add_argument("--quiet", action="store_true", help="Only report problems.")
    args = parser.parse_args(argv)

    if args.config:
        os.environ["MILSURP_CONFIG"] = args.config

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
    )

    config = get_config(reload=bool(args.config))

    if not args.quiet:
        print(f"Mode:     {config.mode}")
        print(f"Config:   {config.source_path or 'built-in defaults (no config.yaml found)'}")
        print(f"Database: {config.database_path}")

    if args.status:
        state = migrations.status(config)
        print(f"Current revision: {state['current_revision'] or '(none — empty database)'}")
        print(f"Head revision:    {state['head_revision']}")
        if state["pending"]:
            print(f"Pending:          {', '.join(state['pending'])}")
        else:
            print("Pending:          none — up to date")
        return 0

    if args.check:
        state = migrations.status(config)
        if state["pending"] or state["current_revision"] is None:
            print(
                "Database is not up to date. Run scripts/dbupdate.py.",
                file=sys.stderr,
            )
            return 1
        if not args.quiet:
            print("Database is up to date.")
        return 0

    created = ensure_database_file(config.database_path)
    if created and not args.quiet:
        print(f"Created a new empty database at {config.database_path}")

    if args.downgrade:
        revision = migrations.downgrade(config, args.revision)
        print(f"Downgraded to {revision}.")
        return 0

    before = migrations.current_revision(config)
    after = migrations.upgrade(config, args.revision)

    if not args.quiet:
        if before == after:
            print(f"Already up to date at revision {after}.")
        else:
            print(f"Upgraded {before or '(empty)'} -> {after}.")

    # The image store lives alongside the database and has the same lifecycle,
    # so create it here too rather than making the first scan do it.
    config.ensure_directories()
    if not args.quiet:
        print(f"Image store ready at {config.images_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
