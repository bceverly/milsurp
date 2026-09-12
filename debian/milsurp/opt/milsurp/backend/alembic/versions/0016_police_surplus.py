"""Give police surplus its own bucket in the browse filter.

Departments trade their duty weapons in by the lot and dealers sell them as a
named section. It is not military surplus and it is the same question this
catalog exists to ask -- somebody's service weapon, sold on, in quantity -- so
it gets its own Type rather than being scattered through Rifles and Handguns.

**Not a sixth mutually exclusive kind.** A police trade-in Glock *is* a
handgun, and ``is_pistol`` keeps saying so: the armory, the caliber work and
every other question about what a listing is should get the true answer. What
this column changes is only which bucket the browse filter counts it in --
see KINDS in ``services/search.py``, where police surplus is subtracted from
Rifles and Handguns so the buckets still partition the catalog.

Nullable is not an option here: every filter clause reads it, and a NULL would
drop the row out of every bucket including "Other". Defaults false, and
``make reclassify`` fills it in from each listing's stored category.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "items")
    if not existing or "is_police_surplus" in existing:
        return

    # sa.false(), not sa.text("0"): PostgreSQL refuses an integer default on a
    # boolean column. See "Two engines, one schema" in README.md.
    op.add_column(
        "items",
        sa.Column("is_police_surplus", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_items_is_police_surplus", "items", ["is_police_surplus"])


def downgrade() -> None:
    bind = op.get_bind()
    if "is_police_surplus" not in _columns(bind, "items"):
        return
    with op.batch_alter_table("items") as batch:
        # The index goes inside the batch: SQLite rebuilds the table from what
        # it reflects and would recreate an index over a column that has gone.
        # See 0011's downgrade, which is where that was learned.
        for index in sa.inspect(bind).get_indexes("items"):
            if "is_police_surplus" in index["column_names"]:
                batch.drop_index(index["name"])
        batch.drop_column("is_police_surplus")
