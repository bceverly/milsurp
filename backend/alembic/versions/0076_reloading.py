"""What it costs to reload one round: bullet, new brass, powder and primer.

Asked for on 2026-10-14. On each caliber, the primer it takes (from its
Wikipedia article, or set by hand) and the load entered by hand (a powder, a
charge, the bullet weight it is for), with what the brass, primer and powder
for one round cost today; and a table of Graf & Sons' powders and primers,
priced per pound and per primer, so a load typed by hand is priced at once
and the powder dropdown has something to offer. See app.services.reloading.

Every caliber with an article has it read again on the next Wikipedia part
of the caliber data: the primer is in the infobox, and the articles were all
read before this asked for it.

Revision ID: 0076
Revises: 0075
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    add_column_if_missing,
    create_table_if_missing,
    drop_column_if_present,
    drop_table_if_present,
)

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_COLUMNS = (
    ("primer_size", sa.String(16)),
    ("primer_magnum", sa.Boolean()),
    ("primer_source", sa.String(16)),
    ("powder_name", sa.String(128)),
    ("powder_charge_gr", sa.Float()),
    ("powder_bullet_gr", sa.Float()),
    ("brass_cost", sa.Float()),
    ("brass_url", sa.String(500)),
    ("brass_checked_at", sa.DateTime()),
    ("primer_cost", sa.Float()),
    ("primer_url", sa.String(500)),
    ("powder_cost", sa.Float()),
    ("powder_url", sa.String(500)),
)


def upgrade() -> None:
    for name, kind in _COLUMNS:
        add_column_if_missing("calibers", sa.Column(name, kind, nullable=True))
    create_table_if_missing(
        "reloading_supplies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("kind", "name", name="uq_reloading_supplies_kind_name"),
    )
    op.execute(
        sa.text("UPDATE calibers SET wikipedia_read_at = NULL WHERE wikipedia_url IS NOT NULL")
    )


def downgrade() -> None:
    drop_table_if_present("reloading_supplies")
    for name, _kind in reversed(_COLUMNS):
        drop_column_if_present("calibers", name)
