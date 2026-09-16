"""Countries of origin, editable from the admin pages.

The list started as 38 regular expressions in ``app.services.classify``, which
meant recognizing one more spelling -- "Ishapore" for India, a new arsenal
name -- was a code change, a review and a deploy, for a fact about the world
the person running the site knows and the programmer does not. The maker list
moved out of the code for that reason and this follows it.

**It could not follow it exactly.** A maker is matched by
``manufacturers.extract(session, ...)``, which is called from the scan where a
session exists. A country is matched by ``classify.enrich``, which scrapers
call too -- and a scraper has no session and should not have one. So the rules
are held in a process-wide registry that loads itself once and is dropped when
the table changes, rather than being read per call. See
``app/services/countries.py``.

Seeded here from the constants it replaces, so the table starts out saying
exactly what the code said and the change is invisible until somebody edits it.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: (name, aliases, position) seeded from classify.COUNTRY_PATTERNS.
#:
#: The regexes there are word alternations and optional-suffix shapes, both of
#: which expand to plain spellings -- "Austrian?" becomes "Austrian" and
#: "Austria". Two needed enumerating rather than expanding, because they are
#: punctuation-flexible abbreviations rather than words: U.K. and U.S.A.
#:
#: Order is preserved exactly. It decides which rule is tried first and that
#: matters here as much as it does for makers.
#:
#: Some spellings look wrong and are not. "Belgia", "Canadia" and "Peruvia" are
#: what ``\bBelgian?\b`` and its siblings actually match -- the optional "n"
#: means the stem alone is a match -- so they are seeded too. Dropping them
#: would be a behavior change dressed up as tidying, and this migration's whole
#: promise is that the table starts out saying exactly what the code said.
SEED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Finland", ("Finn", "Finnish")),
    ("Germany", ("German", "Germany", "Germanic", "Nazi", "Prussian")),
    ("Russia", ("Russia", "Russian", "Soviet", "USSR", "Tula", "Izhevsk")),
    ("Sweden", ("Swedish", "Sweden")),
    ("Switzerland", ("Swiss", "Switzerland")),
    ("United Kingdom", ("British", "English", "Britain", "UK", "U.K.", "U.K")),
    (
        "United States",
        # Enumerated rather than expanded, because the pattern this replaces is
        # punctuation-flexible rather than a word: \bU\.?\s?S\.?\s?A?\.?\b.
        # The dotless forms matter as much as the dotted ones -- "U.S Revolver
        # Company" has no trailing stop, and the "U.S." inside "U.S.M.C." is
        # followed by a letter, so only "U.S" reaches both.
        (
            "American",
            "United States",
            "US",
            "U.S",
            "US.",
            "U.S.",
            "U S",
            "USA",
            "U.S.A",
            "U.S.A.",
            "U S A",
        ),
    ),
    ("Japan", ("Japanese", "Japan")),
    ("Italy", ("Italian", "Italy")),
    ("France", ("French", "France")),
    ("Czech Republic", ("Czech", "Czechoslovak", "Czechoslovakian")),
    ("Austria", ("Austria", "Austrian", "Austro-Hungarian")),
    ("Belgium", ("Belgia", "Belgian", "Belgium")),
    ("Spain", ("Spanish", "Spain")),
    ("Yugoslavia", ("Yugoslav", "Yugoslavian", "Serbia", "Serbian")),
    ("Poland", ("Polish", "Poland")),
    ("Romania", ("Romania", "Romanian")),
    ("Hungary", ("Hungaria", "Hungarian")),
    ("China", ("Chinese", "China")),
    ("Turkey", ("Turkish", "Turkey", "Ottoman")),
    ("Greece", ("Greek", "Greece")),
    ("Argentina", ("Argentine", "Argentinian")),
    ("Brazil", ("Brazil", "Brazilian")),
    ("Peru", ("Peruvia", "Peruvian")),
    ("Chile", ("Chilea", "Chilean")),
    ("Persia", ("Persia", "Persian", "Irania", "Iranian", "Iran")),
    ("Norway", ("Norwegia", "Norwegian", "Norway")),
    ("Denmark", ("Danish", "Denmark")),
    ("Netherlands", ("Dutch", "Netherlands", "Holland")),
    ("Portugal", ("Portuguese", "Portugal")),
    ("Mexico", ("Mexica", "Mexican", "Mexico")),
    ("South Africa", ("South African",)),
    ("Canada", ("Canadia", "Canadian", "Canada")),
    ("India", ("India", "Indian", "Ishapore")),
    ("Egypt", ("Egyptia", "Egyptian")),
    ("Ethiopia", ("Ethiopia", "Ethiopian")),
    ("Bulgaria", ("Bulgaria", "Bulgarian")),
    ("Israel", ("Israel", "Israeli", "IMI", "IWI")),
)


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("countries"):
        return
    table = op.create_table(
        "countries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True, index=True),
        #: Other spellings, one per line. Matched as literal text on word
        #: boundaries, never as patterns: they come from a form.
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, index=True, server_default="1000"),
        sa.Column("enabled", sa.Boolean(), nullable=False, index=True, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.bulk_insert(
        table,
        [
            {
                "name": name,
                "aliases": "\n".join(aliases),
                "position": (index + 1) * 10,
                "enabled": True,
            }
            for index, (name, aliases) in enumerate(SEED)
        ],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("countries"):
        op.drop_table("countries")
