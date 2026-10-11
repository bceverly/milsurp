"""Wikipedia for makers, and proposed articles awaiting a person.

``manufacturers.wikipedia_url``, beside the one models have always had; and
``reference_proposals``, the articles a pass over Wikipedia's search proposes
for a maker or model with none, each waiting to be accepted or rejected on the
Armory page. See "Wikipedia for every maker and model" in ROADMAP.md.

Idempotent like every migration here.

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import (
    add_column_if_missing,
    create_table_if_missing,
    drop_column_if_present,
    drop_table_if_present,
)

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "manufacturers", sa.Column("wikipedia_url", sa.String(500), nullable=True)
    )
    create_table_if_missing(
        "reference_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False, index=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("confident", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("target_type", "target_id", "url", name="uq_reference_proposal"),
    )


def downgrade() -> None:
    drop_table_if_present("reference_proposals")
    drop_column_if_present("manufacturers", "wikipedia_url")
