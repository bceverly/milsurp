"""Variants under a model, and the barrel and finish a listing states.

``model_variants``: a model's versions as a buyer can choose them -- caliber,
barrel length, finish, with the maker's UPC, part number, MSRP and page where
they are known. Pending until approved, like every other armory row. And on
``items``: ``barrel_inches`` and ``finish`` as the title states them, and
``variant_id`` when those narrow the model to exactly one variant. Slice 2 of
"New-gun prices, and the makers' own pages" in ROADMAP.md.

Idempotent like every migration here.

Revision ID: 0064
Revises: 0063
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    column_exists,
    create_index_if_missing,
    create_table_if_missing,
    drop_column_if_present,
    drop_index_if_present,
    drop_table_if_present,
    table_exists,
)

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_missing(
        "model_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("firearm_models.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column(
            "caliber_id",
            sa.Integer(),
            sa.ForeignKey("calibers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("barrel_inches", sa.Float(), nullable=True),
        sa.Column("finish", sa.String(32), nullable=True),
        sa.Column("upc", sa.String(20), nullable=True, index=True),
        sa.Column("maker_part", sa.String(64), nullable=True),
        sa.Column("msrp", sa.Float(), nullable=True),
        sa.Column("maker_url", sa.String(500), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="hand"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # Not batch mode, and not a foreign key at the column level: items carries
    # a generated column (migration 0034) that SQLite's table rebuild cannot
    # reproduce. The link is kept by the application and cleared on delete.
    for column in (
        sa.Column("barrel_inches", sa.Float(), nullable=True),
        sa.Column("finish", sa.String(32), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
    ):
        if table_exists("items") and not column_exists("items", column.name):
            op.add_column("items", column)
    create_index_if_missing("ix_items_variant_id", "items", ["variant_id"])


def downgrade() -> None:
    drop_index_if_present("ix_items_variant_id", "items")
    drop_column_if_present("items", "variant_id")
    drop_column_if_present("items", "finish")
    drop_column_if_present("items", "barrel_inches")
    drop_table_if_present("model_variants")
