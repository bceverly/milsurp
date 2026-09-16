"""What a person decided about one listing, kept across re-scrapes.

Everything the application knows about a listing beyond the vendor's own words
is derived: the caliber read out of a title, the country inferred from a
maker's name, the model matched from the armory. All of it is recomputed on
every scan, which is what makes a rule fix reach eleven thousand rows at once
-- and what makes a correction by hand impossible, because the next scan
derives the old answer again.

This is the escape hatch. A row here says "whatever the rules conclude, this
listing is a 7.65 Parabellum", and it is applied last, after the heuristics and
after the armory. One row per listing, and only the fields somebody actually
set: a NULL means "no opinion", not "blank it".

**Kept in its own table rather than as columns on `items`.** Not for
tidiness -- the reason is that the override has to survive `reclassify
--recompute`, which exists to rebuild derived fields and would have every
reason to clear a column sitting among them. A separate table cannot be
mistaken for derived data.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("item_overrides"):
        return
    op.create_table(
        "item_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Unique: one opinion per listing. A second row would be a second
        # answer with nothing to say which is current.
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("caliber", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("manufacturer", sa.String(length=150), nullable=True),
        sa.Column("model", sa.String(length=150), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=True),
        # Why, in the words of whoever decided. An override with no reason is
        # one nobody can safely undo later.
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "set_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("set_by_name", sa.String(length=150), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("item_overrides"):
        op.drop_table("item_overrides")
