"""Hot deals narrowed to a reader's saved searches.

One column on ``hot_deal_preferences``: whether this reader wants only the
deals that match at least one of their saved searches. The category switches
beside it could only say "rifles", and somebody who collects Swiss rifles was
mailed every bargain in the catalog.

**Off by default, and false for every existing row.** A reader who has changed
nothing keeps getting what they got yesterday. The matching itself is not
stored anywhere: it is worked out when the email is built, from the saved
searches as they are then, by the same code the browse page runs.

Idempotent like every migration here.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "hot_deal_preferences",
        sa.Column(
            "match_saved_searches",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    drop_column_if_present("hot_deal_preferences", "match_saved_searches")
