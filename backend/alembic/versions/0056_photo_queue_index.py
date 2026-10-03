"""An index on the photos still waiting to be downloaded.

``ix_item_photos_pending``: ``item_photos(item_id) WHERE filename IS NULL``.
A partial index, so it holds only the waiting rows -- 226 of 109,777 on
production on 2026-10-03 -- and the download queue and the backlog counts,
which ask for exactly those, stop reading the whole table to find them.
Production had scanned ``item_photos`` sequentially 71,871 times by then.

Both engines take a partial index. Idempotent like every migration here.

Revision ID: 0056
Revises: 0055
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import drop_index_if_present, index_exists, table_exists

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

NAME = "ix_item_photos_pending"


def upgrade() -> None:
    if table_exists("item_photos") and not index_exists("item_photos", NAME):
        op.create_index(
            NAME,
            "item_photos",
            ["item_id"],
            postgresql_where=sa.text("filename IS NULL"),
            sqlite_where=sa.text("filename IS NULL"),
        )


def downgrade() -> None:
    drop_index_if_present(NAME, "item_photos")
