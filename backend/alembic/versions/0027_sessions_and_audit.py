"""Server-side sessions, and a log of what administrators did.

**Sessions exist now because a JWT cannot be taken back.** The token was
stateless on purpose and that bought a great deal -- no lookup, no shared
state, nothing to keep in step. What it could not do was answer "where am I
signed in?" or "end that one". The only revocation available was
``token_version``, which ends *every* session at once and is what a password
change uses; there was no way to close the laptop you left at work without
signing yourself out of your phone as well.

So a login writes a row, the token carries its id, and the row can be marked
revoked. The cost is a lookup per request -- alongside the one that already
loads the user, so it is one query against a primary key on a table with a row
per active sign-in.

**The audit log is a separate idea with the same shape.** Failed sign-ins were
already logged to the journal; what happened *after* somebody got in was not.
Creating an account, changing a role, disabling a site -- each is a decision
somebody made, and a log file that scrolls and rotates is not where you go to
find out who made it. These rows are append-only and outlive the account that
caused them, which is the point: the row that matters most is usually the one
made by an account somebody has since deleted.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            # What the person sees in the list. Truncated and scrubbed before
            # it gets here; it is somebody else's string either way.
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
            # Touched as the session is used, so the list can say which one is
            # this browser and which has been idle for a week.
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            # SET NULL, not CASCADE: deleting an account must not erase the
            # record of what it did. "Who disabled this site?" is a question
            # most worth asking about somebody who is no longer here.
            sa.Column(
                "actor_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            # Kept as text beside the id for the same reason.
            sa.Column("actor_name", sa.String(length=150), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False, index=True),
            sa.Column("target_type", sa.String(length=32), nullable=True),
            sa.Column("target_id", sa.String(length=64), nullable=True),
            sa.Column("target_label", sa.String(length=255), nullable=True),
            sa.Column("detail", sa.String(length=500), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("audit_events"):
        op.drop_table("audit_events")
    if inspector.has_table("user_sessions"):
        op.drop_table("user_sessions")
