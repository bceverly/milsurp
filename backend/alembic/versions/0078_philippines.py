"""The Philippines, as a country the classifier reads and the armory names.

Added on 2026-10-15 with the Armscor reader: Rock Island Armory's guns are
made in the Philippines, and the shipped armory says so. A country the
classifier cannot produce splits one filter in two (see
tests/test_armory.py, TestTheShippedFileNamesItsCountries), so the row the
classifier reads at runtime is added here, as 0029 added the rest.

Revision ID: 0078
Revises: 0077
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    have = bind.execute(sa.text("SELECT 1 FROM countries WHERE name = 'Philippines'")).first()
    if have:
        return
    position = bind.execute(
        sa.text("SELECT COALESCE(MAX(position), 0) + 10 FROM countries")
    ).scalar()
    bind.execute(
        sa.text(
            "INSERT INTO countries (name, aliases, position, enabled) "
            "VALUES ('Philippines', :aliases, :position, :enabled)"
        ),
        {"aliases": "Philippines\nPhilippine\nFilipino", "position": position, "enabled": True},
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM countries WHERE name = 'Philippines'"))
