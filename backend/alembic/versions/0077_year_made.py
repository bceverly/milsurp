"""When a gun was made: the year its listing states, or one its serial places.

Asked for on 2026-10-15. On each listing, the serial it labels as one and the
years it was made, stated or placed by its serial among the listings of the
same model and maker that state theirs; and a read of everything stored. See
app.services.serials.

Revision ID: 0077
Revises: 0076
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.migration_utils import (
    add_column_if_missing,
    column_exists,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
)

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

_COLUMNS = (
    ("serial", sa.String(32)),
    ("serial_low", sa.Integer()),
    ("serial_high", sa.Integer()),
    ("made_from", sa.Integer()),
    ("made_to", sa.Integer()),
    ("made_source", sa.String(16)),
    ("made_quote", sa.String(200)),
)


def upgrade() -> None:
    for name, kind in _COLUMNS:
        add_column_if_missing("items", sa.Column(name, kind, nullable=True))
    create_index_if_missing("ix_items_made_from", "items", ["made_from"])

    # Imported here rather than at module scope, as in 0075.
    from app.services import serials

    session = Session(bind=op.get_bind())
    # Without the published tables: their table is made by 0081, which has
    # not run yet. Site settings' re-read dates by them once it has.
    counts = serials.backfill(session, tables=False)
    session.flush()
    log.info(
        "Years made: %s gun(s) read, %s with a serial, %s stating a year, %s placed by serial.",
        counts["examined"],
        counts["serial"],
        counts["stated"],
        counts["placed"],
    )


def downgrade() -> None:
    if column_exists("items", "made_from"):
        drop_index_if_present("ix_items_made_from", "items")
    for name, _kind in reversed(_COLUMNS):
        drop_column_if_present("items", name)
