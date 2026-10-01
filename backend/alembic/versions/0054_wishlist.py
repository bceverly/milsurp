"""The wishlist, and whether a reader holds a C&R license.

``wishlist_items`` (a listing a reader means to buy, with its price when
added and what the last alert about it said), ``users.has_cr_license``, which
lets the wishlist leave the transfer fee off a C&R-eligible gun, and the
reader's wishlist alerts switch and budget. See ``app.services.wishlist``.

Idempotent like every migration here.

Revision ID: 0054
Revises: 0053
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import add_column_if_missing, drop_column_if_present, table_exists

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "users",
        sa.Column("has_cr_license", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column_if_missing(
        "users",
        sa.Column("wishlist_alerts", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column_if_missing("users", sa.Column("wishlist_budget", sa.Float(), nullable=True))
    if not table_exists("wishlist_items"):
        _create_table()
    for column in (
        sa.Column("price_when_added", sa.Float(), nullable=True),
        sa.Column("told_price", sa.Float(), nullable=True),
        sa.Column("told_state", sa.String(16), nullable=True),
        sa.Column("told_at", sa.DateTime(), nullable=True),
    ):
        add_column_if_missing("wishlist_items", column)


def _create_table() -> None:
    op.create_table(
        "wishlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "item_id", name="uq_wishlist_item"),
    )
    op.create_index("ix_wishlist_items_user_id", "wishlist_items", ["user_id"])
    op.create_index("ix_wishlist_items_item_id", "wishlist_items", ["item_id"])


def downgrade() -> None:
    if table_exists("wishlist_items"):
        op.drop_table("wishlist_items")
    drop_column_if_present("users", "wishlist_budget")
    drop_column_if_present("users", "wishlist_alerts")
    drop_column_if_present("users", "has_cr_license")
