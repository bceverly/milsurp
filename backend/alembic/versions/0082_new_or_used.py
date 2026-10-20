"""Whether a listing is a new gun or a used one.

Asked for on 2026-10-20 with the carry shops, which sell distributors' new
guns beside a shelf of used ones: ``items.is_new`` (True new, False used, null
not known), indexed for the Inventory's "New or used" filter, and every stored
listing filed by its shop and its words (app.services.newness).

Revision ID: 0082
Revises: 0081
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.migration_utils import (
    add_column_if_missing,
    column_exists,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
)

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("is_new", sa.Boolean(), nullable=True))
    create_index_if_missing("ix_items_is_new", "items", ["is_new"])

    # Imported here rather than at module scope, as in 0075.
    from app.services import newness

    session = Session(bind=op.get_bind())
    counts = newness.backfill(session)
    log.info(
        "New or used: %s new, %s used, %s not known.",
        counts["new"],
        counts["used"],
        counts["unknown"],
    )


def downgrade() -> None:
    if column_exists("items", "is_new"):
        drop_index_if_present("ix_items_is_new", "items")
    drop_column_if_present("items", "is_new")
