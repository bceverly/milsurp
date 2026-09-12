"""Keep the message that was sent, not just the fact that it was.

The digest page could say a message went out at a time, to a person, with a
subject and two counts — and could not show what it said. That makes a delivery
question ("did the price drop I expected actually go out?") unanswerable after
the fact, because the only copy of the message was in somebody's inbox.

Both parts are stored. The HTML is what was actually delivered; the plain-text
alternative is what the mailer generates alongside it, and it is the one worth
reading in a table or searching.

Existing rows get NULL, which the page renders as "not recorded" rather than as
an empty message.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("email_logs", sa.Column("body_html", sa.Text(), nullable=True))
    add_column_if_missing("email_logs", sa.Column("body_text", sa.Text(), nullable=True))


def downgrade() -> None:
    drop_column_if_present("email_logs", "body_html")
    drop_column_if_present("email_logs", "body_text")
