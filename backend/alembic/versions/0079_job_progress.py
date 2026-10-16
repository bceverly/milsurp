"""When a Site settings job started, and what it is on now.

Asked for on 2026-10-16: "how do i know when update msrps and variants is
done? ... can we show when something is 'running' and a 'last updated
date/time' and 'last status' (success, warning or failure)". The button
cleared the request when the scheduler took it and the result was written at
the end, so nothing said a run was going. Both job tables -- the
manufacturer and listing reads, and the caliber data -- gain the start time
and a line of progress, cleared when the run ends.

Revision ID: 0079
Revises: 0078
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLES = ("manufacturer_jobs", "ammo_settings")


def upgrade() -> None:
    for table in _TABLES:
        add_column_if_missing(table, sa.Column("started_at", sa.DateTime(), nullable=True))
        add_column_if_missing(table, sa.Column("progress", sa.String(200), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        drop_column_if_present(table, "progress")
        drop_column_if_present(table, "started_at")
