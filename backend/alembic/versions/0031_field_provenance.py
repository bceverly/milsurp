"""Where each derived field's value came from.

Everything beyond a vendor's own words is derived, and the pipeline is built to
be recomputed -- that is what lets one rule fix reach eleven thousand listings.
One thing was always missing, and the gap has a measured cost: **nothing
recorded whether a stored value was the vendor's or the rules'.**

So ``reclassify --recompute`` could not tell a correction from a demolition.
Run over the catalog scoped to nothing but the caliber it changed **3,187 of
11,038 listings** -- 2,251 of them to nothing at all -- because the flag
discards the stored value by design and re-derives from the title. Right for a
caliber the rules guessed; wrong for one the dealer printed. A Carl Gustafs
1896 stated as 6.5x55mm Swedish came back 8mm Mauser; a Carcano carbine whose
own title reads "6.5X52" came back 7.35x51mm.

Four columns, one beside each field ``reclassify`` can rebuild, holding
``vendor``, ``derived`` or ``catalog``. See ``app/services/provenance.py``.

**Deliberately not backfilled.** Every existing row gets NULL, meaning "nobody
knows", and NULL is treated exactly like ``vendor`` -- protected from a
rebuild. A backfill would have to guess which values were the vendor's, and a
guess about provenance is precisely the mistake being corrected; guessing again
in the other direction is the same mistake with better manners.

The consequence is that this earns nothing on the day it ships and fills itself
in as each site's next scan rewrites its rows. That is the honest cost of not
having recorded it from the start, and it is bounded: every site scans daily.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "caliber_source",
    "country_source",
    "condition_source",
    "manufacturer_source",
)


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("items")}
    for name in COLUMNS:
        if name not in existing:
            op.add_column("items", sa.Column(name, sa.String(length=16), nullable=True))


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("items")}
    for name in COLUMNS:
        if name in existing:
            op.drop_column("items", name)
