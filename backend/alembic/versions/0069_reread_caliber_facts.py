"""Read every caliber's article again, and price every caliber afresh without AmmoSeek.

The first refresh in production (2026-10-11) read some infoboxes wrongly --
a unit written with the number was ignored for the page's own flag, so .22 LR
came out 0.0088" across and .303 British a 2,315 gr bullet. That is fixed in
app.services.ammunition; this makes the fix reach the rows already written:
the facts are read again on the next hourly pass.

And AmmoSeek is gone (2026-10-12): its terms forbid automated collection and
its bot control refused the scanner, so factory ammunition now comes from
Ammo.com and projectiles from Graf & Sons. The figures AmmoSeek gave are
cleared rather than left to look current, its per-caliber query column is
dropped, and a refresh is asked for so the new sources fill them in on the
scheduler's next pass rather than a week later.

Data only apart from the dropped column, and safe to run twice. The
downgrade puts the column back empty; the cleared figures are not restored.

Revision ID: 0069
Revises: 0068
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE calibers SET wikipedia_read_at = NULL")
    op.execute(
        "UPDATE caliber_bullet_weights SET factory_cpr = NULL WHERE caliber_id IN "
        "(SELECT id FROM calibers WHERE factory_source = 'ammoseek')"
    )
    op.execute(
        "UPDATE calibers SET factory_cpr = NULL, factory_source = NULL, factory_url = NULL "
        "WHERE factory_source = 'ammoseek'"
    )
    op.execute(
        "UPDATE caliber_bullet_weights SET projectile_cost = NULL WHERE caliber_id IN "
        "(SELECT id FROM calibers WHERE projectile_url LIKE '%ammoseek%')"
    )
    op.execute(
        "UPDATE calibers SET projectile_cost = NULL, projectile_url = NULL "
        "WHERE projectile_url LIKE '%ammoseek%'"
    )
    drop_column_if_present("calibers", "ammoseek_query")
    # Only where a refresh has run: one that never has is due already.
    op.get_bind().execute(
        sa.text("UPDATE ammo_settings SET requested_at = :now WHERE last_run_at IS NOT NULL"),
        {"now": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")},
    )


def downgrade() -> None:
    add_column_if_missing("calibers", sa.Column("ammoseek_query", sa.String(300), nullable=True))
