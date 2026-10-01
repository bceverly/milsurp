"""What each owned gun was worth, week by week.

``collection_valuations``: one row per gun per snapshot day, recorded for a
reader's whole collection on the same day. See
``app.services.collection.snapshot_due``.

Idempotent like every migration here.

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import table_exists

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("collection_valuations"):
        return
    op.create_table(
        "collection_valuations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "collection_item_id",
            sa.Integer(),
            sa.ForeignKey("collection_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("recorded_on", sa.Date(), nullable=False),
        sa.Column("estimate", sa.Float(), nullable=False),
        sa.Column("basis", sa.String(length=8), nullable=False),
        sa.UniqueConstraint(
            "collection_item_id", "recorded_on", name="uq_collection_valuation_day"
        ),
    )
    op.create_index(
        "ix_collection_valuations_collection_item_id",
        "collection_valuations",
        ["collection_item_id"],
    )
    op.create_index("ix_collection_valuations_user_id", "collection_valuations", ["user_id"])
    op.create_index(
        "ix_collection_valuations_recorded_on", "collection_valuations", ["recorded_on"]
    )


def downgrade() -> None:
    if table_exists("collection_valuations"):
        op.drop_table("collection_valuations")
