"""Record which armory model a listing matched.

The armory has been shaping listings since 0011 — filling a blank caliber,
naming a maker, settling rifle against handgun — and doing all of it invisibly.
Nothing on a listing said *which* model it had matched, so the browse page
could not offer "show me the Mosin-Nagant M91/30s", the detail view could not
link to what is known about the gun, and there was no way to look at a
questionable fill and see where it had come from.

A foreign key rather than the name in text, unlike the maker and caliber
columns beside it. Those hold whatever a vendor wrote; this is only ever set
from a row an admin approved, so it can point at that row and carry everything
on it — the kind, the makers, the reference link — instead of copying any of
it and letting the copy drift.

``ON DELETE SET NULL``. Deleting a model from the armory is a statement about
the armory, not a reason to delete a $4,000 rifle.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
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
    if not existing or "firearm_model_id" in existing:
        return

    # No ForeignKey in the DDL. SQLite cannot add one to an existing table
    # without rebuilding it, and rebuilding `items` — the largest table here,
    # with photos and price history hanging off it — is a far worse trade than
    # a column the application constrains itself. The ORM declares the
    # relationship, which is what every reader goes through.
    op.add_column("items", sa.Column("firearm_model_id", sa.Integer(), nullable=True))
    op.create_index("ix_items_firearm_model_id", "items", ["firearm_model_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "firearm_model_id" not in _columns(bind, "items"):
        return
    with op.batch_alter_table("items") as batch:
        batch.drop_index("ix_items_firearm_model_id")
        batch.drop_column("firearm_model_id")
