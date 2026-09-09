"""Alembic environment.

The database URL comes from the application's own configuration rather than
alembic.ini, so `make migrate` targets whatever ``database.path`` resolves to
for the current mode: the repository root in dev, /etc/milsurp in production.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# backend/alembic/env.py -> backend
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_config  # noqa: E402
from app.database import Base  # noqa: E402
from app import models  # noqa: F401,E402  (import registers every model)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

app_config = get_config()

# A URL set by the caller wins. Normally nobody sets one -- alembic.ini
# deliberately has no url, so this falls through to the application's own
# config and `make migrate` targets whatever database.yaml resolves to. But
# `alembic -x`, and the portability tests, need to point the chain at a
# throwaway database, and a line that always clobbers the URL makes that
# impossible: the run silently goes to the real database instead. Which it did,
# once, while this file was being written.
explicit = config.get_main_option("sqlalchemy.url", None)
if not explicit:
    config.set_main_option("sqlalchemy.url", app_config.database_url)
    explicit = app_config.database_url

# Only a SQLite target needs a directory made, and only when it is the one the
# application configured -- a temp file passed in from a test makes its own.
if explicit == app_config.database_url:
    app_config.ensure_directories()

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (``alembic upgrade --sql``)."""
    context.configure(
        url=explicit,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER most things in place; batch mode rebuilds the
            # table around the change, which is what makes column edits possible
            # at all on this backend.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
