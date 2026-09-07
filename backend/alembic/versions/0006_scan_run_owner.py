"""Record which process is running a scan.

A scan claimed its site in a process-local dictionary, so the CLI and the web
application could not see each other's runs. Both would scan the same vendor at
once — at twice the request rate its robots.txt asks for, which the vendor
answered with 429s — and each process's stale-run reaper would mark the other's
live scan as failed, because a RUNNING row it did not own looked orphaned.

The database is the only thing the two processes share, so the claim belongs
here. Existing rows get NULL, which reads as "owner unknown" and is reaped on
the timeout as before.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.migration_utils import add_column_if_missing, drop_column_if_present

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    add_column_if_missing("scan_runs", sa.Column("owner_host", sa.String(128), nullable=True))
    add_column_if_missing("scan_runs", sa.Column("owner_pid", sa.Integer(), nullable=True))


def downgrade() -> None:
    drop_column_if_present("scan_runs", "owner_host")
    drop_column_if_present("scan_runs", "owner_pid")
