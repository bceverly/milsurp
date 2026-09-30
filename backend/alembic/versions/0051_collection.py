"""A reader's own collection: what they own, what they paid, what it is worth.

One table, ``collection_items``, owned per user. See
``app.services.collection`` for how a row is valued against the market.

Idempotent like every migration here.

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import table_exists

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("collection_items"):
        return
    op.create_table(
        "collection_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "firearm_model_id",
            sa.Integer(),
            sa.ForeignKey("firearm_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model_declined", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("caliber", sa.String(length=64), nullable=True),
        sa.Column("manufacturer", sa.String(length=128), nullable=True),
        sa.Column("condition_grade", sa.String(length=16), nullable=True),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("paid", sa.Float(), nullable=True),
        sa.Column("acquired_from", sa.String(length=128), nullable=True),
        sa.Column(
            "item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_collection_items_user_id", "collection_items", ["user_id"])
    op.create_index(
        "ix_collection_items_firearm_model_id", "collection_items", ["firearm_model_id"]
    )


def downgrade() -> None:
    if table_exists("collection_items"):
        op.drop_table("collection_items")
