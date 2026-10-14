"""A handgun's frame size, on listings, models and variants.

Asked for on 2026-10-14: read for every handgun as the barrel is (0074), kept
in the armory -- on a model only ever made in one size, and on each variant --
and used to narrow the versions a listing could be. Columns, an index on the
listing's for filtering, and a read of everything stored: each handgun's
words, and each variant's label. See app.services.frames.

Revision ID: 0075
Revises: 0074
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

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("frame_size", sa.String(16), nullable=True))
    add_column_if_missing("items", sa.Column("frame_quote", sa.String(200), nullable=True))
    add_column_if_missing("firearm_models", sa.Column("frame_size", sa.String(16), nullable=True))
    add_column_if_missing("model_variants", sa.Column("frame_size", sa.String(16), nullable=True))
    create_index_if_missing("ix_items_frame_size", "items", ["frame_size"])

    # Imported here rather than at module scope, as in 0048.
    from app.services import frames

    session = Session(bind=op.get_bind())
    variants = frames.label_variants(session)
    counts = frames.backfill(session)
    session.flush()
    log.info(
        "Frame sizes: %s variant(s) from their labels; %s handgun(s) read, %s stated, "
        "%s from the armory.",
        variants,
        counts.get("examined", 0),
        counts.get("stated", 0),
        counts.get("from_armory", 0),
    )


def downgrade() -> None:
    if column_exists("items", "frame_size"):
        drop_index_if_present("ix_items_frame_size", "items")
    drop_column_if_present("model_variants", "frame_size")
    drop_column_if_present("firearm_models", "frame_size")
    drop_column_if_present("items", "frame_quote")
    drop_column_if_present("items", "frame_size")
