"""Add thumbnail and dimension columns to item_photos.

Revision ID: 0002
Revises: 0001
Created: 2026-09-05

Photos are now kept at two resolutions -- the original download and a
locally-generated thumbnail -- so the grid view can stay light on mobile while
the detail view still shows full-size images.

Existing rows keep a NULL thumb_filename; the API falls back to the full image
for those, and the next scan fills them in.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Names only. The Column objects themselves are built fresh on each use:
#: a Column instance is bound to the table it is added to, so reusing one
#: across calls needs the deprecated Column.copy().
NEW_COLUMN_NAMES = ("thumb_filename", "thumb_bytes", "width", "height")


def _new_columns() -> list[sa.Column]:
    return [
        sa.Column("thumb_filename", sa.String(512), nullable=True),
        sa.Column("thumb_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    for column in _new_columns():
        # Each column is added only if missing, so this revision is safe to
        # re-run and safe against a database built by an older create_all().
        add_column_if_missing("item_photos", column)


def downgrade() -> None:
    for name in NEW_COLUMN_NAMES:
        drop_column_if_present("item_photos", name)
