#!/usr/bin/env python3
"""Copy a Milsurp Monitor SQLite database into PostgreSQL.

**This is the data half of the move; Alembic is the schema half.** A migration
can only ever change the database it is connected to, so nothing in
``backend/alembic/versions/`` can carry rows from one server to another. The
move is two steps and they are meant to be run in this order:

    1. Point ``database:`` in config.yaml at PostgreSQL, then run
       ``scripts/dbupdate.py``. That runs the same migration chain that built
       the SQLite database, against the new one, and leaves an empty schema at
       the same revision.

    2. Run this, which reads every row out of the SQLite file and writes it in.

Both databases are read through SQLAlchemy using the *same* table definitions,
which is what makes the conversions right: SQLite has no boolean and no
datetime, and reading its 0/1 and its "2026-09-09 04:15:00.123456" back through
the column types turns them into ``True`` and a ``datetime`` before PostgreSQL
ever sees them. A row-by-row ``INSERT ... VALUES`` built from ``sqlite3`` output
would hand PostgreSQL the integer 0 for a boolean column and stop there.

Three things it insists on, because each one has a silent-corruption version:

* **Both databases are at the same Alembic revision.** Copying into a schema
  that is a migration ahead means a column that quietly stays NULL.
* **The target is empty**, unless ``--force`` is given, which empties it first.
  Copying into a database that already has rows is either a duplicate-key error
  or, worse, a partial merge.
* **Every table's row count is compared afterwards.** A copy that dropped rows
  and said nothing is the failure mode that matters.

Primary keys are carried over as they are -- an item's id is in URLs, in saved
searches and in emails that have already gone out -- so the last step is to
wind each table's sequence past the highest id it now holds. Without that the
next insert would collide with row 1.

Usage::

    scripts/sqlite-to-postgres.py                    # from the configured path
    scripts/sqlite-to-postgres.py --from milsurp.db
    scripts/sqlite-to-postgres.py --dry-run          # report, change nothing
    scripts/sqlite-to-postgres.py --force            # empty the target first
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# scripts/sqlite-to-postgres.py -> repo root -> backend
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import sqlalchemy as sa  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402

from app import models  # noqa: F401,E402  (importing registers every table)
from app.config import get_config  # noqa: E402
from app.database import Base  # noqa: E402

#: Rows per INSERT. Large enough that the round trips do not dominate, small
#: enough to stay well under PostgreSQL's 65535 bound-parameter ceiling for the
#: widest table here (items, ~40 columns: 500 x 40 = 20,000).
BATCH = 500


def revision_of(engine: sa.Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def self_references(table: sa.Table) -> list[str]:
    """Columns on this table whose foreign key points back at this table.

    Three of them do: calibers, firearm_models and manufacturers each carry a
    ``merged_into_id``, which is how a duplicate row is folded into the row it
    was a duplicate of. They are the one thing that makes the copy order
    matter *inside* a table -- ``sorted_tables`` gets the order right between
    tables, but nothing orders a row against another row of its own table, and
    PostgreSQL checks a foreign key the instant the row lands.

    So those columns are left NULL on the way in and filled by an UPDATE once
    every row of the table exists. SQLite never noticed because it does not
    enforce foreign keys unless asked to.
    """
    return [c.name for c in table.columns for fk in c.foreign_keys if fk.column.table is table]


def copy_table(source: sa.Engine, target: sa.Engine, table: sa.Table, *, quiet: bool) -> int:
    columns = list(table.columns)
    deferred = self_references(table)
    key = list(table.primary_key.columns)
    if deferred and len(key) != 1:
        raise RuntimeError(f"{table.name} references itself but has no single-column primary key")

    copied = 0
    fixups: list[dict[str, object]] = []
    with source.connect() as reader, target.begin() as writer:
        result = reader.execution_options(stream_results=True, yield_per=BATCH).execute(
            sa.select(*columns)
        )
        insert = table.insert()
        for chunk in result.partitions(BATCH):
            rows = [dict(row._mapping) for row in chunk]  # noqa: SLF001
            for row in rows:
                pointing = {name: row[name] for name in deferred if row[name] is not None}
                if pointing:
                    fixups.append({"_pk": row[key[0].name], **pointing})
                    for name in pointing:
                        row[name] = None
            if rows:
                writer.execute(insert, rows)
                copied += len(rows)

        if fixups:
            update = (
                table.update()
                .where(key[0] == sa.bindparam("_pk"))
                .values({name: sa.bindparam(name) for name in deferred})
            )
            # Every fixup row needs every bound parameter present, or
            # executemany sees two different statements.
            for row in fixups:
                for name in deferred:
                    row.setdefault(name, None)
            writer.execute(update, fixups)

    if not quiet:
        note = f"  (+{len(fixups):,} self-reference(s) filled in)" if fixups else ""
        print(f"  {table.name:<32} {copied:>8,}{note}")
    return copied


def reset_sequences(target: sa.Engine) -> list[str]:
    """Wind every serial sequence past the largest id that was just copied."""
    wound = []
    with target.begin() as connection:
        for table in Base.metadata.sorted_tables:
            for column in table.primary_key.columns:
                if not isinstance(column.type, sa.Integer):
                    continue
                sequence = connection.execute(
                    sa.text("SELECT pg_get_serial_sequence(:t, :c)"),
                    {"t": table.name, "c": column.name},
                ).scalar_one_or_none()
                if not sequence:
                    continue
                # Two statements, neither of them built by string formatting.
                # The obvious one-liner interpolates the table and column into
                # a MAX() subquery, which is a SQL injection finding to anyone
                # reading it -- and suppressing that finding is worse than not
                # having it. The highest id is a perfectly ordinary Core query,
                # and the sequence name binds as a parameter once it is cast to
                # regclass, which is the only reason it looked unavoidable.
                highest = connection.execute(
                    sa.select(sa.func.coalesce(sa.func.max(column), 0)).select_from(table)
                ).scalar_one()
                # is_called=false, so the next id handed out is exactly this
                # one -- and the floor of max+1 means an empty table starts at
                # 1 rather than 2.
                connection.execute(
                    sa.text("SELECT setval(CAST(:sequence AS regclass), :next, false)"),
                    {"sequence": sequence, "next": highest + 1},
                )
                wound.append(sequence)
    return wound


def row_counts(engine: sa.Engine, tables: list[sa.Table]) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table.name: connection.execute(
                sa.select(sa.func.count()).select_from(table)
            ).scalar_one()
            for table in tables
        }


def report_plan(tables: list[sa.Table], counts: dict[str, int], total: int) -> None:
    print(f"\nWould copy {total:,} row(s):")
    for table in tables:
        if counts[table.name]:
            print(f"  {table.name:<32} {counts[table.name]:>8,}")


def empty_target(target: sa.Engine, tables: list[sa.Table]) -> None:
    """Delete every row, in reverse dependency order so a child goes before
    its parent."""
    with target.begin() as connection:
        for table in reversed(tables):
            connection.execute(table.delete())


def _cannot_start(config, source_path: Path) -> str | None:
    """Why this cannot run at all, or None."""
    if not config.database.is_postgres:
        return (
            "error: config.yaml does not name a PostgreSQL database, so there is "
            "nothing to copy into.\n"
            "       Edit the database: block first -- see README.md, "
            "'Running on PostgreSQL'."
        )
    if not source_path.is_file():
        return f"error: {source_path} does not exist."
    return None


def _refuse(source: sa.Engine, target: sa.Engine, tables: list[sa.Table], *, force: bool):
    """The three refusals, each of which has a silent-corruption version.

    Returns the complaint, or None to go ahead.
    """
    here, there = revision_of(source), revision_of(target)
    if there is None:
        return "error: the PostgreSQL database has no schema yet. Run scripts/dbupdate.py first."
    if here != there:
        return (
            f"error: the two databases are at different schema revisions "
            f"({here or 'none'} here, {there} there). Bring the SQLite file up "
            f"to date first, then re-run scripts/dbupdate.py against PostgreSQL."
        )

    inspector = sa.inspect(source)
    missing = [table.name for table in tables if not inspector.has_table(table.name)]
    if missing:
        return f"error: the SQLite file has no {', '.join(missing)}."

    occupied = {name: n for name, n in row_counts(target, tables).items() if n}
    if occupied and not force:
        listed = ", ".join(f"{name} ({n:,})" for name, n in occupied.items())
        return (
            f"error: the target is not empty: {listed}.\n"
            f"       Re-run with --force to empty those tables first."
        )
    return None


def arguments(argv: list[str] | None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", help="Path to a config.yaml (overrides the search path).")
    parser.add_argument(
        "--from",
        dest="source",
        help="The SQLite file to read (default: database.path from config.yaml).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete everything in the target tables first. Destructive.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report and change nothing.")
    parser.add_argument("--quiet", action="store_true", help="Only report problems.")
    return parser.parse_args(argv)


def report_mismatches(expected: dict[str, int], landed: dict[str, int]) -> bool:
    """Say which tables lost rows. True when every count matches.

    A copy that dropped rows and said nothing is the failure mode that matters.
    """
    wrong = {
        name: (expected[name], landed[name]) for name in expected if expected[name] != landed[name]
    }
    for name, (wanted, got) in wrong.items():
        print(f"error: {name}: expected {wanted:,} row(s), found {got:,}", file=sys.stderr)
    return not wrong


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)

    if args.config:
        os.environ["MILSURP_CONFIG"] = args.config
    config = get_config(reload=bool(args.config))

    source_path = Path(args.source) if args.source else config.database.path
    complaint = _cannot_start(config, source_path)
    if complaint:
        print(complaint, file=sys.stderr)
        return 1

    source = sa.create_engine(f"sqlite:///{source_path}")
    target = sa.create_engine(config.database_url)

    if not args.quiet:
        print(f"From: {source_path}")
        print(f"To:   {config.database.describe()}")

    tables = list(Base.metadata.sorted_tables)
    complaint = _refuse(source, target, tables, force=args.force)
    if complaint:
        print(complaint, file=sys.stderr)
        return 1
    already = row_counts(target, tables)
    counts = row_counts(source, tables)
    total = sum(counts.values())

    if args.dry_run:
        report_plan(tables, counts, total)
        return 0

    if args.force and any(already.values()):
        empty_target(target, tables)
        if not args.quiet:
            print("Emptied the target tables.")

    if not args.quiet:
        print(f"\nCopying {total:,} row(s):")
    for table in tables:
        copy_table(source, target, table, quiet=args.quiet or not counts[table.name])

    # --- Verify -------------------------------------------------------------
    if not report_mismatches(counts, row_counts(target, tables)):
        return 1

    wound = reset_sequences(target)
    if not args.quiet:
        print(f"\nCopied {total:,} row(s); every table's count matches.")
        print(f"Wound {len(wound)} sequence(s) past the ids that were carried over.")
        print("\nStart the application and check the browse page before deleting anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
