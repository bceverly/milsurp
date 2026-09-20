"""Hot deals: what is cheap for what it is, and who wants to hear about it.

Four tables, and each one is a different kind of thing.

``hot_deal_settings`` is one row of policy, like ``backup_settings``: how often
to look, and what counts. ``hot_deals`` is a *cache* -- rebuilt from scratch by
every pass, worth nothing if lost, and present only because the computation
behind it is a minute of work that every page load would otherwise repeat.
``hot_deal_preferences`` is per reader, and its absence is meaningful: no row
means subscribed to all three categories, which is how every existing account
gets the feature without this migration having to write one row per user.
``hot_deal_notices`` is the memory that makes each email different from the
last -- one row per (reader, listing) carrying *the price they were told*.

Idempotent, like every migration here: each table is created only if it is not
already there, so a database built by ``create_all()`` and then stamped is not
a failure case.

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("hot_deal_notices", "hot_deal_preferences", "hot_deals", "hot_deal_settings")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("hot_deal_settings"):
        op.create_table(
            "hot_deal_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("min_cheaper_than", sa.Integer(), nullable=False, server_default="80"),
            sa.Column("min_discount_percent", sa.Integer(), nullable=False, server_default="20"),
            sa.Column("max_discount_percent", sa.Integer(), nullable=False, server_default="65"),
            sa.Column("min_vendors", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_status", sa.String(length=16), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("last_deal_count", sa.Integer(), nullable=True),
            sa.Column("last_considered", sa.Integer(), nullable=True),
            sa.Column("last_seconds", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        # Seeded here rather than left to the service's get-or-create, so a
        # fresh install has the row the admin page reads before anything has
        # run. The service still creates one, for a database built some other
        # way -- the same belt and braces backup_settings has.
        op.execute(
            sa.text(
                "INSERT INTO hot_deal_settings "
                "(id, enabled, interval_hours, min_cheaper_than, min_discount_percent, "
                " max_discount_percent, min_vendors) "
                "VALUES (1, :on, 8, 80, 20, 65, 2)"
            ).bindparams(on=True)
        )

    if not inspector.has_table("hot_deals"):
        op.create_table(
            "hot_deals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "item_id",
                sa.Integer(),
                sa.ForeignKey("items.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
                index=True,
            ),
            sa.Column("bucket", sa.String(length=20), nullable=False, index=True),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("median_price", sa.Float(), nullable=False),
            sa.Column("discount_percent", sa.Float(), nullable=False, index=True),
            sa.Column("cheaper_than", sa.Integer(), nullable=False),
            sa.Column("peer_count", sa.Integer(), nullable=False),
            sa.Column("vendor_count", sa.Integer(), nullable=False),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("first_listed_at", sa.DateTime(), nullable=False),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
        )

    if not inspector.has_table("hot_deal_preferences"):
        op.create_table(
            "hot_deal_preferences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
                index=True,
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("include_rifles", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("include_handguns", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "include_police_surplus", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("last_sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_hot_deal_preferences_enabled", "hot_deal_preferences", ["enabled"])

    if not inspector.has_table("hot_deal_notices"):
        op.create_table(
            "hot_deal_notices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "item_id",
                sa.Integer(),
                sa.ForeignKey("items.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "item_id", name="uq_hot_deal_notice"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Children first: hot_deal_notices and hot_deal_preferences both point at
    # users, and hot_deals at items, so the order here is about this set rather
    # than about the rest of the schema -- but dropping them in reverse of the
    # creation order is the habit worth keeping.
    for table in _TABLES:
        if inspector.has_table(table):
            op.drop_table(table)
