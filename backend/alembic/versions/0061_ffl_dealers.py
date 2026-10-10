"""A reader's FFL dealers: ``ffl_dealers``, in place of ``users.ffl_transfer_fee``.

Asked for on 2026-10-09: a list of dealers -- name, address, website and
transfer fee, each entered by hand -- instead of the one fee. Every delivered
price uses the lowest fee among them (``User.ffl_transfer_fee``, now a
property).

A fee already set is not lost: it becomes a dealer named "My FFL dealer",
which the reader can rename and fill in. The downgrade puts each reader's
lowest fee back on the user.

Idempotent like every migration here.

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    add_column_if_missing,
    column_exists,
    create_table_if_missing,
    drop_column_if_present,
    drop_table_if_present,
)

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

CARRIED_OVER_NAME = "My FFL dealer"


def upgrade() -> None:
    create_table_if_missing(
        "ffl_dealers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("transfer_fee", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    if column_exists("users", "ffl_transfer_fee"):
        now = datetime.now(UTC).replace(tzinfo=None)
        op.execute(
            sa.text(
                "INSERT INTO ffl_dealers (user_id, name, transfer_fee, created_at, updated_at) "
                "SELECT id, :name, ffl_transfer_fee, :now, :now FROM users "
                "WHERE ffl_transfer_fee IS NOT NULL"
            ).bindparams(name=CARRIED_OVER_NAME, now=now)
        )
    drop_column_if_present("users", "ffl_transfer_fee")


def downgrade() -> None:
    add_column_if_missing("users", sa.Column("ffl_transfer_fee", sa.Float(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET ffl_transfer_fee = (SELECT MIN(transfer_fee) FROM ffl_dealers "
            "WHERE ffl_dealers.user_id = users.id)"
        )
    )
    drop_table_if_present("ffl_dealers")
