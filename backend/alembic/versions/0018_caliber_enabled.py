"""Let a cartridge be switched off, the way a model or a maker already can.

Three tables behaving three ways is what made rejecting a row confusing. A
model or a maker can be *disabled* -- kept, taken out of matching, and left
where a scan will find it and stop proposing the name again. A caliber could
not, so its only durable "no" was **Send back for approval**, which is the same
mechanism wearing a name that reads like an undo rather than a decision.

Deleting is not the answer for any of the three: every ``propose_*`` in
``services/armory.py`` looks a name up regardless of status, so *any* surviving
row suppresses re-proposal and a deleted one comes back the next time a title
names it. The row is the tombstone. This gives calibers the same switch the
other two have.

Defaults true, because every row that exists when this runs is in use.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "calibers")
    # No table means a database built by create_all(), which already has it;
    # the column already present means this ran before. Either way, nothing.
    if not existing or "enabled" in existing:
        return

    # sa.true(), not sa.text("1"): PostgreSQL refuses an integer default on a
    # boolean column. See "Two engines, one schema" in README.md.
    op.add_column(
        "calibers",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_calibers_enabled", "calibers", ["enabled"])


def downgrade() -> None:
    bind = op.get_bind()
    if "enabled" not in _columns(bind, "calibers"):
        return
    with op.batch_alter_table("calibers") as batch:
        # The index goes inside the batch: SQLite rebuilds the table from what
        # it reflects and would recreate an index over a column that has gone.
        # See 0011's downgrade, which is where that was learned.
        for index in sa.inspect(bind).get_indexes("calibers"):
            if "enabled" in index["column_names"]:
                batch.drop_index(index["name"])
        batch.drop_column("enabled")
