"""Read the vendors' mailing lists: ``inbox_settings`` and ``vendor_emails``.

The notification account is subscribed to the marketing email of the shops we
read. ``inbox_settings`` says whether and how often its inbox is checked (off
until an administrator turns it on); ``vendor_emails`` records each message
from a shop once, by its Message-ID, and only messages from shops -- nothing
else in that mailbox is stored. See ``app/services/inbox.py``.

Idempotent like every migration here.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import create_table_if_missing, drop_table_if_present, table_exists

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("inbox_settings"):
        op.create_table(
            "inbox_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_status", sa.String(length=16), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("last_looked_at", sa.Integer(), nullable=True),
            sa.Column("last_recorded", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        # Seeded so the page has a row to read before anything has run; the
        # service still creates one for a database built some other way.
        op.execute(
            sa.text(
                "INSERT INTO inbox_settings (id, enabled, interval_hours) VALUES (1, :off, 2)"
            ).bindparams(off=False)
        )

    create_table_if_missing(
        "vendor_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(length=512), nullable=False, unique=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("asks_to_confirm", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("received_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    drop_table_if_present("vendor_emails")
    drop_table_if_present("inbox_settings")
