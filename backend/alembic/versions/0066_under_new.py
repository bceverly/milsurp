"""Hot deals found against the new price, as well as against peers.

A listing linked to one variant whose new price is known (slice 4 of "New-gun
prices") is a deal when it is far enough under new -- asked for on
2026-10-11 as a second signal beside the used median. On
``hot_deal_settings``, how far under new it must be; on ``hot_deals``, the new
price and how far under it the listing is. The peer figures become optional,
because a deal found against new may have too few peers for a median.

Idempotent like every migration here.

Revision ID: 0066
Revises: 0065
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import add_column_if_missing, column_exists, drop_column_if_present

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

DEAL_COLUMNS = (
    sa.Column("new_price", sa.Float(), nullable=True),
    sa.Column("under_new_percent", sa.Float(), nullable=True),
)

#: The peer figures, which a deal found only against new does not have.
PEER_FIGURES = (
    ("median_price", sa.Float()),
    ("discount_percent", sa.Float()),
    ("cheaper_than", sa.Integer()),
    ("peer_count", sa.Integer()),
    ("vendor_count", sa.Integer()),
)


def _peer_figures(nullable: bool) -> None:
    # SQLite cannot change a column's nullability in place; batch_alter_table
    # rebuilds the table around the change.
    with op.batch_alter_table("hot_deals") as batch:
        for name, kind in PEER_FIGURES:
            batch.alter_column(
                name, existing_type=kind, nullable=nullable, existing_nullable=not nullable
            )


def upgrade() -> None:
    add_column_if_missing(
        "hot_deal_settings",
        sa.Column("min_under_new_percent", sa.Integer(), nullable=False, server_default="25"),
    )
    for column in DEAL_COLUMNS:
        add_column_if_missing("hot_deals", column)
    _peer_figures(nullable=True)


def downgrade() -> None:
    # The table is a cache the next pass rebuilds, so a row with no peer
    # figures is dropped rather than given invented ones.
    if column_exists("hot_deals", "median_price"):
        op.execute("DELETE FROM hot_deals WHERE median_price IS NULL")
        _peer_figures(nullable=False)
    for column in reversed(DEAL_COLUMNS):
        drop_column_if_present("hot_deals", column.name)
    drop_column_if_present("hot_deal_settings", "min_under_new_percent")
