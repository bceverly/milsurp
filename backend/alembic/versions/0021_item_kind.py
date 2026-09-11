"""The finer kind of a firearm: flintlock pistol, percussion carbine, revolver.

The browse filter's five buckets -- rifle, handgun, bayonet, parts kit, police
surplus -- partition the catalog and are the right answer to "what am I looking
at". They are not the right answer to "show me the revolvers", and a collector
asks that one constantly: a flintlock pistol and a percussion revolver are
different objects, and both are "handgun" to the filter.

``FirearmKind`` has carried the finer vocabulary since the armory shipped, on
the *model* rather than the listing. Reading it through the join is possible and
awkward -- facets are tallied over a column -- and it also throws away the
second source, which is better on the shelves the armory does not reach: Simpson
Ltd. state "Revolver" and "Shotgun" per listing in ``stated_kind``.

So the answer is resolved once and stored. Two sources, in order:

* the linked armory model's kind, which is curated and the finer of the two --
  it knows percussion_revolver where a vendor says Revolver;
* the vendor's own word, which reaches 4,713 listings the models do not.

Together they cover 6,624 of 8,773 firearms (76%). Null means neither source
had an answer, which is a real state and not a gap.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
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
    if not existing or "kind" in existing:
        return
    op.add_column("items", sa.Column("kind", sa.String(length=32), nullable=True))
    op.create_index("ix_items_kind", "items", ["kind"])


def downgrade() -> None:
    bind = op.get_bind()
    if "kind" not in _columns(bind, "items"):
        return
    with op.batch_alter_table("items") as batch:
        batch.drop_index("ix_items_kind")
        batch.drop_column("kind")
