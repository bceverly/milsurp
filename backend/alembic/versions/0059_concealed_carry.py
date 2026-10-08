"""Concealed carry: a Type of its own, and a hot-deals tab to match.

``items.is_concealed_carry``: compact and subcompact pistols in 9mm, 10mm,
.40, .45 and .380, and small revolvers in .32 H&R, .327, .38 Special and .357
-- see app/services/carry.py for the rule. Like ``is_police_surplus`` it sits
beside ``is_pistol`` rather than replacing it: a Glock 19 is still a handgun,
and only the browse filter's partition and the hot-deals buckets treat the
two differently. Concealed carry outranks police surplus there, so a traded-in
Glock 19 is found where somebody shopping for a carry gun looks.

``hot_deal_preferences.include_concealed_carry``: whether a person's hot-deals
email carries the new tab, true by default like the other three.

Defaults false, never NULL -- every filter clause reads the column -- and the
package's catch-up (``reclassify --recompute``) fills it in for every stored
listing on upgrade. Idempotent like every migration here.

Revision ID: 0059
Revises: 0058
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

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEX = "ix_items_is_concealed_carry"


def upgrade() -> None:
    # A plain ADD COLUMN, not add_column_if_missing's batch mode: SQLite
    # rebuilds the table for a batch, and it cannot rebuild ``items`` around
    # the generated ``search_document`` column. 0016 added is_police_surplus
    # the same way for the same reason. An ADD COLUMN with a constant default
    # needs no rebuild on either engine.
    #
    # sa.false(), not sa.text("0"): PostgreSQL refuses an integer default on a
    # boolean column. See "Two engines, one schema" in README.md.
    if table_exists("items") and not column_exists("items", "is_concealed_carry"):
        op.add_column(
            "items",
            sa.Column(
                "is_concealed_carry", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    create_index_if_missing(INDEX, "items", ["is_concealed_carry"])
    if table_exists("hot_deal_preferences") and not column_exists(
        "hot_deal_preferences", "include_concealed_carry"
    ):
        op.add_column(
            "hot_deal_preferences",
            sa.Column(
                "include_concealed_carry", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )


def downgrade() -> None:
    if table_exists("hot_deal_preferences"):
        drop_column_if_present("hot_deal_preferences", "include_concealed_carry")
    if table_exists("items"):
        drop_index_if_present(INDEX, "items")
        drop_column_if_present("items", "is_concealed_carry")
