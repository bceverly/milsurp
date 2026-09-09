"""Let a user name a set of filters and be mailed its results.

The browse page already carries every filter in its URL -- keyword, site,
category, caliber, country, manufacturer, armory model, type, availability,
price range, "new since", price-drops-only, and one of six sort orders -- so a
saved search is a name and that query string. It is stored as the query string
rather than as a column per filter for one reason: the filter set has grown
four times already, and a column each means a migration each time.

**The query is validated, not trusted.** ``services.search.parse_query`` reads
it into the same filters the browse endpoint uses, and refuses an unknown
parameter or sort. That check runs when the row is *saved*, because the row is
then run unattended every morning and there is nobody there to see a 400.

``email_item_limit`` is a cap on the email and on nothing else. Running a saved
search from its own page returns the whole result set; an email is a fixed
thing that arrives whether or not anybody wants to read four hundred rows.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "saved_searches"):
        return

    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        # The browse page's own query string, canonicalized: sorted, with the
        # paging parameters dropped so two searches that differ only in page
        # size are one search.
        sa.Column("query", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("sort", sa.String(length=32), nullable=False, server_default="newest"),
        sa.Column(
            "email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0"), index=True
        ),
        sa.Column("email_item_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("last_emailed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # One name per user, so "Mosins under $400" means one thing in their
        # list and renaming onto an existing name is refused rather than
        # silently making two.
        sa.UniqueConstraint("user_id", "name", name="uq_saved_search_name"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "saved_searches"):
        op.drop_table("saved_searches")
