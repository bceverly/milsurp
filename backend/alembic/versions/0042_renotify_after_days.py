"""How long a mailed price stays quiet: ``hot_deal_settings.renotify_after_days``.

Hot-deal emails and watchlist target alerts remember the price they mentioned,
and used to stay quiet about that price for good. Now a notice older than this
many days no longer suppresses anything, so a listing still at a good price
gets one reminder instead of going dark forever. 30 by default; 0 turns
reminders off. It lives with the hot-deal settings because that is the page an
administrator tunes notifications on, and it governs both kinds of message. See
``app/services/renotify.py``.

Idempotent like every migration here.

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "hot_deal_settings",
        sa.Column("renotify_after_days", sa.Integer(), nullable=False, server_default="30"),
    )


def downgrade() -> None:
    drop_column_if_present("hot_deal_settings", "renotify_after_days")
