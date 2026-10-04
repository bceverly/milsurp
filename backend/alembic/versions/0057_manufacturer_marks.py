"""Marks: the codes that name a maker only on its own models.

``manufacturers.marks``, one per line: ``byf`` for Mauser Oberndorf on a K98k,
``SA`` for Springfield Armory on a Garand. Matched only inside the listings of
a model the maker is linked to, never on their own. See
``app.services.arsenals``.

Idempotent like every migration here.

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("manufacturers", sa.Column("marks", sa.Text(), nullable=True))


def downgrade() -> None:
    drop_column_if_present("manufacturers", "marks")
