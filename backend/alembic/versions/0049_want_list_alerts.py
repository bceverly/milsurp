"""Want-list alerts: a saved search that tells you the moment one appears.

``saved_searches.alert_instantly`` and ``alert_since``, and a table of the
listings each has already announced, so a listing is news once. See
``app.services.wantlist``.

Idempotent like every migration here.

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import add_column_if_missing, drop_column_if_present, table_exists

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "saved_searches",
        sa.Column("alert_instantly", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column_if_missing("saved_searches", sa.Column("alert_since", sa.DateTime(), nullable=True))
    if not table_exists("saved_search_alerts"):
        op.create_table(
            "saved_search_alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "saved_search_id",
                sa.Integer(),
                sa.ForeignKey("saved_searches.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "item_id",
                sa.Integer(),
                sa.ForeignKey("items.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("alerted_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("saved_search_id", "item_id", name="uq_saved_search_alert"),
        )
        op.create_index(
            "ix_saved_search_alerts_saved_search_id", "saved_search_alerts", ["saved_search_id"]
        )
        op.create_index("ix_saved_search_alerts_item_id", "saved_search_alerts", ["item_id"])


def downgrade() -> None:
    if table_exists("saved_search_alerts"):
        op.drop_table("saved_search_alerts")
    drop_column_if_present("saved_searches", "alert_since")
    drop_column_if_present("saved_searches", "alert_instantly")
