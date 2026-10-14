"""Every gun's barrel length and whether it is threaded.

Asked for on 2026-10-13: both read from each listing's own words, searchable,
and the length used to narrow the variants a listing could be. The length had
been read only from the titles of models still in production; it is now read
for every firearm, from the title and the description. Two columns, an index
on the length for the range filter, and a backfill over everything stored --
a derivation over text already in the database, as in 0048. Re-runnable
through ``cli.py barrels-backfill``. See app.services.barrels.

Revision ID: 0074
Revises: 0073
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    add_column_if_missing,
    column_exists,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
)

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("barrel_threaded", sa.Boolean(), nullable=True))
    add_column_if_missing("items", sa.Column("barrel_quotes", sa.JSON(), nullable=True))
    create_index_if_missing("ix_items_barrel_inches", "items", ["barrel_inches"])
    create_index_if_missing("ix_items_barrel_threaded", "items", ["barrel_threaded"])

    # Imported here rather than at module scope, as in 0048.
    from app.services import barrels

    counts = barrels.backfill(op.get_bind())
    log.info(
        "Barrels: examined %s gun(s) — %s length(s), %s threaded, %s stated not threaded.",
        counts.get("examined", 0),
        counts.get("length", 0),
        counts.get("threaded", 0),
        counts.get("not_threaded", 0),
    )


def downgrade() -> None:
    if column_exists("items", "barrel_threaded"):
        drop_index_if_present("ix_items_barrel_threaded", "items")
    drop_index_if_present("ix_items_barrel_inches", "items")
    drop_column_if_present("items", "barrel_quotes")
    drop_column_if_present("items", "barrel_threaded")
