"""Record when a listing's detail page was fetched; make the digest timezone optional.

Two unrelated single-column changes, together because they landed together.

``items.detail_fetched_at`` replaces an inference. Whether a scraper still owes
a listing its detail page used to be guessed from "does this row have any photo
records yet", which is not the same question: an interrupted Royal Tiger scan
left 210 listings holding photo rows whose files had never been downloaded, the
next scan read that as "complete", skipped every detail page, and the
catalog-grid thumbnail replaced galleries of six and seven photos with one.
Every existing row starts NULL, so the next scan re-fetches and repairs them.

``email_preferences.display_timezone`` becomes nullable so that "never chosen"
is representable. It defaulted to the string 'UTC', which is indistinguishable
from someone deliberately choosing UTC, so the settings page could not know
whether it was allowed to offer the browser's zone instead.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, column_exists, drop_column_if_present

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("detail_fetched_at", sa.DateTime(), nullable=True))

    # SQLite cannot ALTER a column's nullability in place; batch_alter_table
    # rebuilds the table around the change. Guarded so the revision stays
    # re-runnable.
    if column_exists("email_preferences", "display_timezone"):
        from alembic import op

        with op.batch_alter_table("email_preferences") as batch:
            batch.alter_column(
                "display_timezone",
                existing_type=sa.String(64),
                nullable=True,
                existing_nullable=False,
            )


def downgrade() -> None:
    drop_column_if_present("items", "detail_fetched_at")
    if column_exists("email_preferences", "display_timezone"):
        from alembic import op

        # Going back needs a value in every row before the column can be NOT
        # NULL again.
        op.execute(
            "UPDATE email_preferences SET display_timezone = 'UTC' "
            "WHERE display_timezone IS NULL"
        )
        with op.batch_alter_table("email_preferences") as batch:
            batch.alter_column(
                "display_timezone",
                existing_type=sa.String(64),
                nullable=False,
                existing_nullable=True,
            )
