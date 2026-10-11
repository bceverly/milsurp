"""What it costs to shoot a caliber.

On ``calibers``: the Wikipedia article and the bullet diameter read from it;
the factory cost per round, with its source, page and date; whether Lee
Precision makes dies for it; the cost of a projectile; and AmmoSeek's own
query for it. A ``caliber_bullet_weights`` table, one caliber to many
weights, each with its own cheapest round and projectile. An
``ammo_settings`` row for how often all of it is refreshed. "Ammunition" in
ROADMAP.md, asked for on 2026-10-11.

Idempotent like every migration here.

Revision ID: 0067
Revises: 0066
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    add_column_if_missing,
    create_index_if_missing,
    create_table_if_missing,
    drop_column_if_present,
    drop_index_if_present,
    drop_table_if_present,
)

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

COLUMNS = (
    sa.Column("wikipedia_url", sa.String(500), nullable=True),
    sa.Column("bullet_diameter_in", sa.Float(), nullable=True),
    sa.Column("wikipedia_read_at", sa.DateTime(), nullable=True),
    sa.Column("factory_cpr", sa.Float(), nullable=True),
    sa.Column("factory_source", sa.String(32), nullable=True),
    sa.Column("factory_url", sa.String(500), nullable=True),
    sa.Column("factory_checked_at", sa.DateTime(), nullable=True),
    sa.Column("lee_dies", sa.Boolean(), nullable=True),
    sa.Column("lee_url", sa.String(500), nullable=True),
    sa.Column("lee_checked_at", sa.DateTime(), nullable=True),
    sa.Column("projectile_cost", sa.Float(), nullable=True),
    sa.Column("projectile_url", sa.String(500), nullable=True),
    sa.Column("projectile_checked_at", sa.DateTime(), nullable=True),
    sa.Column("ammoseek_query", sa.String(300), nullable=True),
)


def upgrade() -> None:
    for column in COLUMNS:
        add_column_if_missing("calibers", column)
    create_table_if_missing(
        "caliber_bullet_weights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "caliber_id",
            sa.Integer(),
            sa.ForeignKey("calibers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grains", sa.Float(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="wikipedia"),
        sa.Column("factory_cpr", sa.Float(), nullable=True),
        sa.Column("projectile_cost", sa.Float(), nullable=True),
        sa.UniqueConstraint("caliber_id", "grains", name="uq_caliber_bullet_weight"),
    )
    create_index_if_missing(
        "ix_caliber_bullet_weights_caliber_id", "caliber_bullet_weights", ["caliber_id"]
    )
    create_table_if_missing(
        "ammo_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("refresh_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("last_summary", sa.String(500), nullable=True),
        sa.Column("last_seconds", sa.Float(), nullable=True),
    )
    bind = op.get_bind()
    if not bind.execute(sa.text("SELECT 1 FROM ammo_settings WHERE id = 1")).first():
        op.execute("INSERT INTO ammo_settings (id, refresh_days) VALUES (1, 7)")


def downgrade() -> None:
    drop_table_if_present("ammo_settings")
    drop_index_if_present("ix_caliber_bullet_weights_caliber_id", "caliber_bullet_weights")
    drop_table_if_present("caliber_bullet_weights")
    for column in reversed(COLUMNS):
        drop_column_if_present("calibers", column.name)
