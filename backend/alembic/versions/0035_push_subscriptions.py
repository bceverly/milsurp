"""Browsers that have agreed to be notified.

A push subscription is not an account setting. It belongs to one browser on one
device: the same person reading this on a phone and a desktop has two, and a
browser that has been reinstalled has a new one rather than an edited old one.

**The endpoint is the whole capability.** Anyone holding it can send that
browser a notification -- there is no second credential to check -- so it is
unique here, it is never rendered on a page, and this table is treated with the
care the sessions table gets.

``p256dh`` and ``auth`` are the browser's half of the encryption: a public key
it generated and a shared secret. No private key belonging to a subscription
exists on this side and none could, which is what makes a stolen copy of this
table unable to read anything already sent.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("push_subscriptions"):
        return
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("endpoint", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("push_subscriptions"):
        op.drop_table("push_subscriptions")
