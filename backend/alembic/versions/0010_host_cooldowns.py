"""Remember, across processes, that a host told us to go away.

A 429 sets a slower pace for the rest of the scan and then the process exits
and the knowledge goes with it. So the scheduler learns that Checkpoint
Charlie's is refusing, backs off for an hour, finishes — and then `make photos`
starts from scratch on the same host thirty seconds later, and so does the next
scan, and so does anything else that fetches. From the vendor's side that is
not one crawler being told to slow down; it is several, none of which listens.

The database is the only thing those processes share, which is the same reason
scan ownership moved here in 0006.

``until`` is when it becomes reasonable to ask again, ``refusals`` counts the
consecutive ones so the wait can grow, and ``reason`` says what happened for
whoever is wondering why a site went quiet.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("host_cooldowns"):
        return
    op.create_table(
        "host_cooldowns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("until", sa.DateTime(), nullable=False, index=True),
        sa.Column("refusals", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("first_refused_at", sa.DateTime(), nullable=True),
        sa.Column("last_refused_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("host_cooldowns"):
        op.drop_table("host_cooldowns")
