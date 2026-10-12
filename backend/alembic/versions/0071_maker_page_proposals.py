"""Suggestions of a model's own page on its maker's site, beside the Wikipedia ones.

Asked for on 2026-10-12: find each model's product page, keep it in the
armory, and show it in "What the armory knows" -- in place of a search of
the maker's site. The proposals share ``reference_proposals`` with the
Wikipedia articles, and the Armory's review of them; ``field`` says which
column accepting one writes: "wikipedia" (every row before this) or
"maker_page" (``firearm_models.maker_url``). See app.services.makerpages.

Revision ID: 0071
Revises: 0070
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "reference_proposals",
        sa.Column("field", sa.String(16), nullable=False, server_default="wikipedia"),
    )


def downgrade() -> None:
    drop_column_if_present("reference_proposals", "field")
