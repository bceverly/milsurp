"""Initial schema: users, sites, scan runs, items, prices, photos, digests.

Revision ID: 0001
Revises:
Created: 2026-09-05

Written to be idempotent -- every object is created only if it is missing, so
this runs cleanly against a fresh database and against one the application
already created with create_all().
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import (
    create_index_if_missing,
    create_table_if_missing,
    drop_table_if_present,
)

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enums are stored as VARCHAR with a CHECK constraint (native_enum=False in the
# models), which keeps SQLite migrations simple and the values readable.
USER_ROLE = sa.String(16)
SCAN_STATUS = sa.String(16)
EMAIL_STATUS = sa.String(16)


def upgrade() -> None:
    create_table_if_missing(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(128), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False, server_default="normal"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    create_index_if_missing("ix_users_username", "users", ["username"])
    create_index_if_missing("ix_users_email", "users", ["email"])

    create_table_if_missing(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scan_interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("requires_browser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_scan_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("next_scan_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_sites_slug"),
    )
    create_index_if_missing("ix_sites_slug", "sites", ["slug"])
    create_index_if_missing("ix_sites_enabled", "sites", ["enabled"])
    create_index_if_missing("ix_sites_next_scan_at", "sites", ["next_scan_at"])

    create_table_if_missing(
        "scan_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("status", SCAN_STATUS, nullable=False, server_default="running"),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("items_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_delisted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_changes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_drops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("images_downloaded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("log", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name="fk_scan_runs_site", ondelete="CASCADE"
        ),
    )
    create_index_if_missing("ix_scan_runs_site_id", "scan_runs", ["site_id"])
    create_index_if_missing("ix_scan_runs_status", "scan_runs", ["status"])
    create_index_if_missing("ix_scan_runs_started_at", "scan_runs", ["started_at"])
    create_index_if_missing("ix_scan_runs_site_started", "scan_runs", ["site_id", "started_at"])

    create_table_if_missing(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("caliber", sa.String(64), nullable=True),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("manufacturer", sa.String(128), nullable=True),
        sa.Column("condition", sa.String(64), nullable=True),
        sa.Column("is_rifle", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_pistol", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_sold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("delisted_at", sa.DateTime(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("previous_price", sa.Float(), nullable=True),
        sa.Column("lowest_price", sa.Float(), nullable=True),
        sa.Column("highest_price", sa.Float(), nullable=True),
        sa.Column("price_changed_at", sa.DateTime(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name="fk_items_site", ondelete="CASCADE"
        ),
        # The scraper's per-site key is what makes re-scrapes update in place
        # instead of duplicating rows.
        sa.UniqueConstraint("site_id", "external_key", name="uq_item_site_key"),
    )
    create_index_if_missing("ix_items_site_id", "items", ["site_id"])
    create_index_if_missing("ix_items_category", "items", ["category"])
    create_index_if_missing("ix_items_caliber", "items", ["caliber"])
    create_index_if_missing("ix_items_country", "items", ["country"])
    create_index_if_missing("ix_items_manufacturer", "items", ["manufacturer"])
    create_index_if_missing("ix_items_is_sold", "items", ["is_sold"])
    create_index_if_missing("ix_items_is_active", "items", ["is_active"])
    create_index_if_missing("ix_items_current_price", "items", ["current_price"])
    create_index_if_missing("ix_items_price_changed_at", "items", ["price_changed_at"])
    create_index_if_missing("ix_items_site_active", "items", ["site_id", "is_active"])
    create_index_if_missing("ix_items_first_seen", "items", ["first_seen_at"])

    create_table_if_missing(
        "item_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_type", sa.String(64), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name="fk_photos_item", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("item_id", "source_url", name="uq_photo_item_source"),
    )
    create_index_if_missing("ix_item_photos_item_id", "item_photos", ["item_id"])

    create_table_if_missing(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("scan_run_id", sa.Integer(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name="fk_price_item", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scan_run_id"], ["scan_runs.id"], name="fk_price_run", ondelete="SET NULL"
        ),
    )
    create_index_if_missing("ix_price_history_item_id", "price_history", ["item_id"])
    create_index_if_missing("ix_price_history_scan_run_id", "price_history", ["scan_run_id"])
    create_index_if_missing("ix_price_history_observed_at", "price_history", ["observed_at"])
    create_index_if_missing("ix_price_item_observed", "price_history", ["item_id", "observed_at"])

    create_table_if_missing(
        "email_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("frequency_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("include_new_items", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("new_items_per_site_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("include_price_drops", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("price_drops_per_site_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("minimum_price_drop", sa.Float(), nullable=False, server_default="0"),
        sa.Column("skip_when_empty", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.Column("next_send_at", sa.DateTime(), nullable=True),
        sa.Column("last_digest_cutoff", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_prefs_user", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", name="uq_prefs_user"),
    )
    create_index_if_missing("ix_email_preferences_user_id", "email_preferences", ["user_id"])
    create_index_if_missing("ix_email_preferences_enabled", "email_preferences", ["enabled"])
    create_index_if_missing(
        "ix_email_preferences_next_send_at", "email_preferences", ["next_send_at"]
    )

    create_table_if_missing(
        "email_preference_sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("preference_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["preference_id"],
            ["email_preferences.id"],
            name="fk_pref_sites_pref",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name="fk_pref_sites_site", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("preference_id", "site_id", name="uq_pref_site"),
    )
    create_index_if_missing(
        "ix_email_preference_sites_preference_id", "email_preference_sites", ["preference_id"]
    )
    create_index_if_missing(
        "ix_email_preference_sites_site_id", "email_preference_sites", ["site_id"]
    )

    create_table_if_missing(
        "email_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", EMAIL_STATUS, nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("new_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_drop_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_email_logs_user", ondelete="CASCADE"
        ),
    )
    create_index_if_missing("ix_email_logs_user_id", "email_logs", ["user_id"])
    create_index_if_missing("ix_email_logs_status", "email_logs", ["status"])
    create_index_if_missing("ix_email_logs_sent_at", "email_logs", ["sent_at"])


def downgrade() -> None:
    # Reverse dependency order so foreign keys never block a drop.
    for table in (
        "email_logs",
        "email_preference_sites",
        "email_preferences",
        "price_history",
        "item_photos",
        "items",
        "scan_runs",
        "sites",
        "users",
    ):
        drop_table_if_present(table)
