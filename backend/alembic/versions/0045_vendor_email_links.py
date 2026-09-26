"""Follow the links in vendors' emails: ``vendor_email_links``.

Each link in a vendor's marketing email that is not footer is recorded with
where following it led on the shop's site and, when it names a listing we
hold, what re-reading that listing found. ``vendor_emails`` gains when its
links were read and its text (for coupon codes and end dates, later). See
``app/services/maillinks.py`` and ``app/services/inbox.py``.

Idempotent like every migration here.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import (
    add_column_if_missing,
    create_table_if_missing,
    drop_column_if_present,
    drop_table_if_present,
)

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("vendor_emails", sa.Column("links_read_at", sa.DateTime(), nullable=True))
    add_column_if_missing("vendor_emails", sa.Column("body_text", sa.Text(), nullable=True))
    create_table_if_missing(
        "vendor_email_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "email_id",
            sa.Integer(),
            sa.ForeignKey("vendor_emails.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("link", sa.String(length=2048), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("how", sa.String(length=16), nullable=False),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("items.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("outcome", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    drop_table_if_present("vendor_email_links")
    drop_column_if_present("vendor_emails", "body_text")
    drop_column_if_present("vendor_emails", "links_read_at")
