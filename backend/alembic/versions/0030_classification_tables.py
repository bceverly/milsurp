"""Caliber designations and classifier keywords, editable from the admin pages.

The last of the classification lists that lived in code. ``DESIGNATION_CALIBERS``
turned a dealer's shorthand into a cartridge -- K31, vz.24, Type 99, Mauser
ES340 -- and ``ACCESSORY_KEYWORDS`` with the two lists that veto it,
``PROMOTIONAL_PHRASES`` and ``FIREARM_WORDS``, decided whether a listing was a
part or a gun. All of them are facts about rifles, not about software, and all
of them followed the maker list and the country list out of the source for the
same reason: the person who knows a Mauser ES340 is a .22 trainer should not
need a deploy to say so.

Read ``app/services/designations.py`` and ``app/services/accessories.py`` for
why the rules are process-wide registries rather than per-request reads. The
short version is that ``classify`` is called by scrapers, and a scraper has no
database session and should not be given one.

**Forty-eight regular expressions became fifty-two rows of literal text.**
Thirty-seven of the patterns are a finite language -- alternation, an optional
hyphen, ``\\s*`` -- and were enumerated mechanically: ``gew\\.?\\s*(?:71|88|91|98)``
is eighteen spellings and every one of them is written out. The other eleven
are "these two things co-occur" rules with an unbounded gap, and those became
the ``requires`` column: ``mauser.*8mm`` is the spelling "mauser" requiring
"8mm".

**The port is not quite invisible, and here is exactly where it is not.**
Measured against all 11,038 listings, end to end through ``extract_caliber``:
**23 change, every one of them from wrong or absent to right.** Two causes,
both deliberate:

* ``requires`` is unordered where three of the original patterns were
  one-directional. ``swiss.*rifle`` wanted "Swiss" before "rifle", which no
  W+F Bern listing writes -- "W + F Bern K31" says Swiss nowhere near the word
  and "WF BERN 1911 INFANTRY RIFLE" says it after. Eleven Swiss rifles and one
  Chatellerault Gras that stated their identity plainly were getting no caliber
  at all. The seven rules the author wrote *both* ways round say plainly that
  unordered is what was meant; the three written one way round are where the
  hand slipped.

* The ``.22 Long Rifle`` rule now accepts the spelling without the leading stop
  and is tried before the Swiss rule. Twelve more, and six of those were
  positively wrong rather than merely blank: a Mauser ES340, a Mauser Model
  410, a Mauser 107 and a Mauser 625B training rifle are .22 rimfire sporters
  that the ``mauser`` + ``8mm`` rule was filing as 8mm Mauser, and a Tikka M91
  trainer was filed as 7.62x54R. "Geco 1925", whose description reads
  "CHAMBERED IN 22 LONG RIFLE CALIBER" without a stop, had gone uncalibered.

Nothing loses a caliber it had. The comparison is in the commit for this
change and re-runnable: classify every listing twice, once through the
constants and once through the table.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: (caliber, spellings, requires, whole_word), in the order the rules are
#: tried. Order is load-bearing: the first match wins, and several of these
#: match most of a description.
DESIGNATIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("5.56x45mm NATO", "ar-15\nar15", "", False),
    ("5.45x39mm", "ak 74\nak-74\nak74", "", False),
    ("7.62x39mm", "ak", "", True),
    ("7.62x54R", "psl", "", True),
    ("7.62x51mm NATO", "m1919", "", False),
    (".30 Carbine", "m1 carbine", "", False),
    (".30-06", "m1 garand", "", False),
    (
        ".30-06",
        "u.s. model of 1917\nu.s model of 1917\nus. model of 1917\nus model of 1917",
        "",
        False,
    ),
    ("8mm Mauser", "kar.98\nkar98\nk.98\nk98", "", False),
    ("8mm Mauser", "m48 mauser", "", False),
    (
        "8mm Mauser",
        "gew. 71\ngew. 88\ngew. 91\ngew. 98\ngew 71\ngew 88\ngew 91\ngew 98\ngew.71\ngew.88\ngew.91\ngew.98\nkar 88\ngew71\ngew88\ngew91\ngew98\nkar88",
        "",
        False,
    ),
    ("8mm Mauser", "gewehr 71\ngewehr 88\ngewehr 98", "", False),
    ("8mm Mauser", "mg 34\nmg34", "", False),
    ("8mm Mauser", "zb 26\nzb 37\nzb26\nzb37", "", False),
    (
        ".303 British",
        "lee - enfield\nlee  enfield\nlee -enfield\nlee- enfield\nlee - speed\nlee enfield\nlee-enfield\nlee  speed\nlee -speed\nlee- speed\nleeenfield\nlee speed\nlee-speed\nleespeed",
        "",
        False,
    ),
    ("8mm Lebel", "berthier", "", True),
    (
        "8mm Lebel",
        "st. etienne 1907\nst. etienne 1915\nst etienne 1907\nst etienne 1915\nst. etienne1907\nst. etienne1915\nst.etienne 1907\nst.etienne 1915\nst etienne1907\nst etienne1915\nst.etienne1907\nst.etienne1915\nstetienne 1907\nstetienne 1915\nstetienne1907\nstetienne1915",
        "",
        False,
    ),
    ("8mm Lebel", "lebel", "", True),
    ("9mm Luger", "p. 38\np 38\np.38\np38", "", True),
    ("9x18 Makarov", "makarov", "", True),
    (".32 ACP", "skorpion", "", True),
    ("9mm", "vigneron", "", True),
    (".32 ACP", "walther pp", "", False),
    (".32 ACP", "cz 50\ncz 70\nvz 50\nvz 70\ncz50\ncz70\nvz50\nvz70", "", False),
    (".32 ACP", "beretta m1935", "", False),
    (".380 ACP", "beretta m1934", "", False),
    ("7.5x54mm French", "mas 49\naa 52\nmas49\naa52", "", False),
    ("8x50mmR", "mannlicher", "", True),
    (".30-06", "force publique", "mauser", False),
    ("11.15x58mmR Kropatschek", "kropatschek", "", True),
    ("11mm Gras", "fusil gras\nst etienne\nst. etienne\nstetienne\nst.etienne", "", False),
    ("11mm Gras", "1874", "gras", False),
    ("10.4x47mmR", "vetterli", "", True),
    ("7.62x39mm", "sks", "", True),
    ("7.5x55 Swiss", "g1911", "", True),
    (".22 LR", ".22 long rifle\n22 long rifle", "", False),
    ("7.5x55 Swiss", "swiss", "rifle", False),
    ("7.7x58mm Arisaka", "arisaka\ntype 99\ntype99", "", True),
    ("6.5x50mm Arisaka", "type 38\ntype38", "", True),
    ("7.62x54R", "mosin", "", True),
    ("7.62x25mm Tokarev", "tokarev\ntt-33\ntt33", "", True),
    ("7.5x55 Swiss", "schmidt-rubin\nschmidtrubin", "", False),
    ("7.65 Luger", "7.65", "luger", False),
    ("8x56mmR", "mannlicher", "8x56\n8 x 56\n8×56\n8 × 56", False),
    ("34mm Flare", "m17-38\n34mm\n34 mm", "flare", False),
    ("26.5mm Flare", "26.5mm\n26.5 mm", "flare", False),
    ("6.5x52mm Carcano", "vetterli", "6.5", False),
    ("7.5x55 Swiss", "swiss", "7.5x55\n7.5 x 55\n7.5×55\n7.5 × 55", False),
    ("8mm Mauser", "mauser", "8mm", False),
    ("8mm Mauser", "mauser rifle", "", False),
    (".22 LR", ".22", "trainer", False),
    ("8mm Nambu", "nambu", "", True),
)

#: (kind, word, match). Three lists in one table, because they are consulted
#: together and in a fixed order -- two vetoes and then the words themselves.
#:
#: * ``accessory`` says the listing is a part. Matched as whole words, which is
#:   the fix for the worst bug this list ever had: these were substring tests,
#:   and "spring" is inside "Springfield", so a Springfield Model 1903 was an
#:   accessory and never got a caliber -- 23 of the 28 in the database.
#:   ``suffix`` is the single deliberate exception, for "scope": an optic is
#:   named by what it is on the end of, and a telescope, a periscope and a
#:   riflescope are all the same kind of thing.
#: * ``promotional`` is a gun sold *with* something. "Mosin-Nagant w/ free
#:   bayonet" is a rifle, and the bayonet is the promotion.
#: * ``firearm`` is a word that says the listing names a gun whatever else it
#:   mentions.
#:
#: The two veto lists stay substring matches, faithfully. "gun" reaching
#: "shotgun" and "handgun" is the point of writing it that way, and narrowing
#: them to whole words is a change somebody should make on purpose and measure,
#: not one this migration makes by tidying.
KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("accessory", "belt", "word"),
    ("accessory", "loading tool", "word"),
    ("accessory", "magazine catch", "word"),
    ("accessory", "spring", "word"),
    ("accessory", "stripper clip", "word"),
    ("accessory", "scope", "suffix"),
    ("accessory", "insert", "word"),
    ("accessory", "gas block", "word"),
    ("accessory", "handguard", "word"),
    ("accessory", "rail", "word"),
    ("accessory", "bipod", "word"),
    ("accessory", "ammo pouch", "word"),
    ("accessory", "canvas", "word"),
    ("accessory", "cover", "word"),
    ("accessory", "helmet", "word"),
    ("accessory", "stahlhelm", "word"),
    ("accessory", "binoculars", "word"),
    ("accessory", "en bloc clip", "word"),
    ("accessory", "enbloc clip", "word"),
    ("accessory", "bayonet", "word"),
    ("accessory", "certificate of authenticity", "word"),
    ("promotional", "with free", "substring"),
    ("promotional", "w/ free", "substring"),
    ("promotional", "w/free", "substring"),
    ("promotional", "with 1 free", "substring"),
    ("promotional", "w/1 free", "substring"),
    ("promotional", "with original holster", "substring"),
    ("promotional", "with holster", "substring"),
    ("promotional", "with sling", "substring"),
    ("firearm", "rifle", "substring"),
    ("firearm", "pistol", "substring"),
    ("firearm", "carbine", "substring"),
    ("firearm", "revolver", "substring"),
    ("firearm", "handgun", "substring"),
    ("firearm", "firearm", "substring"),
    ("firearm", "gun", "substring"),
    ("firearm", "mauser", "substring"),
    ("firearm", "mosin", "substring"),
    ("firearm", "carcano", "substring"),
    ("firearm", "enfield", "substring"),
    ("firearm", "garand", "substring"),
    ("firearm", "luger", "substring"),
    ("firearm", "beretta", "substring"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("caliber_designations"):
        designations = op.create_table(
            "caliber_designations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("caliber", sa.String(length=64), nullable=False, index=True),
            #: Literal text, one spelling per line, never patterns: they come
            #: from a form.
            sa.Column("spellings", sa.Text(), nullable=False),
            #: Also required, anywhere in the listing. Empty for most rules.
            sa.Column("requires", sa.Text(), nullable=True),
            sa.Column("whole_word", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("position", sa.Integer(), nullable=False, index=True, server_default="1000"),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, index=True, server_default=sa.true()
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.bulk_insert(
            designations,
            [
                {
                    "caliber": caliber,
                    "spellings": spellings,
                    "requires": requires or None,
                    "whole_word": whole_word,
                    "position": (index + 1) * 10,
                    "enabled": True,
                }
                for index, (caliber, spellings, requires, whole_word) in enumerate(DESIGNATIONS)
            ],
        )

    if not inspector.has_table("classifier_keywords"):
        keywords = op.create_table(
            "classifier_keywords",
            sa.Column("id", sa.Integer(), primary_key=True),
            #: accessory | promotional | firearm.
            sa.Column("kind", sa.String(length=16), nullable=False, index=True),
            sa.Column("keyword", sa.String(length=64), nullable=False),
            #: word | suffix | substring.
            sa.Column("match", sa.String(length=16), nullable=False, server_default="word"),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, index=True, server_default=sa.true()
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        # Unique per kind rather than outright: "rifle" is a firearm word and
        # could one day also be something else, and nothing is gained by
        # making the three lists fight over a namespace they do not share.
        op.create_index(
            "ix_classifier_keywords_kind_keyword",
            "classifier_keywords",
            ["kind", "keyword"],
            unique=True,
        )
        op.bulk_insert(
            keywords,
            [
                {"kind": kind, "keyword": keyword, "match": match, "enabled": True}
                for kind, keyword, match in KEYWORDS
            ],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for name in ("classifier_keywords", "caliber_designations"):
        if inspector.has_table(name):
            op.drop_table(name)
