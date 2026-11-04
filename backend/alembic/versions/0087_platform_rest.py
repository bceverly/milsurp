"""A hosted platform resting as a whole.

``platform_refusals``: the last 429 each shop on a hosted platform (Shopify,
BigCommerce, Wix) sent us. ``host_cooldowns.platform``: set on the pauses
written when two of a platform's shops refused within a day, so every shop on
it rests a week. See app/services/platform_rest.py. Idempotent like every
migration here.

Revision ID: 0087
Revises: 0086
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    add_column_if_missing,
    create_index_if_missing,
    drop_column_if_present,
    drop_table_if_present,
    table_exists,
)

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("host_cooldowns", sa.Column("platform", sa.String(32), nullable=True))
    if not table_exists("platform_refusals"):
        op.create_table(
            "platform_refusals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("host", sa.String(255), nullable=False, unique=True),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("refused_at", sa.DateTime(), nullable=False),
        )
    create_index_if_missing("ix_platform_refusals_platform", "platform_refusals", ["platform"])


def downgrade() -> None:
    drop_table_if_present("platform_refusals")
    drop_column_if_present("host_cooldowns", "platform")
