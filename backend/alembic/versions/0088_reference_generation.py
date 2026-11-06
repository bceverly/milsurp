"""A generation counter for the reference tables.

``reference_generation``: one row, moved on by every write that can change the
armory, makers, countries, designations or classifier words a process holds
compiled in memory, so the other processes know to recompile. See
app/services/refgen.py. Idempotent like every migration here.

Revision ID: 0088
Revises: 0087
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import drop_table_if_present, table_exists

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("reference_generation"):
        op.create_table(
            "reference_generation",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("changed_at", sa.DateTime(), nullable=True),
        )
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM reference_generation")).scalar() == 0:
        bind.execute(sa.text("INSERT INTO reference_generation (id, generation) VALUES (1, 0)"))


def downgrade() -> None:
    drop_table_if_present("reference_generation")
