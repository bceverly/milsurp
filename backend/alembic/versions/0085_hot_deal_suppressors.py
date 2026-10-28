"""A Suppressors tab in hot deals, and its switch in the email.

``hot_deal_preferences.include_suppressors``: on by default like the other
five, so every reader is mailed suppressor deals until they say otherwise.
Idempotent like every migration here.

Revision ID: 0085
Revises: 0084
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import column_exists, drop_column_if_present, table_exists

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("hot_deal_preferences") and not column_exists(
        "hot_deal_preferences", "include_suppressors"
    ):
        op.add_column(
            "hot_deal_preferences",
            sa.Column(
                "include_suppressors", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )


def downgrade() -> None:
    if table_exists("hot_deal_preferences"):
        drop_column_if_present("hot_deal_preferences", "include_suppressors")
