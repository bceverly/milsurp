"""Rename the reset-link audit action away from the word "password".

The constant was `USER_PASSWORD_RESET = "user.password_reset_sent"`, and three
static analyzers in turn read a name containing PASSWORD as a hardcoded
credential: ruff's S105 and bandit's B105, both suppressed inline for months,
and then CodeQL, which reported *clear-text logging of sensitive information*
against the `log.exception` that names the action when an audit write fails.

No password is within reach of any of them. The value is the name of something
that happened — a one-time link was mailed — and the thing being logged is that
name. Renaming it is what the two suppressions were standing in for, and with
the name changed both linters fall silent without them.

This rewrites the rows already written, so the action has one spelling in the
database rather than two. It is a label on a historical event and nothing keys
on it but the audit page's own filter, which is rebuilt from whatever the
column holds. The page keeps a mapping for the old string anyway, for a
database restored from a snapshot taken before this ran.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "user.password_reset_sent"
NEW = "user.reset_link_sent"


def _rename(was: str, now: str) -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("audit_events"):
        return
    bind.execute(
        sa.text("UPDATE audit_events SET action = :now WHERE action = :was"),
        {"now": now, "was": was},
    )


def upgrade() -> None:
    _rename(OLD, NEW)


def downgrade() -> None:
    _rename(NEW, OLD)
