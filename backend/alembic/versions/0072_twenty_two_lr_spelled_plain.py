""".22 LR written "22 LR", with neither the point nor run together.

Found 2026-10-12: Kittery Trading Post write a used gun's cartridge as
"caliber: 22 LR", which no rule read -- the built-in table wants ".22 LR",
and migration 0068's dealer spellings "22LR". With nothing read, a Taurus PT22,
a Ruger Bearcat, an SP101 and a Beretta B22 had kept a ".25 ACP" an older rule
took from their barrel lengths ("2.25\"", "4.25\""). The spelling joins 0068's
rule for .22 LR; production took it that day.

Idempotent: added only where it is missing. The downgrade takes it out again.

Revision ID: 0072
Revises: 0071
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

SPELLING = "22 lr"
NOTE = "Added 2026-10-11 for listings with no caliber."


def _rows(bind: sa.Connection) -> list[tuple[int, str]]:
    return [
        (row.id, row.spellings)
        for row in bind.execute(
            sa.text(
                "SELECT id, spellings FROM caliber_designations "
                "WHERE caliber = '.22 LR' AND notes = :note"
            ),
            {"note": NOTE},
        )
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for row_id, spellings in _rows(bind):
        lines = [line for line in spellings.splitlines() if line.strip()]
        if SPELLING not in (line.strip().lower() for line in lines):
            bind.execute(
                sa.text("UPDATE caliber_designations SET spellings = :s WHERE id = :id"),
                {"s": "\n".join([*lines, SPELLING]), "id": row_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    for row_id, spellings in _rows(bind):
        kept = [line for line in spellings.splitlines() if line.strip().lower() != SPELLING]
        bind.execute(
            sa.text("UPDATE caliber_designations SET spellings = :s WHERE id = :id"),
            {"s": "\n".join(kept), "id": row_id},
        )
