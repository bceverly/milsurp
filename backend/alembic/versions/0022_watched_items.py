"""A per-user watchlist: the listings somebody is following.

The catalog answers "what is on the shelves", and since the price spectrum "is
this a good deal". It could not answer "tell me when *that one* moves", which
is the question somebody has about the rifle they have decided they want and
will not pay this week's price for. The only way to find out was to come back
and look, which is the thing a monitor is supposed to save you.

One row per (user, listing). Nothing about the listing is copied onto it: the
price, the title and whether it has sold all live on the item and change under
it, and a copy here would be a second version of the truth whose only job is to
go stale. The row holds the fact that somebody cares, their optional target
price, and their own note.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("watched_items"):
        return
    op.create_table(
        "watched_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        # Starring a listing twice is one watch, not two. Enforced here rather
        # than left to the endpoint, because the endpoint is not the only way
        # rows arrive -- a restore, a script, a future import.
        sa.UniqueConstraint("user_id", "item_id", name="uq_watched_item"),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("watched_items"):
        op.drop_table("watched_items")
