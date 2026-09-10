"""Let a maker say where it is from.

Country is the weakest field this catalog holds: measured over 4,562 active
listings, 1,407 had none -- and **1,247 of those already carried a
manufacturer**. Glock on 143 of them, Smith & Wesson on 132, Colt on 126,
Mauser on 100, Sig Sauer on 90. The fact needed to fill them in was one column
away and nothing had it.

**It is the weakest of the three answers, and it goes last.** A country in this
catalog is the origin of the *pattern*, not the provenance of the gun. A model
row states that directly and is right. A maker's country is a decent proxy and
is wrong for exactly the cases surplus is full of: a Yugoslav-built M24/47 is a
German pattern, an Egyptian Hakim is a Swedish one. So the fill order is the
listing, then the model, then this -- and it only ever answers a blank. See
``armory.fill_in``, where the order is enforced and tested.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "manufacturers")
    # No table means a database built by create_all(), which already has it;
    # the column already present means this ran before. Either way, nothing.
    if not existing or "country" in existing:
        return

    # Nullable with no default: "we have not been told" is a real state here
    # and is not the same as any particular country. The fill is one-directional
    # and a NULL simply declines to answer.
    op.add_column("manufacturers", sa.Column("country", sa.String(length=64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "country" not in _columns(bind, "manufacturers"):
        return
    with op.batch_alter_table("manufacturers") as batch:
        # Inside the batch, per 0011's downgrade: SQLite rebuilds the table
        # from what it reflects and would recreate an index over a dropped
        # column. This column carries none today; the loop is what keeps that
        # true if one is added later.
        for index in sa.inspect(bind).get_indexes("manufacturers"):
            if "country" in index["column_names"]:
                batch.drop_index(index["name"])
        batch.drop_column("country")
