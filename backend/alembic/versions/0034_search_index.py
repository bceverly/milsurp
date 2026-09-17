"""A substring index for the search box, on both engines.

The browse search is "every term must appear somewhere in the listing", matched
as a *substring* across six columns: title, description, caliber, manufacturer,
country and category. Six ``ILIKE '%term%'`` predicates OR-ed together, per
term, and no index can serve a leading wildcard — so every search is a
sequential scan of the whole catalog. Measured at 11,038 listings: **43-190ms
per query**, growing linearly, which the roadmap was right to call fine now and
not fine at hundreds of thousands.

**A word index was tried first and rejected**, which is worth recording because
it is the obvious answer. PostgreSQL's ``tsvector`` tokenizes, and this catalog
is full of text that tokenizes badly: ``M1911A1`` is one token, so searching
"1911" lost 86 listings; ``K98k`` is one token, so "k98" lost 59; "8mm" lost
108. Worse, ``S&W`` reduces to the single token ``w``, so searching for it
returned 1,736 listings instead of 211. Token search cannot do infix matching,
and infix matching is what this search box has always promised.

So: **trigram indexes, which accelerate the existing semantics rather than
changing them.** PostgreSQL has ``pg_trgm`` with a GIN index that serves
``ILIKE '%x%'`` directly; SQLite has FTS5's ``trigram`` tokenizer, which does
the same for substrings. Both are the native idiom for their engine and both
answer exactly what the six ILIKEs answered.

**One document column, not six indexes.** The six fields are concatenated into
a generated column and indexed once. Joined by a **newline**, which is the part
that keeps this equivalent rather than merely similar: a space would let the
phrase "german bayonet" match a listing whose title ends "German" and whose
category begins "Bayonet", and neither field contains the phrase. A newline
cannot be typed into the search box, so no query can span a boundary.

Verified against the whole catalog before any of this was written: 31 realistic
queries, **0 differences** between the six-column OR and the single-document
ILIKE, with speedups from 1.2x to 80x.

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

#: The fields the search box has always looked in, in the order they are
#: concatenated. Changing this list means rebuilding the column, which the
#: generated column does for itself on PostgreSQL and the trigger does on
#: SQLite.
FIELDS = ("title", "description", "caliber", "manufacturer", "country", "category")

#: The FTS5 table is external-content: it indexes `items` rather than storing a
#: second copy of every description. Named as a literal in the DDL below rather
#: than interpolated: a fixed identifier spelled through an f-string reads as
#: query building to a linter, and it is not.
FTS_TABLE = "items_fts"


def _expression(newline: str) -> str:
    return ("||" + newline + "||").join(f"coalesce({field},'')" for field in FIELDS)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    columns = {column["name"] for column in sa.inspect(bind).get_columns("items")}

    if "search_document" not in columns:
        newline = "chr(10)" if dialect == "postgresql" else "char(10)"
        op.execute(
            f"ALTER TABLE items ADD COLUMN search_document TEXT "
            f"GENERATED ALWAYS AS ({_expression(newline)}) STORED"
        )

    if dialect == "postgresql":
        # The extension is the one part that can be refused: creating one needs
        # a privilege the application's role may not have been granted. That is
        # not a reason to fail the upgrade -- without the index the search is
        # exactly as fast as it was yesterday, which is to say it works -- so
        # it is attempted, reported and moved past.
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        except Exception:
            log.warning(
                "Could not create the pg_trgm extension, so the search index was "
                "not built. Searching still works and is unchanged in speed. Ask "
                "a superuser for: CREATE EXTENSION pg_trgm;",
            )
            return
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_items_search_trgm "
            "ON items USING gin (search_document gin_trgm_ops)"
        )
    else:
        op.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5("
            "search_document, content='items', content_rowid='id', tokenize='trigram')"
        )
        # External content keeps no copy, so the index has to be told about
        # every write. Three triggers, and the delete half of an update matters
        # as much as the insert half: without it a re-scraped listing is
        # findable under the text it used to have.
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN "
            "INSERT INTO items_fts(rowid, search_document) "
            "VALUES (new.id, new.search_document); END"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN "
            "INSERT INTO items_fts(items_fts, rowid, search_document) "
            "VALUES ('delete', old.id, old.search_document); END"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE ON items BEGIN "
            "INSERT INTO items_fts(items_fts, rowid, search_document) "
            "VALUES ('delete', old.id, old.search_document); "
            "INSERT INTO items_fts(rowid, search_document) "
            "VALUES (new.id, new.search_document); END"
        )
        op.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_items_search_trgm")
    else:
        for suffix in ("ai", "ad", "au"):
            op.execute(f"DROP TRIGGER IF EXISTS items_fts_{suffix}")
        op.execute("DROP TABLE IF EXISTS items_fts")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("items")}
    if "search_document" in columns:
        op.drop_column("items", "search_document")
