"""When the watchlist poller last re-read a listing's own page.

Distinct from ``last_seen_at``, which is when a scan last met it. This is the
poller's rotation marker: watched listings are re-read oldest-first, so a
watchlist longer than one pass is covered round-robin rather than the same head
of it on every tick.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    existing = _columns(op.get_bind(), "items")
    if not existing or "last_checked_at" in existing:
        return
    op.add_column("items", sa.Column("last_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if "last_checked_at" not in _columns(op.get_bind(), "items"):
        return
    with op.batch_alter_table("items") as batch:
        batch.drop_column("last_checked_at")
