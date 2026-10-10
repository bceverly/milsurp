"""Modern production, and where a maker and its models live on the web.

``firearm_models.modern_production`` -- still made, so a new one can be
bought and the maker describes it -- and ``firearm_models.maker_url``, the
model's page on the maker's site; ``manufacturers.website``, the maker's own
site. Slice 1 of "New-gun prices, and the makers' own pages" in ROADMAP.md.

Idempotent like every migration here.

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "firearm_models",
        sa.Column("modern_production", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column_if_missing("firearm_models", sa.Column("maker_url", sa.String(500), nullable=True))
    add_column_if_missing("manufacturers", sa.Column("website", sa.String(500), nullable=True))


def downgrade() -> None:
    drop_column_if_present("manufacturers", "website")
    drop_column_if_present("firearm_models", "maker_url")
    drop_column_if_present("firearm_models", "modern_production")
