"""Move the manufacturer list out of the code and into a table.

Recognizing one more maker used to be a change to a tuple of regular
expressions in app/services/classify.py: a commit, a review and a deploy for a
fact about the world that the person running the site knows and the programmer
does not. The table is seeded from that tuple on the next startup, so nothing
is lost and the first edit can be made from the admin pages.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import create_table_if_missing, drop_table_if_present

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_missing(
        "manufacturers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1000", index=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    drop_table_if_present("manufacturers")
