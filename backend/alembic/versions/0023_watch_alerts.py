"""Immediate alerts on a watched listing reaching its target.

The digest answers "what changed since last time" on a schedule the reader
chose, and for a target price that schedule is the wrong one: a rifle that hits
$700 an hour after the daily digest sends is news twenty-three hours later,
which on a shelf where one rifle is one rifle is often too late.

Three columns. ``alert_immediately`` is opt-in, because an alert is an
interruption and somebody who has not asked for one has not asked to be
interrupted. ``alerted_price`` and ``alerted_at`` are the alert's own
watermark: it fires *between* digests and so cannot use ``last_digest_cutoff``,
and without a memory of its own it would mail the same $650 every five minutes
until somebody bought the thing.

The watermark is a price rather than a timestamp on purpose. What an alert asks
is "is this a number I have not told you about", so a vendor who puts a price
back up and drops it again has genuinely done something worth a second email.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "watched_items")
    if not existing:
        return
    if "alert_immediately" not in existing:
        op.add_column(
            "watched_items",
            sa.Column(
                "alert_immediately",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.create_index(
            "ix_watched_items_alert_immediately", "watched_items", ["alert_immediately"]
        )
    if "alerted_price" not in existing:
        op.add_column("watched_items", sa.Column("alerted_price", sa.Float(), nullable=True))
    if "alerted_at" not in existing:
        op.add_column("watched_items", sa.Column("alerted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "watched_items")
    if not existing:
        return
    with op.batch_alter_table("watched_items") as batch:
        if "alert_immediately" in existing:
            batch.drop_index("ix_watched_items_alert_immediately")
            batch.drop_column("alert_immediately")
        for column in ("alerted_price", "alerted_at"):
            if column in existing:
                batch.drop_column(column)
