"""What a row held before an administrator changed it, so the change can be undone.

The audit log has recorded *that* something changed since it was written — who,
when, which row, which fields. It has never recorded what those fields held, so
it could say "somebody edited the K31's aliases at 14:02" and could not say what
they were at 14:01. That is enough to answer "who did this" and not enough to
answer "put it back", which is the question somebody actually has on seeing
*412 listing(s) re-matched* under a dialog they have just closed.

One column, holding JSON. Not a table of its own: an undo belongs to the event
that needs undoing, it is read exactly when that event is read, and a second
table would be a join and a second thing to prune on the same schedule.

Deliberately unstructured. The shape of "before" differs per target — a caliber
has aliases and a status, a model has manufacturers and a kind — and a column
per field would be a schema change every time an editable field is added, for a
value nothing ever queries. It is written by the endpoint that knows the shape
and read by the endpoint that reverses it, and nothing in between looks inside.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audit_events")}
    if "before_state" not in existing:
        op.add_column("audit_events", sa.Column("before_state", sa.Text(), nullable=True))


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audit_events")}
    if "before_state" in existing:
        op.drop_column("audit_events", "before_state")
