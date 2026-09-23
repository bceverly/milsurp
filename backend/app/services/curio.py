"""Curio and relic eligibility, read from what a vendor actually wrote.

**Why this is stored as evidence and not as a verdict.** The ATF's first limb
is a *rolling* fifty years, so "eligible" is a statement about today and not
about the gun: something made in 1977 is not eligible now and is in 2027. A
boolean written during a scan would be wrong within the year and nothing would
have changed to make it so. What is stored is therefore the manufacture year
and whether the vendor said anything, and the verdict is computed against the
current date every time it is asked for -- in Python for one listing, and as a
SQL expression for a filter over the whole catalog, so the two cannot drift.

**Three states, describing the evidence rather than the law.** Eligible by age,
not eligible by age, and unknown. Deliberately not "C&R: no" -- the other two
limbs of the definition are a museum curator's certification and being novel,
rare or bizarre, neither of which this application can see. A gun under fifty
may still be a curio, and saying otherwise about a regulated purchase is a
claim nothing here can support.

**Three sources, and the order matters more than the count.** Measured over
3,919 active listings:

* **The vendor says so** -- 623 listings (16%). The best source there is, and
  the description trimmer already protects it: the floor that stops
  ``Description **C&R FFL OK**`` being cut as boilerplate exists for this.
* **An explicit manufacture date** -- 413 (11%). "Dated 1943", "mfg. 1952".
  Somebody wrote a date and meant it.
* **A year that is not the model's own designation** -- 1,532 (39%). This is
  the one that needs the care, because a four-digit number in a milsurp title
  is usually a *pattern* year: "M1911A1" reads as 1911 whether the gun left
  Colt in 1943 or a reproduction shop in 2020, and the reproduction is exactly
  the case where being wrong costs somebody something.

  So a year is only read as a date when it is **not** in a designation context
  (``Model 1873``, ``Mk III``, ``91/30``) *and* does not appear in the name of
  the armory model the listing is matched to. The armory is what makes this
  safe: its model names are curated and approved, so "1891" against a
  Mosin-Nagant M91/30 is recognisably the pattern and "1943" is not.

Trusting bare years without that test resolves the same 66% of the catalog and
is wrong on the listings that matter; trusting only the first two sources
leaves 74% unknown, which is not a feature. Hence the three tiers.

**Only a firearm has a C&R status at all.** The classification is a category
of *firearm*: a bayonet, a helmet, a book or a parts kit with no receiver is
not something the ATF licenses, and telling a reader a 1943 cap is "C&R
eligible" is a wrong answer rather than a harmless one. So a listing that is
neither a rifle nor a handgun, or that is a parts kit, gets no verdict -- not
"unknown", which would say the question is open -- and no filter state picks
it up. The test is applied where the verdict is worked out, like the date,
rather than where the evidence is stored: a reclassify can move a listing in
or out of the firearm buckets without re-reading its text, and the evidence
has to be there when it moves in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import and_ as sa_and
from sqlalchemy import or_ as sa_or

#: The ATF's first limb: manufactured at least this many years ago.
CURIO_YEARS = 50

#: What the three states are called wherever one is written down.
ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not_eligible"
UNKNOWN = "unknown"

#: Where a reading came from, kept so a page can show its working rather than
#: asserting a conclusion at somebody.
BY_VENDOR = "vendor"
BY_DATE = "dated"
BY_YEAR = "year"

_YEAR = r"(1[7-9]\d{2}|20[0-2]\d)"

#: The vendor saying it outright. "C&R", "C & R", "curio".
_SAYS = re.compile(r"\bC\s*&\s*R\b|\bcurio\b", re.IGNORECASE)

#: ...and saying the opposite. Checked first, because "not C&R" contains "C&R"
#: and a naive match reads a refusal as a confirmation.
_DENIES = re.compile(r"\b(?:not|non)[\s\-]*C\s*&\s*R\b", re.IGNORECASE)

#: A date somebody wrote on purpose, either side of the year.
_DATED_BEFORE = re.compile(
    r"(?:dated|date|mfg\.?|mfd\.?|manufactured|made|production|prod\.?|built)"
    r"\s*(?:in\s*)?" + _YEAR,
    re.IGNORECASE,
)
_DATED_AFTER = re.compile(_YEAR + r"\s*(?:dated|production|mfg\b|manufacture)", re.IGNORECASE)

#: A year being used as a name. "Model 1873", "M1911", "Mk 1917", "Type 38".
_DESIGNATION = re.compile(r"(?:model|mod\.|m|mk|mark|pattern|patt|type)\s*" + _YEAR, re.IGNORECASE)

#: A pattern written as a fraction -- "91/30", "96/11" -- where the digits
#: either side are designations and neither is a date.
_FRACTION = re.compile(_YEAR + r"\s*/\s*\d|\d\s*/\s*" + _YEAR)

_ANY_YEAR = re.compile(_YEAR)


@dataclass(frozen=True)
class Reading:
    """What a listing's text says about when it was made, and how strongly.

    ``stated`` is the vendor's own assertion and outranks everything: True when
    they called it a C&R, False when they said it is not, None when they were
    silent. ``year`` is a manufacture year believed good enough to judge on.
    """

    stated: bool | None = None
    year: int | None = None
    evidence: str | None = None

    @property
    def says_anything(self) -> bool:
        return self.stated is not None or self.year is not None


def cutoff(today: date | None = None) -> int:
    """The newest manufacture year still eligible, as of today.

    UTC rather than the host's zone, so two machines in different places agree
    about which year it is -- the boundary only moves once a year, and the one
    day where they could disagree is exactly the day somebody would notice.
    """
    return (today or datetime.now(UTC).date()).year - CURIO_YEARS


def read(title: str, description: str | None = None, model_name: str | None = None) -> Reading:
    """What this listing's own words say. Never raises; silence is a Reading."""
    text = "\n".join(part for part in (title, description) if part)
    if not text:
        return Reading()

    # The vendor's own words first, and the denial before the confirmation.
    if _DENIES.search(text):
        return Reading(stated=False, evidence=BY_VENDOR)
    if _SAYS.search(text):
        return Reading(stated=True, evidence=BY_VENDOR)

    dated = [int(y) for y in _DATED_BEFORE.findall(text) + _DATED_AFTER.findall(text)]
    if dated:
        # The earliest, because a listing naming two dates is usually a receiver
        # and a later rebuild, and the ATF's question is when it was made.
        return Reading(year=min(dated), evidence=BY_DATE)

    loose = _loose_years(text, model_name)
    if loose:
        return Reading(year=min(loose), evidence=BY_YEAR)
    return Reading()


def _loose_years(text: str, model_name: str | None) -> list[int]:
    """Years in the text that are not being used as a name.

    Three things are excluded, and each of them is a way of writing a pattern:
    a designation prefix, a fraction, and any year that appears in the name of
    the armory model this listing was matched to.
    """
    designations = set(_DESIGNATION.findall(text))
    designations.update(_FRACTION.findall(text))
    if model_name:
        designations.update(_ANY_YEAR.findall(model_name))
    return sorted({int(y) for y in _ANY_YEAR.findall(text) if y not in designations})


def applies(is_rifle: bool, is_pistol: bool, is_parts_kit: bool) -> bool:
    """Whether this listing is a firearm, and so has a C&R status to give.

    A parts kit is excluded even though it is also filed as a rifle or a
    handgun: it is the gun *minus* its receiver, and the receiver is the part
    the law calls the firearm.
    """
    return bool((is_rifle or is_pistol) and not is_parts_kit)


def status(stated: bool | None, year: int | None, *, today: date | None = None) -> str:
    """Eligible, not eligible, or unknown -- as of ``today``.

    The vendor's word outranks the arithmetic. They are looking at the gun and
    at its proof marks, and a shop that files a listing under C&R has taken a
    position this application is in no place to overrule.
    """
    if stated is not None:
        return ELIGIBLE if stated else NOT_ELIGIBLE
    if year is not None:
        return ELIGIBLE if year <= cutoff(today) else NOT_ELIGIBLE
    return UNKNOWN


#: The three states, in the order a filter should offer them.
STATES: tuple[str, ...] = (ELIGIBLE, NOT_ELIGIBLE, UNKNOWN)


def clause(state: str, *, today: date | None = None):
    """The same judgment as :func:`status`, as something a query can ask.

    It exists twice because it is needed twice -- once for a listing in hand
    and once for a filter over the whole catalog -- and the two readings must
    agree or the browse count will disagree with the badge on the page it
    opens. ``test_curio.py`` holds them to the same answer over every
    combination rather than trusting that they were written to match.
    """
    from ..models import Item

    edge = cutoff(today)
    silent = Item.cr_stated.is_(None)
    # The same test as applies(), so a bayonet is in none of the three states
    # rather than quietly in "unknown".
    firearm = sa_and(
        sa_or(Item.is_rifle.is_(True), Item.is_pistol.is_(True)),
        Item.is_parts_kit.is_(False),
    )
    if state == ELIGIBLE:
        verdict = sa_or(
            Item.cr_stated.is_(True),
            sa_and(silent, Item.manufacture_year.is_not(None), Item.manufacture_year <= edge),
        )
    elif state == NOT_ELIGIBLE:
        verdict = sa_or(
            Item.cr_stated.is_(False),
            sa_and(silent, Item.manufacture_year.is_not(None), Item.manufacture_year > edge),
        )
    elif state == UNKNOWN:
        verdict = sa_and(silent, Item.manufacture_year.is_(None))
    else:
        raise ValueError(f"unknown curio state {state!r}")
    return sa_and(firearm, verdict)


def backfill(session: object, *, only_missing: bool = True, batch: int = 1000) -> dict[str, int]:
    """Read every stored listing's text and fill in the evidence columns.

    Shared by the migration that introduces the columns and by the CLI command
    that re-runs it, because the alternative is two readings of the same text
    that drift the first time a pattern is tightened.

    ``only_missing`` leaves alone any row that already carries a reading, which
    is what makes this safe to run on a schedule or twice by accident. Pass
    False after changing the rules above -- that is the case ``reclassify
    --recompute`` exists for, and this is the same shape.

    Takes a live session rather than opening one so the migration can hand it
    the connection it is already inside; an object rather than a Session in the
    signature for the same reason.
    """
    from sqlalchemy import select

    from ..models import FirearmModel, Item

    counts = {ELIGIBLE: 0, NOT_ELIGIBLE: 0, UNKNOWN: 0, "examined": 0}
    query = select(Item.id, Item.title, Item.description, FirearmModel.name).join(
        FirearmModel, FirearmModel.id == Item.firearm_model_id, isouter=True
    )
    if only_missing:
        query = query.where(
            Item.cr_stated.is_(None),
            Item.manufacture_year.is_(None),
            Item.cr_evidence.is_(None),
        )

    wrote = False
    pending: list[dict[str, object]] = []
    for item_id, title, description, model_name in session.execute(query):  # type: ignore[attr-defined]
        counts["examined"] += 1
        found = read(title or "", description, model_name)
        counts[status(found.stated, found.year)] += 1
        if not found.says_anything:
            # Nothing to write. Left null rather than stamped "unknown", so a
            # later run with better rules still sees it as unexamined.
            continue
        pending.append(
            {
                "_id": item_id,
                "cr_stated": found.stated,
                "manufacture_year": found.year,
                "cr_evidence": found.evidence,
            }
        )
        if len(pending) >= batch:
            _write(session, pending)
            wrote = True
            pending = []
    if pending:
        _write(session, pending)
        wrote = True

    # The write above goes through Core and so goes around the identity map:
    # anything the caller already had loaded still holds the old reading, and
    # would go on holding it through a re-read in the same session. It does not
    # matter to either caller here -- the CLI closes its session immediately
    # and the migration has no identity map at all -- and that is exactly why
    # it is worth doing rather than leaving for whoever calls this next.
    expire = getattr(session, "expire_all", None)
    if wrote and callable(expire):
        expire()
    return counts


def _write(session: object, rows: list[dict[str, object]]) -> None:
    from typing import cast

    from sqlalchemy import Table, bindparam, update

    from ..models import Item

    # **Against the table, not the mapped class.** This runs on a live ORM
    # Session (the CLI) and on a bare Connection (the migration), and handed
    # the class the two disagree: the ORM reads `execute(update(Item), [...])`
    # as its own bulk-update-by-primary-key and demands an `id` in every dict,
    # while the Connection wants the WHERE spelled out. Core has one meaning on
    # both. The migration path alone would never have shown this, which is what
    # the CLI-shaped test is for.
    # Cast because the declarative base types `__table__` as the general
    # FromClause; it is a Table, and update() wants to be told so.
    table = cast(Table, Item.__table__)
    session.execute(  # type: ignore[attr-defined]
        update(table).where(table.c.id == bindparam("_id")),
        rows,
    )
