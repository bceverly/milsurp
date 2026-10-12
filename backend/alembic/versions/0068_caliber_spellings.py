"""Spellings dealers write a caliber in that no rule read.

Added 2026-10-11, after production's listings with no caliber were read
through: "22LR", "38SPL", "22 S, L, & LR", "308 Win", "6.5 Creedmor",
"45/70", "7,65mm" and the rest stated a cartridge in their titles or
descriptions that the built-in table, written for dotted spellings, did not
know. Rows in caliber_designations, editable on the Classification page,
after every rule already there (position 600 on), so none of them can
outrank a rule somebody chose. Production took the same rows that day.

Idempotent: a rule already present with the same caliber and spellings is
left alone, and the downgrade removes only these.

Revision ID: 0068
Revises: 0067
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

NOTE = "Added 2026-10-11 for listings with no caliber."

#: (caliber, spellings, whole word), in order; positions 600, 610, ...
RULES: tuple[tuple[str, list[str], bool], ...] = (
    (
        ".22 LR",
        [
            "22lr",
            "22 l.r.",
            "22 s, l, lr",
            "22 s,l,lr",
            "22 s, l, & lr",
            "22 s, l & lr",
            "22 s l & lr",
            "22. s. l. & l.r.",
            "22 s, l, & l.r.",
            "22 s,l & lr",
        ],
        True,
    ),
    (".22 WMR", ["22mrf", "22 mrf", "22wmr"], True),
    (".38 Special", ["38spl", "38 spl", "38spcl"], True),
    (".32 H&R Magnum", ["32mag", "32 h&r mag"], True),
    (".357 Magnum", ["357h", "357mag"], True),
    (".44 Magnum", ["44remma", "44 rem mag", "44mag"], True),
    (".45 ACP", ["45acp"], False),
    (".460 S&W Magnum", ["460s&w", "460 xvr", "460xvr", "460pc"], True),
    (".500 S&W Magnum", ["500 s&w", "500s&w"], True),
    ("7.62x51 NATO", ["308 win", "308win", ".308win", "308 police"], True),
    (".243 Winchester", ["243 win", "243win", ".243win"], True),
    ("6.5mm Creedmoor", ["6.5 creedmoor", "6.5 creedmor", "6.5creedmoor"], True),
    (".338 Winchester Magnum", ["338wm", ".338wm", "338 win mag"], True),
    (".300 AAC Blackout", ["300 blackout", ".300 blackout", "300blk", "300 blk"], True),
    (".22-250 Remington", ["22-250", "22/250"], True),
    ("25-06 Remington", ["25-06", "25/06"], True),
    (".220 Swift", ["220 swift"], True),
    ("5.56x45mm NATO", ["5.56 nato", "5.56nato"], True),
    (".458 SOCOM", ["458 socom"], True),
    (".45-70 Government", ["45/70", "45-70"], True),
    (".375 H&H Magnum", ["375 h&h", ".375 h&h"], True),
    (".32 ACP", ["32acp", "7,65mm", "7,65 mm"], True),
    (".38 ACP", ["38rs", ".38rs"], True),
)

TABLE = sa.table(
    "caliber_designations",
    sa.column("caliber", sa.String),
    sa.column("spellings", sa.Text),
    sa.column("whole_word", sa.Boolean),
    sa.column("position", sa.Integer),
    sa.column("enabled", sa.Boolean),
    sa.column("notes", sa.Text),
)


def upgrade() -> None:
    bind = op.get_bind()
    have = set(bind.execute(sa.text("SELECT caliber, spellings FROM caliber_designations")).all())
    rows = []
    for at, (caliber, spellings, whole_word) in enumerate(RULES):
        text = "\n".join(spellings)
        if (caliber, text) in have:
            continue
        rows.append(
            {
                "caliber": caliber,
                "spellings": text,
                "whole_word": whole_word,
                "position": 600 + 10 * at,
                "enabled": True,
                "notes": NOTE,
            }
        )
    if rows:
        op.bulk_insert(TABLE, rows)


def downgrade() -> None:
    op.execute(TABLE.delete().where(TABLE.c.notes == NOTE))
