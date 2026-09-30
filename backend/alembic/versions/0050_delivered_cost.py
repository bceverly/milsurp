"""What a gun costs delivered: shop shipping and the reader's transfer fee.

``sites.shipping_long_gun``, ``shipping_handgun`` and ``shipping_note`` -- an
administrator's override of what each scraper declares from the shop's policy
page -- and ``users.ffl_transfer_fee``. See ``app.services.delivered``.

Idempotent like every migration here.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("sites", sa.Column("shipping_long_gun", sa.Float(), nullable=True))
    add_column_if_missing("sites", sa.Column("shipping_handgun", sa.Float(), nullable=True))
    add_column_if_missing("sites", sa.Column("shipping_note", sa.String(length=200), nullable=True))
    add_column_if_missing("users", sa.Column("ffl_transfer_fee", sa.Float(), nullable=True))


def downgrade() -> None:
    drop_column_if_present("users", "ffl_transfer_fee")
    drop_column_if_present("sites", "shipping_note")
    drop_column_if_present("sites", "shipping_handgun")
    drop_column_if_present("sites", "shipping_long_gun")
