"""Mark a mailing-list subscription confirmed: ``sites.newsletter_confirmed_at``.

A double opt-in list asks for confirmation, and the Sites card shows it amber
until real mail follows. Mailchimp sends a "you're confirmed" message only if
the list owner turned it on, so a confirmed list can stay silent -- and amber
-- until its next newsletter. This records an administrator saying it is
confirmed. See ``app/services/inbox.py``.

Idempotent like every migration here.

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing(
        "sites", sa.Column("newsletter_confirmed_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    drop_column_if_present("sites", "newsletter_confirmed_at")
