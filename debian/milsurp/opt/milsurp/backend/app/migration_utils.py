"""Helpers that make Alembic migrations idempotent.

The application calls ``create_all()`` on startup so a fresh checkout works
without running the migration chain first. That means a migration can legitimately
find its table already present. Rather than failing, every migration in this
project asks the database what exists before changing it, so ``make migrate`` is
safe to run repeatedly and safe to run against a database created either way.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def table_exists(name: str) -> bool:
    return name in _inspector().get_table_names()


def column_exists(table: str, column: str) -> bool:
    if not table_exists(table):
        return False
    return any(col["name"] == column for col in _inspector().get_columns(table))


def index_exists(table: str, name: str) -> bool:
    if not table_exists(table):
        return False
    return any(idx["name"] == name for idx in _inspector().get_indexes(table))


def create_table_if_missing(name: str, *columns: Any, **kwargs: Any) -> None:
    if not table_exists(name):
        op.create_table(name, *columns, **kwargs)


def drop_table_if_present(name: str) -> None:
    if table_exists(name):
        op.drop_table(name)


def create_index_if_missing(
    name: str, table: str, columns: list[str], unique: bool = False
) -> None:
    if table_exists(table) and not index_exists(table, name):
        op.create_index(name, table, columns, unique=unique)


def drop_index_if_present(name: str, table: str) -> None:
    if index_exists(table, name):
        op.drop_index(name, table_name=table)


def add_column_if_missing(table: str, column: sa.Column) -> None:
    if table_exists(table) and not column_exists(table, column.name):
        # Batch mode: SQLite cannot ALTER TABLE ADD CONSTRAINT, so Alembic
        # rebuilds the table around the change.
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def drop_column_if_present(table: str, column: str) -> None:
    if column_exists(table, column):
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)
