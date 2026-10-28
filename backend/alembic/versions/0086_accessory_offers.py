"""Magazines and speedloaders that fit the guns somebody owns.

``accessory_offers``: what an accessory store sells and the guns it says each
product fits, refreshed daily for the models in readers' collections, and
shown on "For your guns". Apart from ``items`` so the browse catalog is not
swamped. See app/services/fitting.py. Idempotent like every migration here.

Revision ID: 0086
Revises: 0085
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import create_index_if_missing, drop_table_if_present, table_exists

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("accessory_offers"):
        op.create_table(
            "accessory_offers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("external_key", sa.String(128), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("url", sa.String(1000), nullable=False),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("in_stock", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("image_url", sa.String(1000), nullable=True),
            sa.Column("maker", sa.String(128), nullable=True),
            sa.Column("fits", sa.Text(), nullable=True),
            sa.Column("refreshed_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "external_key", name="uq_accessory_offers_source_key"),
        )
    create_index_if_missing("ix_accessory_offers_source", "accessory_offers", ["source"])


def downgrade() -> None:
    drop_table_if_present("accessory_offers")
