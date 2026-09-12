"""Keep the type a vendor stated, rather than re-deriving one they told us.

``kind_from_category`` already exists for the case where a dealer's *section*
says what the thing is -- "Handguns" tells you something no heuristic gets from
"BELGIAN Model 1910/22 Browning". But a section is one label for hundreds of
listings, and two vendors now state the type per listing instead: Simpson Ltd.
in a ``Type`` field ("Pistol", "Rifle", "Revolver", "Shotgun") and GunPrime in
each product's own taxons.

Simpson made the case for the column. 1,051 of their 5,241 listings typed as
neither rifle nor handgun, because collector shorthand carries no noun to key
on -- "SWISS 1906/24 RIG", "DWM P.08 FINNISH MILITARY", "ERFURT 1918 MILITARY".
Every one of those has ``Type: Pistol`` on it.

Stored rather than applied at scan time, because ``reclassify`` re-derives
everything from what the row holds: a type applied during the scan and not
written down would be thrown away by the next ``make reclassify``, which is
exactly the trap the ``--fields`` flag was added for.

Null is the normal case, and means "this vendor said nothing" -- which is also
what Simpson use for accessories, so the blank is meaningful rather than
missing.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
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
    if not existing or "stated_kind" in existing:
        return
    op.add_column("items", sa.Column("stated_kind", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "stated_kind" not in _columns(bind, "items"):
        return
    with op.batch_alter_table("items") as batch:
        batch.drop_column("stated_kind")
