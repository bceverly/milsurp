"""The monthly market report: an opt-in, and when it last went.

``email_preferences.market_report`` and ``market_report_sent_at``. See
``app.services.marketreport``.

Idempotent like every migration here.

Revision ID: 0053
Revises: 0052
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "email_preferences",
        sa.Column("market_report", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column_if_missing(
        "email_preferences", sa.Column("market_report_sent_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    drop_column_if_present("email_preferences", "market_report_sent_at")
    drop_column_if_present("email_preferences", "market_report")
