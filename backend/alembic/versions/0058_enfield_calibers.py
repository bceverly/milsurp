"""M1917s filed as .303 British, put right.

The M1917 and the P14 are one rifle in two cartridges, and the word "Enfield"
alone used to decide: "CMP M1917 Enfield Service Grade" was stored as a .303
British, four listings on production on 2026-10-04. The classifier reads them
correctly now (``classify.enfield_pattern``), but a scan only fills an empty
caliber, so the ones already stored are corrected here -- only where the
caliber was a guess and the title states none. See ``app.services.enfields``.

Data only, and re-runnable: a second run finds nothing left to change.

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Imported here rather than at module scope, as in 0037: a migration that
    # fails to import takes the whole upgrade path down with it.
    from app.services import enfields

    enfields.recalibrate(op.get_bind())


def downgrade() -> None:
    """Nothing to undo: the stored caliber was wrong."""
