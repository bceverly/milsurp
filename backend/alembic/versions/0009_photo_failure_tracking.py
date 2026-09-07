"""Remember that a photo failed, and why.

A queued photo is a row with no ``filename``, and the downloader selects those
and tries them. Nothing recorded a failure, so a URL that can never succeed —
a 404, a removed image, a host that refuses — was retried on every scan and
every ``make photos``, forever, silently.

Worse than the wasted requests: the queue is read with a per-scan budget and
had no ordering, so a few hundred permanently dead rows could sit at the front
and starve photos that would have worked. Checkpoint Charlie's rate-limited
their uploads directory and twenty-odd photographs failed in a burst; nothing
in the run said so, and "stored 1 photo" out of twenty-three read as success.

``attempts`` counts tries, ``last_attempt_at`` and ``last_error`` say when and
why. Existing rows start at zero attempts, which is true of them as far as
anything knows.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "item_photos",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    add_column_if_missing("item_photos", sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
    add_column_if_missing("item_photos", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in ("attempts", "last_attempt_at", "last_error"):
        drop_column_if_present("item_photos", column)
