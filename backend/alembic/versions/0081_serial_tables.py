"""Published serial-to-date tables, a range to a row.

"Serial tables" in ROADMAP.md, built on 2026-10-19: a model's serials from
one maker, from one number to another, made in these years, and where that
was read. Shipped in the armory file under each model and loaded with it;
this makes the table.

Revision ID: 0081
Revises: 0080
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import create_table_if_missing, drop_table_if_present

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_missing(
        "serial_ranges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("firearm_models.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "manufacturer_id",
            sa.Integer(),
            sa.ForeignKey("manufacturers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("prefix", sa.String(8), nullable=False, server_default=""),
        sa.Column("suffix", sa.String(8), nullable=False, server_default=""),
        sa.Column("serial_low", sa.Integer(), nullable=False),
        sa.Column("serial_high", sa.Integer(), nullable=False),
        sa.Column("year_from", sa.Integer(), nullable=False),
        sa.Column("year_to", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    drop_table_if_present("serial_ranges")
