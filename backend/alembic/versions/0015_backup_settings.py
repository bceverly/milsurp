"""Let an administrator set the backup schedule, instead of a YAML file.

Three settings moved out of ``config.yaml`` and into a row: whether backups run
at all, how often, and how many to keep. They are policy, and policy belongs to
whoever administers the site -- not to whoever can edit a file on the server and
restart the service.

``backups.directory`` deliberately did **not** move. Where files land on disk is
a fact about the machine, and a text box that can point the writer at any path
is a worse idea than a default nobody can change from a browser.

**Seeded from config.yaml**, so an installation that had configured these keeps
what it had. After that the row is authoritative and the file is ignored, which
is the only arrangement with one source of truth. Reading the config here rather
than hard-coding the defaults is what makes the upgrade invisible to anyone who
had customised it.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _seed_values() -> tuple[bool, int, int]:
    """What config.yaml says, or the built-in defaults if it cannot be read.

    A migration that cannot run because the application's configuration is
    unavailable would be a poor trade for a nicety, so every failure here falls
    back to the defaults rather than raising.
    """
    try:
        from app.config import get_config

        config = get_config()
        backups = config.backups
        # "and not is_dev" preserves exactly what was effective before: dev
        # never took snapshots, because a development database is a scratch
        # copy and filling a working tree with copies of it is noise. An
        # upgrade should not start writing files nobody asked for; turning
        # them on in development is now one click on the Backups page.
        enabled = bool(backups.enabled) and not config.is_dev
        return enabled, int(backups.interval_hours), int(backups.keep)
    except Exception:  # pragma: no cover - defaults are the safe answer
        return False, 24, 10


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "backup_settings"):
        return

    table = op.create_table(
        "backup_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        # sa.false(), not sa.text("0"): PostgreSQL refuses an integer default
        # on a boolean column. See "Two engines, one schema" in README.md.
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("keep", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    enabled, interval_hours, keep = _seed_values()
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        table,
        [
            {
                "id": 1,
                "enabled": enabled,
                "interval_hours": interval_hours,
                "keep": keep,
                "last_run_at": None,
                "last_status": None,
                "last_error": None,
                "last_bytes": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "backup_settings"):
        op.drop_table("backup_settings")
