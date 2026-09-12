"""Give bayonets and parts kits their own flags.

Both were "neither a rifle nor a handgun", which is also what a sling, a helmet
and a cleaning kit are. That made them unfindable: somebody watching for a
Carcano bayonet or an Enfield parts kit had to read the whole accessories pile.

They are separate columns rather than one "kind" enum for the same reason
is_rifle and is_pistol are: a listing can be more than one of these at once. A
parts kit is a firearm minus its serialized part, so "ENFIELD NO1 MK2 PARTS
KITS" is a handgun *and* a parts kit, and a filter for either should find it.

Existing rows get 0 and are corrected by `cli.py reclassify`, which re-derives
every flag from the text already stored and needs no network.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # sa.false(), not sa.text("0"). The literal renders per dialect -- "0" for
    # SQLite, "false" for PostgreSQL -- and PostgreSQL refuses an integer
    # default on a boolean column outright. See "Two engines, one schema".
    for column in ("is_bayonet", "is_parts_kit"):
        add_column_if_missing(
            "items",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    drop_column_if_present("items", "is_bayonet")
    drop_column_if_present("items", "is_parts_kit")
