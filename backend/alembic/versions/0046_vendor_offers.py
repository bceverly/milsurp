"""What vendors' emails offer: ``vendor_offers``, and where a price came from.

Codes and deadlines read from vendor emails ("10% off with code X through
Sunday"), shown beside the shop's listings while they last and never applied
to a price; ``vendor_emails.offers_read_at`` says an email's text has been
read for one. ``price_history.source`` marks a price that arrived by email or
the watchlist poll rather than a scan. See ``app/services/offers.py``.

Idempotent like every migration here.

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import (
    add_column_if_missing,
    create_index_if_missing,
    create_table_if_missing,
    drop_column_if_present,
    drop_table_if_present,
)

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "vendor_emails", sa.Column("offers_read_at", sa.DateTime(), nullable=True)
    )
    add_column_if_missing("price_history", sa.Column("source", sa.String(length=16), nullable=True))
    create_table_if_missing(
        "vendor_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "email_id",
            sa.Integer(),
            sa.ForeignKey("vendor_emails.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("discount", sa.String(length=80), nullable=True),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("terms", sa.String(length=200), nullable=True),
        sa.Column("personal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("shown_until", sa.DateTime(), nullable=False),
        sa.Column("ended_checked_at", sa.DateTime(), nullable=True),
    )
    create_index_if_missing("ix_vendor_offers_shown_until", "vendor_offers", ["shown_until"])


def downgrade() -> None:
    drop_table_if_present("vendor_offers")
    drop_column_if_present("price_history", "source")
    drop_column_if_present("vendor_emails", "offers_read_at")
