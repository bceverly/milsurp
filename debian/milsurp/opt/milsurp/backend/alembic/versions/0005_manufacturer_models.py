"""Model numbers, tied to the maker that made them.

A dealer names the model far more often than the maker: "RUSSIAN M44 CARBINES"
and "WW2 RUSSIAN 91/30 RIFLES" are both Mosin-Nagants and neither says Mosin,
or Nagant, anywhere. Those were being stuffed into the manufacturer's alias
box, which conflated two different facts — how a firm's name is spelled, and
what that firm made — and left a model nowhere to record its own caliber or
type later.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import create_table_if_missing, drop_table_if_present

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_missing(
        "manufacturer_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "manufacturer_id",
            sa.Integer(),
            sa.ForeignKey("manufacturers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("manufacturer_id", "name", name="uq_model_per_manufacturer"),
    )


def downgrade() -> None:
    drop_table_if_present("manufacturer_models")
