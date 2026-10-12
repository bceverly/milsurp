"""The caliber data refreshed a part at a time.

Asked for on 2026-10-12: separate buttons for the calibers' Wikipedia facts,
for reloading bullets and for ammunition prices, with one to do all three.
``requested_parts`` is what was asked for, ``last_parts`` what the last
refresh covered, and ``last_full_at`` the last refresh covering all three,
which the schedule now counts from -- updating one part by hand should not
put the others off for another week.

Revision ID: 0070
Revises: 0069
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("ammo_settings", sa.Column("requested_parts", sa.String(64)))
    add_column_if_missing("ammo_settings", sa.Column("last_parts", sa.String(64)))
    add_column_if_missing("ammo_settings", sa.Column("last_full_at", sa.DateTime()))
    # Every refresh before this one was a full one.
    op.execute("UPDATE ammo_settings SET last_full_at = last_run_at WHERE last_full_at IS NULL")


def downgrade() -> None:
    for column in ("last_full_at", "last_parts", "requested_parts"):
        drop_column_if_present("ammo_settings", column)
