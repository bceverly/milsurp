"""One-time password reset links, sent by an administrator.

The roadmap parked *self-service* reset deliberately: it needs an
unauthenticated endpoint that issues a token to anybody who names an address,
and with a handful of users an admin reset was the smaller attack surface. This
keeps the issuing side authenticated -- an admin presses the button -- and
leaves only redeeming open, which needs a token nobody can guess.

It is also not new power. An admin can already set another account's password
through ``PATCH /api/users/{id}``. What changes is that the admin never learns
the new password and the person choosing it is the person who will use it.

The token is hashed with the same Argon2 the passwords use: while it is live it
*is* the password. Single use, short lived, and superseded by the next one
issued for the same account.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("password_reset_tokens"):
        return
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "issued_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("password_reset_tokens"):
        op.drop_table("password_reset_tokens")
