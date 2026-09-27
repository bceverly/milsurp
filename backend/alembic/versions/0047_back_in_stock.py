"""Back-in-stock alerts: ``items.restocked_at`` and a watch's ``alert_restock``.

A scan that sees a sold-out listing available again stamps
``items.restocked_at``. A watch with ``alert_restock`` is mailed the moment
that happens, once per return (``restock_alerted_at``), with or without a
target price: at the CMP a grade reappearing is the whole event.

Idempotent like every migration here.

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("restocked_at", sa.DateTime(), nullable=True))
    add_column_if_missing(
        "watched_items",
        sa.Column("alert_restock", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column_if_missing(
        "watched_items", sa.Column("restock_alerted_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    drop_column_if_present("watched_items", "restock_alerted_at")
    drop_column_if_present("watched_items", "alert_restock")
    drop_column_if_present("items", "restocked_at")
