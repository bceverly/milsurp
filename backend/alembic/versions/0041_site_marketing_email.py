"""When a vendor's marketing email last reached us: ``sites.marketing_email_at``.

The notification account is being subscribed to the mailing lists of the shops
we read, so the inbox reader (ROADMAP, "Vendor mailing lists") can hear about
sales before a scan would. The Sites card shows each shop's signup link green
once mail from that shop has arrived and red until then, which is how an
administrator sees which lists still need joining. This column is that fact.

Nothing writes it until the inbox reader ships, so every shop starts red. That
is accurate: nothing has been received, because nothing is reading yet.

Idempotent like every migration here.

Revision ID: 0041
Revises: 0040
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("sites", sa.Column("marketing_email_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    drop_column_if_present("sites", "marketing_email_at")
