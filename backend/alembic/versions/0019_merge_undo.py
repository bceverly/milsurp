"""Record what a merge took, so it can be given back.

Merging is the one edit in the armory that cannot be reversed from what is
left behind. It moves the source's model and caliber links onto the target and
then clears the source's own; it copies the source's spellings into the
target's aliases; and on a maker it deletes the source's rows from
``firearm_model_manufacturers`` outright. Afterwards there is no way to tell
which of the target's makers came from the source, or which of its aliases.

So the merge writes down what it consumed before it consumes it, and the undo
reads that back. Null means either "never merged" or "merged before this
column existed" -- 112 rows were already in that state when this ran, and
``unmerge`` handles them on a best-effort basis rather than refusing.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("manufacturers", "calibers", "firearm_models")


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        existing = _columns(bind, table)
        # No table means a database built by create_all(), which already has
        # the column; the column already present means this ran before.
        if not existing or "merge_undo" in existing:
            continue
        # Text rather than JSON: this has to build the same schema on SQLite
        # and PostgreSQL, and the payload is read back through json.loads in
        # one place. See "Two engines, one schema" in README.md.
        op.add_column(table, sa.Column("merge_undo", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if "merge_undo" not in _columns(bind, table):
            continue
        with op.batch_alter_table(table) as batch:
            batch.drop_column("merge_undo")
