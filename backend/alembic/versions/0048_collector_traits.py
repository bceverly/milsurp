"""Import marks, matching numbers, the finish, and a common condition grade.

Six columns on ``items`` and a backfill over everything already stored, for the
reason migration 0037 gave for curio: a fix to how a listing is *read* never
reaches the listings already read, and this is a derivation over text that is
already in the database -- nothing to re-scrape, no vendor to trouble. It is
re-runnable afterwards through ``cli.py traits-backfill``.

Idempotent like every migration here: columns only if absent, and the backfill
only reads rows that carry no reading yet.

Revision ID: 0048
Revises: 0047
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

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("import_marked", sa.Boolean(), nullable=True))
    add_column_if_missing("items", sa.Column("numbers_match", sa.Boolean(), nullable=True))
    add_column_if_missing("items", sa.Column("refinished", sa.Boolean(), nullable=True))
    add_column_if_missing("items", sa.Column("finish_percent", sa.Integer(), nullable=True))
    add_column_if_missing("items", sa.Column("trait_quotes", sa.JSON(), nullable=True))
    add_column_if_missing(
        "items", sa.Column("condition_grade", sa.String(length=16), nullable=True)
    )
    create_index_if_missing("ix_items_condition_grade", "items", ["condition_grade"])

    # Imported here rather than at module scope, as in 0037: a migration that
    # fails to import takes the whole upgrade path down with it.
    from app.services import traits

    counts = traits.backfill(op.get_bind(), only_missing=True)
    log.info(
        "Collector traits: examined %s listing(s) — %s import mark(s), %s numbers, "
        "%s finish(es), %s condition grade(s) read.",
        counts.get("examined", 0),
        counts.get("import", 0),
        counts.get("numbers", 0),
        counts.get("finish", 0),
        counts.get("graded", 0),
    )


def downgrade() -> None:
    if column_exists("items", "condition_grade"):
        drop_index_if_present("ix_items_condition_grade", "items")
    drop_column_if_present("items", "condition_grade")
    drop_column_if_present("items", "trait_quotes")
    drop_column_if_present("items", "finish_percent")
    drop_column_if_present("items", "refinished")
    drop_column_if_present("items", "numbers_match")
    drop_column_if_present("items", "import_marked")
