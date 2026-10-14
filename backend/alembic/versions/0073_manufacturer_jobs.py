"""The reads of the manufacturers' own sites, started from Site settings.

Asked for on 2026-10-13: the MSRP and variant readers had never been run in
production, because the only way to was a command on the server. A row per
read -- "variants" and "pages" -- holds the request the Site settings button
makes and how the last run went. See app.services.makerjobs.

Revision ID: 0073
Revises: 0072
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import create_table_if_missing, drop_table_if_present

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_missing(
        "manufacturer_jobs",
        sa.Column("name", sa.String(16), primary_key=True),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_summary", sa.String(500), nullable=True),
        sa.Column("last_seconds", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    drop_table_if_present("manufacturer_jobs")
