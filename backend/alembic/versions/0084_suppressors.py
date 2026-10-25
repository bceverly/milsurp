"""Suppressors: a Type of their own.

``items.is_suppressor``: a suppressor or silencer, not a part for one -- see
app/services/suppressors.py for the rule. Beside ``is_black_powder`` and the
other Type flags; a suppressor is never a gun, so it partitions cleanly out of
"Other parts & accessories", where it used to fall.

Defaults false, never NULL, and the package's catch-up (``reclassify
--recompute``) fills it in for every stored listing on upgrade. Idempotent like
every migration here.

Revision ID: 0084
Revises: 0083
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    column_exists,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
    table_exists,
)

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEX = "ix_items_is_suppressor"


def upgrade() -> None:
    # A plain ADD COLUMN, as 0060 did for is_black_powder and for the same
    # reason: SQLite cannot rebuild ``items`` around its generated column.
    if table_exists("items") and not column_exists("items", "is_suppressor"):
        op.add_column(
            "items",
            sa.Column("is_suppressor", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    create_index_if_missing(INDEX, "items", ["is_suppressor"])


def downgrade() -> None:
    if table_exists("items"):
        drop_index_if_present(INDEX, "items")
        drop_column_if_present("items", "is_suppressor")
