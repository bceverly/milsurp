"""Countries of origin, read from a table the operator can edit.

The list was 38 regular expressions in :mod:`app.services.classify`, so
teaching it that "Ishapore" means India was a code change, a review and a
deploy — for a fact about the world the operator knows and the programmer does
not. The maker list moved out of the code for exactly that reason and this
follows it.

**It could not follow it exactly, and the difference is the interesting part.**
A maker is matched by ``manufacturers.extract(session, …)``, called from the
scan where a session exists. A country is matched inside ``classify.enrich``,
which *scrapers* call too — and a scraper has no database session and should
not be given one: it runs against somebody else's website and the moment it can
write to the database it is a different kind of program.

So the rules live in a process-wide registry that loads itself once and is
dropped when the table changes, rather than being read per call. Any writer
must call :func:`invalidate`, the same contract :mod:`app.services.armory`
already has.

**And there is a fallback, deliberately loud.** A registry that cannot reach
its table returns nothing and says so, and ``classify`` falls back to the
constants it was seeded from. That path exists for the test suite, which builds
a classifier with no database at all, and for the minutes during an upgrade
before the migration has run. It is logged because a silent fallback would mean
the operator edits a country, sees nothing change, and has no way to find out
why.
"""

from __future__ import annotations

import logging
import re
import threading

from sqlalchemy import select

from ..models import Country

log = logging.getLogger("milsurp.countries")

_lock = threading.Lock()
#: (name, compiled) in the order the rules are tried, or None when not built.
_rules: list[tuple[str, re.Pattern[str]]] | None = None
#: Set once a load has failed, so the warning is not repeated per listing.
_warned = False


def invalidate() -> None:
    """Forget the compiled rules; the next read rebuilds them."""
    global _rules, _warned
    with _lock:
        _rules = None
        _warned = False


def _compile(spellings: list[str]) -> re.Pattern[str]:
    """One country's spellings as a pattern.

    Escaped, longest first, and bounded by ``(?<!\\w)``/``(?!\\w)`` rather than
    ``\\b`` — the same construction the maker matcher uses, and for the same
    reason: ``\\b`` does nothing useful beside a full stop, so "U.S.A." would
    never match with it.
    """
    alternatives = sorted((s.strip() for s in spellings if s.strip()), key=len, reverse=True)
    if not alternatives:
        return re.compile(r"(?!)")  # matches nothing
    body = "|".join(r"\s+".join(re.escape(part) for part in text.split()) for text in alternatives)
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)


def _load() -> list[tuple[str, re.Pattern[str]]] | None:
    """Build the rules from the table, or None if it cannot be read."""
    global _warned
    try:
        from ..database import session_scope

        with session_scope() as session:
            rows = (
                session.execute(
                    select(Country)
                    .where(Country.enabled.is_(True))
                    .order_by(Country.position, Country.id)
                )
                .scalars()
                .all()
            )
            # The aliases and *only* the aliases. Adding the country's own name
            # looks obviously right and is a behavior change: the pattern this
            # replaced for Finland was `\bFinn(?:ish)?\b`, which never matched
            # the word "Finland". Seeding the name as well moved 38 listings on
            # the first comparison -- a Mauser sold by "a gunsmith in Finland"
            # became Finnish, and a Turkish bayonet mentioning an Argentine
            # contract became Argentinian.
            #
            # Some of those were improvements and some were not, and that is
            # the point: the table's promise is that it starts out saying
            # exactly what the code said. Adding "Finland" to Finland's aliases
            # is now a one-line edit on a page, which is the whole feature.
            built = [(row.name, _compile((row.aliases or "").splitlines())) for row in rows]
    except Exception:
        if not _warned:
            _warned = True
            log.warning(
                "The countries table could not be read; falling back to the built-in list. "
                "Edits on the Countries page will not take effect until this is fixed.",
                exc_info=True,
            )
        return None
    if not built:
        return None
    return built


def rules() -> list[tuple[str, re.Pattern[str]]] | None:
    """The compiled rules, or None when the caller should use the built-ins."""
    global _rules
    with _lock:
        if _rules is None:
            _rules = _load()
        return _rules


def match(text: str) -> str | None:
    """The first country whose spellings appear in *text*.

    Returns None both for "no country here" and for "no table to ask", which
    the caller cannot tell apart — and does not need to, because the built-in
    list answers the second case identically to how this would have.
    """
    compiled = rules()
    if not compiled:
        return None
    for name, pattern in compiled:
        if pattern.search(text):
            return name
    return None


def available() -> bool:
    """Whether the table is answering, for the caller deciding whether to
    fall back rather than for anything user-facing."""
    return rules() is not None
