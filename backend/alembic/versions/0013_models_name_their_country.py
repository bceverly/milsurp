"""Give an armory model its country of origin.

The listing table has had a ``country`` column since the beginning, filled by
reading the title: "RUSSIAN M44 CARBINES" says Russia and "SWEDISH MAUSER
M96" says Sweden. What it cannot do is answer a title that names no country at
all, and a great many do -- "M1 GARANDS, EXC" and "K98k, matching, RC" among
them. Those listings simply had no country, and the browse page's country
filter had no opinion about them.

The armory already answers that shape of question for the caliber and the
maker: the model is named, and the model knows. This is the same fact one
column over.

**Origin of the pattern, not provenance of the gun.** A Mosin-Nagant is
Russian however many of them Finland captured and rebuilt, and a K98k
assembled in Brno after the war is a German pattern made in Czechoslovakia.
Which is why the fill is one-directional: a listing that states a country keeps
what it states, and this only ever answers a blank.

Nullable, with no backfill. Every existing row is a question for whoever
curates the armory, and the seed file carries the answers.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "firearm_models")
    if not existing or "country" in existing:
        return

    op.add_column("firearm_models", sa.Column("country", sa.String(length=64), nullable=True))
    op.create_index("ix_firearm_models_country", "firearm_models", ["country"])


def downgrade() -> None:
    bind = op.get_bind()
    if "country" not in _columns(bind, "firearm_models"):
        return
    with op.batch_alter_table("firearm_models") as batch:
        batch.drop_index("ix_firearm_models_country")
        batch.drop_column("country")
