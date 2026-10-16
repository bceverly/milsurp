"""How many rounds a gun holds, on listings and on models.

Asked for on 2026-10-16: a gun's capacity, "the non-California standard
capacity ... as an attribute of the model", shown on the listing and
searchable. A listing takes its own words where it states one, its model's
standard capacity where it does not; each model with none is given the one
its listings state most often (app.services.capacity.standard). Columns, an
index on the listing's for searching, and a read of everything stored.

Revision ID: 0080
Revises: 0079
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

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("capacity", sa.Integer(), nullable=True))
    add_column_if_missing("items", sa.Column("capacity_quote", sa.String(200), nullable=True))
    add_column_if_missing("firearm_models", sa.Column("capacity", sa.Integer(), nullable=True))
    create_index_if_missing("ix_items_capacity", "items", ["capacity"])

    # Imported here rather than at module scope, as in 0075.
    from app.services import capacity

    session = Session(bind=op.get_bind())
    counts = capacity.backfill(session)
    session.flush()
    log.info(
        "Capacity: %s gun(s) read, %s stating one; %s model(s) given a standard capacity, "
        "%s listing(s) taking their model's.",
        counts["examined"],
        counts["stated"],
        counts["models"],
        counts["from_armory"],
    )


def downgrade() -> None:
    if column_exists("items", "capacity"):
        drop_index_if_present("ix_items_capacity", "items")
    drop_column_if_present("firearm_models", "capacity")
    drop_column_if_present("items", "capacity_quote")
    drop_column_if_present("items", "capacity")
