"""The maker list, as data rather than as code.

:mod:`app.services.classify` still carries a built-in list, and it is still the
one used by the tests and by anything that has no database to hand. What this
module adds is that a deployment can edit it: the table is seeded from those
built-ins the first time it is empty, and from then on it is the table that
decides.

Two decisions are worth spelling out.

**Aliases are literal text, not patterns.** They arrive from a form on the
admin pages. A regular expression from a form is a way to hang the process on a
pathological backtrack and a way to match things nobody intended, and neither
is a fair thing to hand somebody who only wanted to write "S&W". Each spelling
is escaped and wrapped in word boundaries, with runs of whitespace allowed to
vary so "Smith & Wesson" still matches "Smith  &  Wesson".

**Order is part of the data.** The rules are tried in ``position`` order and
the first match wins, which is what keeps "Mosin-Nagant" from being filed under
"Nagant". Adding a maker whose name contains another maker's therefore means
placing it, not just naming it.
"""

from __future__ import annotations

import logging
import re
import threading

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import ArmoryStatus, FirearmModel, Item, Manufacturer
from . import classify

log = logging.getLogger("milsurp.manufacturers")

#: A compiled rule: the canonical name, and what matches it.
Rule = tuple[str, re.Pattern[str]]


def pattern_for(spellings: list[str]) -> re.Pattern[str]:
    """One case-insensitive pattern matching any of these spellings.

    Every spelling is escaped, so what the admin types is what is looked for.
    Whitespace inside a spelling is allowed to stretch, because OCR and vendors
    both space a name however they like.
    """
    alternatives = sorted((s for s in spellings if s.strip()), key=len, reverse=True)
    if not alternatives:
        return re.compile(r"(?!)")  # matches nothing
    # Split on whitespace and rejoin with \s+, rather than escaping the whole
    # string and then substituting: re.escape may or may not put a backslash in
    # front of a space depending on the version, and rewriting the space
    # afterwards turned "Smith & Wesson" into a pattern looking for a literal
    # backslash.
    body = "|".join(r"\s+".join(re.escape(part) for part in text.split()) for text in alternatives)
    # \b does not do anything useful next to "&" or ".", so the boundary is
    # asserted only where the spelling actually starts or ends with a word
    # character -- otherwise "S&W" would never match at all.
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)


class Registry:
    """The rules, in order, with the text they match."""

    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules

    def __len__(self) -> int:
        return len(self.rules)

    def extract(self, text: str) -> str | None:
        for name, pattern in self.rules:
            if pattern.search(text):
                return name
        return None

    def extract_from(
        self, title: str, description: str | None = None, caliber: str | None = None
    ) -> str | None:
        """The maker, preferring the title over the prose beneath it.

        A title is where a vendor says what they are selling. A description is
        where they talk about it, and on a flyer read by OCR it carries
        whatever the neighboring panel said -- which filed "CZ 50/70 PISTOL
        KITS" under Walther, because Walther is tried before CZ and the word
        appeared in text that had bled in from the next listing.

        The caliber is asked last, and answers more often than it looks like it
        should: a great many surplus cartridges are named after the firm that
        designed them, so "7x57mm Mauser" and "6.5x52mm Carcano" name a maker
        that the listing itself never mentions. "SPANISH 1916 SHORT RIFLES" is
        a Mauser and does not say so anywhere.
        """
        return (
            self.extract(title or "")
            or self.extract(f"{title or ''} {description or ''}")
            or (self.extract(caliber) if caliber else None)
        )


def _rules_from(session: Session) -> list[Rule]:
    """The maker rules: each firm's own spellings, plus the models only it made.

    The models come from the armory now, not from the flat list of names that
    used to hang off a maker. That list could only ever say "this firm made
    something called M44", which meant a designation two firms both made had to
    be dropped from matching entirely -- picking whichever row came first would
    have been an accident of ordering rather than a decision.

    In the armory a model is one row with all of its makers on it, so the same
    fact is expressible directly: a model with exactly one maker names that
    maker, and a model with several names none of them. Nine firms built the M1
    Carbine, so "M1 Carbine" in a title says nothing about who built this one.

    Only models an admin has promoted take part, for the reason everything else
    in the armory works that way: a pending row is a question, not a fact.
    """
    rows = (
        session.execute(
            select(Manufacturer)
            .where(
                Manufacturer.enabled.is_(True),
                # A maker a scan proposed, or one that arrived in the shipped
                # armory file, decides nothing until somebody promotes it --
                # the same rule the models and calibers follow.
                Manufacturer.status == ArmoryStatus.APPROVED,
            )
            .order_by(Manufacturer.position, Manufacturer.id)
        )
        .scalars()
        .all()
    )
    designations = _models_by_maker(session)
    return [
        (row.name, pattern_for([*row.spellings, *designations.get(row.id, [])])) for row in rows
    ]


def _models_by_maker(session: Session) -> dict[int, list[str]]:
    """Every spelling of every model that exactly one firm is known to have made."""
    found: dict[int, list[str]] = {}
    rows = (
        session.execute(
            select(FirearmModel)
            .options(selectinload(FirearmModel.manufacturers))
            .where(
                FirearmModel.enabled.is_(True),
                FirearmModel.status == ArmoryStatus.APPROVED,
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if len(row.manufacturers) == 1:
            found.setdefault(row.manufacturers[0].id, []).extend(row.spellings)
    return found


# Compiling forty patterns on every listing of a two-hundred-listing scan is
# wasted work, so the registry is built once and rebuilt when the table
# changes. The stamp is bumped by every write in this module, and any other
# writer should call invalidate().
_lock = threading.Lock()
_cached: Registry | None = None


def invalidate() -> None:
    """Forget the compiled rules; the next read rebuilds them."""
    global _cached
    with _lock:
        _cached = None


def registry(session: Session) -> Registry:
    global _cached
    with _lock:
        if _cached is None:
            _cached = Registry(_rules_from(session))
        return _cached


def extract(
    session: Session,
    title: str,
    description: str | None = None,
    caliber: str | None = None,
) -> str | None:
    """The maker named in a listing, or None.

    Falls back to the built-in list while the table is empty, so a database
    that has not been seeded yet behaves as it did before the table existed
    rather than losing every maker.
    """
    rules = registry(session)
    if not rules:
        return classify.extract_manufacturer(title, description)
    return rules.extract_from(title, description, caliber)


def canonical(session: Session, name: str | None) -> str | None:
    """The table's own spelling of a maker a vendor stated, or the name back.

    A stated maker is the vendor's, and this does not argue with it -- it only
    settles *how it is written*. "S&W" and "Smith & Wesson" are the same firm
    written twice, and the browse page can only offer one of them: without this
    the Manufacturer filter listed both, 25 listings under one and 53 under the
    other, and picking either hid the rest.

    The same argument the armory already makes about calibers, where ".32 ACP"
    and "7.65mm Browning" are one cartridge and a filter has to choose. It
    collapses exactly what somebody has declared to be an alias and nothing
    else: "Springfield" and "Springfield Armory" stay apart until the armory
    says they are one firm, which is a curation question and not this
    function's to answer.

    Matched whole rather than by search, so a maker named inside a longer
    string is not silently rewritten -- this is asked about a *field*, not
    about prose.
    """
    stated = " ".join((name or "").split())
    if not stated:
        return None
    for canonical_name, pattern in registry(session).rules:
        if pattern.fullmatch(stated):
            return str(canonical_name)
    return stated


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def seed(session: Session) -> int:
    """Fill an empty table from the built-in list. Returns how many were added.

    Only ever adds what is missing: an admin who deletes a maker deliberately
    should not find it back the next time the process restarts, so a table with
    anything in it is left alone entirely.
    """
    if session.execute(select(func.count(Manufacturer.id))).scalar_one():
        return 0

    for position, (pattern, name) in enumerate(classify.MANUFACTURER_PATTERNS):
        session.add(
            Manufacturer(
                name=name,
                aliases="\n".join(_spellings_in(pattern, name)) or None,
                # Approved, and the only thing here that is. This list is the
                # classifier's own vocabulary moved into a table rather than
                # anybody's proposal, and a fresh install whose maker matching
                # did nothing until somebody clicked through thirty-six rows
                # would be broken on arrival. Everything else -- an admin's
                # form, a scan's proposal -- arrives pending.
                status=ArmoryStatus.APPROVED,
                position=(position + 1) * 10,
            )
        )
    session.flush()
    invalidate()
    log.info("Seeded %d manufacturers from the built-in list", len(classify.MANUFACTURER_PATTERNS))
    return len(classify.MANUFACTURER_PATTERNS)


#: The built-in list is regular expressions. The seed turns each back into the
#: plain spellings it was written to match, which is possible because they are
#: all of one shape: alternatives of literal words with the odd optional
#: character. Anything that will not come apart cleanly is left as the
#: canonical name alone, and can be given its aliases by hand.
#: A model designation is a plain string, and plenty of them contain a slash:
#: "91/30", "CZ 50/70". Without it those were dropped from the seeded aliases
#: and the table went in missing exactly the spellings a dealer actually uses.
_LITERAL = re.compile(r"^[\w&.'/ -]+$")

#: The two ways the built-ins spell "this character is optional".
_OPTIONAL_CLASS = re.compile(r"\[([^\]]*)\]\?")
_OPTIONAL_CHAR = re.compile(r"(.)\?")


def _variants(text: str) -> list[str]:
    """Every literal string an optional-character pattern stands for.

    "Mosin[- ]?Nagant" is three spellings, and a vendor uses all three.
    """
    match = _OPTIONAL_CLASS.search(text) or _OPTIONAL_CHAR.search(text)
    if not match:
        return [text]
    choices = [*match.group(1), ""] if match.re is _OPTIONAL_CLASS else [match.group(1), ""]
    found = []
    for choice in choices:
        for rest in _variants(text[: match.start()] + choice + text[match.end() :]):
            if rest not in found:
                found.append(rest)
    return found


def _spellings_in(pattern: str, name: str) -> list[str]:
    found: list[str] = []
    for branch in pattern.split("|"):
        text = branch.replace(r"\b", "").replace("\\", "")
        for candidate in _variants(text):
            spelling = candidate.strip()
            if not spelling or not _LITERAL.match(spelling):
                continue
            if spelling.lower() == name.lower() or spelling.lower() in {f.lower() for f in found}:
                continue
            found.append(spelling)
    return found


# ---------------------------------------------------------------------------
# Re-deriving the catalog after an edit
# ---------------------------------------------------------------------------
def reprocess(session: Session, spellings: list[str]) -> int:
    """Re-derive the maker on every listing that mentions one of ``spellings``.

    Re-running the whole catalog after every edit would be correct and slow.
    An edit can only change the answer for a listing whose text contains one of
    the strings involved -- the ones being added, and the ones being taken away
    -- so those are the only rows fetched.

    Returns how many listings changed. Both directions are handled: a listing
    can gain a maker, and one can lose it when the rule that gave it is
    deleted.
    """
    wanted = [text.strip() for text in spellings if text and text.strip()]
    if not wanted:
        return 0

    clauses = []
    for text in wanted:
        pattern = f"%{_escape_like(text)}%"
        clauses.append(Item.title.like(pattern, escape="!"))
        clauses.append(Item.description.like(pattern, escape="!"))

    candidates = session.execute(select(Item).where(or_(*clauses))).scalars().all()
    rules = registry(session)
    changed = 0
    for item in candidates:
        found = rules.extract_from(item.title, item.description, item.caliber)
        if found != item.manufacturer:
            item.manufacturer = found
            changed += 1
    return changed


def _escape_like(text: str) -> str:
    """Make a literal safe inside a LIKE pattern, with ! as the escape."""
    return text.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def reprocess_everything(session: Session) -> int:
    """Re-derive the maker on every listing. For a change of order or a reseed."""
    rules = registry(session)
    changed = 0
    for item in session.execute(select(Item)).scalars():
        found = rules.extract_from(item.title, item.description, item.caliber)
        if found != item.manufacturer:
            item.manufacturer = found
            changed += 1
    return changed
