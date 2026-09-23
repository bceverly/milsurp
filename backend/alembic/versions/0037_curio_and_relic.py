"""Curio and relic eligibility, as evidence rather than as a verdict.

Three columns on ``items`` and a backfill over everything already stored.

**Why the columns hold evidence.** The ATF's first limb is a *rolling* fifty
years, so "eligible" is a statement about today and not about the gun: made in
1977 is not eligible now and is in 2027. A column holding the answer would be
wrong within the year with nothing having changed. ``cr_stated`` and
``manufacture_year`` hold what the vendor actually said; the verdict is derived
from them at read time, in one place, by ``app.services.curio``.

**Why the backfill is here rather than in a command somebody has to remember.**
A fix to how a listing is *read* never reaches the listings already read --
that is the same lesson the detail-refetch work learned -- and this is a
derivation over text that is already in the database, so there is nothing to
re-scrape and no vendor to trouble. ``debian/milsurp.postinst`` applies
outstanding migrations before it will start the service, so the data is there
the first time anybody opens the page. It is re-runnable afterwards through
``cli.py curio-backfill``, which is the path for when the rules are tightened.

Idempotent, like every migration here: the columns and the index are created
only if absent, and the backfill only fills rows that carry no reading yet, so
a database built by ``create_all()`` and stamped is not a failure case.

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migration_utils import (
    add_column_if_missing,
    column_exists,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
)

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    add_column_if_missing("items", sa.Column("cr_stated", sa.Boolean(), nullable=True))
    add_column_if_missing("items", sa.Column("manufacture_year", sa.Integer(), nullable=True))
    add_column_if_missing("items", sa.Column("cr_evidence", sa.String(length=16), nullable=True))
    create_index_if_missing("ix_items_manufacture_year", "items", ["manufacture_year"])

    # Imported here rather than at module scope: a migration that fails to
    # import takes the whole upgrade path down with it, including the ones that
    # do not need this.
    from app.services import curio

    counts = curio.backfill(op.get_bind(), only_missing=True)
    log.info(
        "C&R backfill: examined %s listing(s) — %s eligible, %s not eligible, %s unknown.",
        counts.get("examined", 0),
        counts.get(curio.ELIGIBLE, 0),
        counts.get(curio.NOT_ELIGIBLE, 0),
        counts.get(curio.UNKNOWN, 0),
    )


def downgrade() -> None:
    if column_exists("items", "manufacture_year"):
        drop_index_if_present("ix_items_manufacture_year", "items")
    drop_column_if_present("items", "cr_evidence")
    drop_column_if_present("items", "manufacture_year")
    drop_column_if_present("items", "cr_stated")
