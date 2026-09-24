"""When a listing sold, not only whether it has.

``items.is_sold`` said a listing had sold; nothing said when. The Market page's
time-to-sell figures need the date, and it cannot be reconstructed afterwards:
``price_history`` records price changes, not availability, and ``delisted_at``
is a different event that most shops never trigger for a sale. So this starts
recording it, and the figures only ever describe sales seen after it did.

No backfill, on purpose. Stamping every already-sold listing with today's date
would invent a thousand sales that all happened this afternoon.

Idempotent like every migration here.

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import (
    add_column_if_missing,
    column_exists,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
)

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("sold_at", sa.DateTime(), nullable=True))
    create_index_if_missing("ix_items_sold_at", "items", ["sold_at"])


def downgrade() -> None:
    if column_exists("items", "sold_at"):
        drop_index_if_present("ix_items_sold_at", "items")
    drop_column_if_present("items", "sold_at")
