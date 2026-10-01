"""When a shop's scans started failing, and whether anybody has been told.

``sites.scan_failing_since`` and ``sites.scan_failure_reported``, so a failed
scan is mailed only once the failure has outlasted a grace period rather than
the moment it happens. See ``app.services.scanalerts``.

Idempotent like every migration here.

Revision ID: 0055
Revises: 0054
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("sites", sa.Column("scan_failing_since", sa.DateTime(), nullable=True))
    add_column_if_missing(
        "sites",
        sa.Column("scan_failure_reported", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    drop_column_if_present("sites", "scan_failure_reported")
    drop_column_if_present("sites", "scan_failing_since")
