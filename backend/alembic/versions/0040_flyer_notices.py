"""Mail a new flyer once: the ``flyer_notices`` table, and a daily look.

Hunter's Lodge publish their stock as one scanned advertisement at a time. A
scan that reads one nobody has been told about now mails it, and this table is
what makes that happen once per flyer rather than once per scan.

**And the site is looked at daily rather than weekly.** Its scraper's default
changed, but a default only applies to a site row being created; the row every
existing install already has still says a week, which would make "the day the
ad goes up" mean "up to a week later". So it is moved here -- but only if it
still holds the old default. An administrator who chose a cadence on purpose
keeps it.

Idempotent like every migration here.

Revision ID: 0040
Revises: 0039
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

WEEKLY = 60 * 24 * 7
DAILY = 60 * 24


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("flyer_notices"):
        op.create_table(
            "flyer_notices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "site_id",
                sa.Integer(),
                sa.ForeignKey("sites.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("signature", sa.String(length=255), nullable=False),
            sa.Column("listings", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("partial", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sent_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("site_id", "signature", name="uq_flyer_notice"),
        )

    sites = sa.table(
        "sites",
        sa.column("slug", sa.String),
        sa.column("scan_interval_minutes", sa.Integer),
    )
    bind.execute(
        sites.update()
        .where(sites.c.slug == "hunters-lodge", sites.c.scan_interval_minutes == WEEKLY)
        .values(scan_interval_minutes=DAILY)
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("flyer_notices"):
        op.drop_table("flyer_notices")
