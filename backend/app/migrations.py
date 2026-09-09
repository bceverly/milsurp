"""Programmatic Alembic access.

The schema is created and evolved by Alembic and nothing else: even a brand new
database is built by running the migration chain, so a fresh install and an
upgraded one go through exactly the same steps and can never drift apart.

Both entry points share this module -- ``scripts/dbupdate.py`` for the command
line, and application startup -- so dev and production behave identically.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from .config import Config, get_config
from .database import get_engine

log = logging.getLogger("milsurp.migrations")

# backend/app/migrations.py -> backend
BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"

# Revision modules import `app.migration_utils`, and Alembic loads them
# directly (bypassing env.py) when reading history, so backend/ has to be on
# sys.path before any ScriptDirectory call -- not just inside env.py.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def alembic_config(config: Config | None = None) -> AlembicConfig:
    """Build an Alembic config pointed at the database for the current mode."""
    config = config or get_config()
    config.ensure_directories()

    alembic_cfg = AlembicConfig(str(ALEMBIC_INI))
    # Set explicitly rather than relying on the ini so this works no matter what
    # directory the caller happens to be in.
    alembic_cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    alembic_cfg.set_main_option("sqlalchemy.url", config.database_url)
    # env.py imports the app package and the migration helpers from these.
    alembic_cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    return alembic_cfg


def current_revision(config: Config | None = None) -> str | None:
    """The revision the database is stamped with, or ``None`` if it is empty."""
    config = config or get_config()
    engine = get_engine()
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision(config: Config | None = None) -> str | None:
    """The newest revision available on disk."""
    script = ScriptDirectory.from_config(alembic_config(config))
    return script.get_current_head()


def pending_revisions(config: Config | None = None) -> list[str]:
    """Revisions that exist on disk but have not been applied yet."""
    config = config or get_config()
    current = current_revision(config)
    script = ScriptDirectory.from_config(alembic_config(config))
    head = script.get_current_head()
    if head is None or current == head:
        return []
    # walk_revisions yields newest-first; stop once we reach what is applied.
    pending = []
    for revision in script.walk_revisions(base="base", head=head):
        if revision.revision == current:
            break
        pending.append(revision.revision)
    return list(reversed(pending))


def upgrade(config: Config | None = None, revision: str = "head") -> str | None:
    """Apply outstanding migrations. Returns the revision now in effect.

    Safe to call on every start: with nothing outstanding it is a no-op, and the
    migrations themselves are written to be idempotent.
    """
    config = config or get_config()
    before = current_revision(config)
    outstanding = pending_revisions(config)

    if outstanding:
        log.info("Applying %s migration(s): %s", len(outstanding), ", ".join(outstanding))
    elif before is None:
        log.info("Creating a new database at %s", config.database.describe())

    command.upgrade(alembic_config(config), revision)

    after = current_revision(config)
    if after != before:
        log.info("Database schema is now at revision %s", after)
    return after


def downgrade(config: Config | None = None, revision: str = "-1") -> str | None:
    command.downgrade(alembic_config(config), revision)
    return current_revision(config)


def stamp(config: Config | None = None, revision: str = "head") -> None:
    """Mark the database as being at a revision without running anything.

    Only needed to adopt a database that was created before Alembic was wired
    in; a normal install never needs it.
    """
    command.stamp(alembic_config(config), revision)


def status(config: Config | None = None) -> dict[str, object]:
    config = config or get_config()
    current = current_revision(config)
    head = head_revision(config)
    pending = pending_revisions(config)
    return {
        "database_path": config.database.describe(),
        "engine": config.database.engine,
        "mode": config.mode,
        "current_revision": current,
        "head_revision": head,
        "pending": pending,
        "up_to_date": not pending and current is not None,
    }
