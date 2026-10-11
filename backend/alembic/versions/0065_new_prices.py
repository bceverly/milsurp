"""A variant's current price new, from gun.deals.

On ``model_variants``: the lowest in-stock price across the stores gun.deals
lists for its UPC, how many stores have it, the gun.deals page it came from
(shown as the source), and when that was last asked. Slice 4 of "New-gun
prices, and the makers' own pages" in ROADMAP.md.

Idempotent like every migration here.

Revision ID: 0065
Revises: 0064
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

COLUMNS = (
    sa.Column("new_price", sa.Float(), nullable=True),
    sa.Column("new_stores", sa.Integer(), nullable=True),
    sa.Column("new_price_url", sa.String(500), nullable=True),
    sa.Column("new_price_checked_at", sa.DateTime(), nullable=True),
)


def upgrade() -> None:
    for column in COLUMNS:
        add_column_if_missing("model_variants", column)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        drop_column_if_present("model_variants", column.name)
