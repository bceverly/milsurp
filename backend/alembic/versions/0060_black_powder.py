"""Black powder: a Type of its own, and a hot-deals tab to match.

``items.is_black_powder``: percussion and flintlock guns, originals and
reproductions -- see app/services/blackpowder.py for the rule. It sits beside
``is_rifle``/``is_pistol`` as ``is_concealed_carry`` and ``is_police_surplus``
do, and outranks both in the browse filter's partition and the hot-deals
buckets: a percussion revolver is never a carry gun or a trade-in.

``hot_deal_preferences.include_black_powder``: the new tab in a reader's
hot-deals email, on by default like the others.

Defaults false, never NULL, and the package's catch-up (``reclassify
--recompute``) fills it in for every stored listing on upgrade. Idempotent like
every migration here.

Revision ID: 0060
Revises: 0059
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

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEX = "ix_items_is_black_powder"


def upgrade() -> None:
    # A plain ADD COLUMN, not add_column_if_missing's batch mode: SQLite
    # rebuilds the table for a batch, and it cannot rebuild ``items`` around
    # the generated ``search_document`` column. 0016 added is_police_surplus
    # the same way for the same reason. An ADD COLUMN with a constant default
    # needs no rebuild on either engine.
    #
    # sa.false(), not sa.text("0"): PostgreSQL refuses an integer default on a
    # boolean column. See "Two engines, one schema" in README.md.
    if table_exists("items") and not column_exists("items", "is_black_powder"):
        op.add_column(
            "items",
            sa.Column("is_black_powder", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    create_index_if_missing(INDEX, "items", ["is_black_powder"])
    if table_exists("hot_deal_preferences") and not column_exists(
        "hot_deal_preferences", "include_black_powder"
    ):
        op.add_column(
            "hot_deal_preferences",
            sa.Column(
                "include_black_powder", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )


def downgrade() -> None:
    if table_exists("hot_deal_preferences"):
        drop_column_if_present("hot_deal_preferences", "include_black_powder")
    if table_exists("items"):
        drop_index_if_present(INDEX, "items")
        drop_column_if_present("items", "is_black_powder")
