"""Two-factor authentication, and the codes that stop it being a lockout.

The admin sign-in is reachable from the internet through haproxy, and a
password is the only thing in front of it. TOTP is the ordinary answer: six
digits from a shared secret and the clock, which every authenticator app on a
phone implements and which app/totp.py implements here in the standard library.

Three columns and a table.

``totp_secret`` holds the shared secret **encrypted**, with a key derived from
``security.password_pepper`` -- the secret that already lives in the config
file rather than the database so that a stolen dump is not enough to attack
passwords offline. Storing the TOTP secret in the clear beside the password
hashes would hand an attacker both factors at once and make the second one
decorative.

``totp_enabled`` is separate from having a secret, because enrollment has a
middle state: a secret is issued and displayed, and only a code typed back from
the phone turns the flag on. Without that gap, an enrollment abandoned halfway
-- a mistyped secret, a closed tab -- locks the account out.

``recovery_codes`` is the way back in when the phone is gone. Ten single-use
codes, hashed with the same Argon2 the passwords use because one of them alone
is the whole second factor. Used ones are kept, so "three left" is answerable.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "users")
    if existing:
        if "totp_secret" not in existing:
            op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
        if "totp_enabled" not in existing:
            op.add_column(
                "users",
                sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
        if "totp_confirmed_at" not in existing:
            op.add_column("users", sa.Column("totp_confirmed_at", sa.DateTime(), nullable=True))

    if not sa.inspect(bind).has_table("recovery_codes"):
        op.create_table(
            "recovery_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("code_hash", sa.String(length=255), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("recovery_codes"):
        op.drop_table("recovery_codes")
    existing = _columns(bind, "users")
    with op.batch_alter_table("users") as batch:
        for column in ("totp_secret", "totp_enabled", "totp_confirmed_at"):
            if column in existing:
                batch.drop_column(column)
