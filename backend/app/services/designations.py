"""Rifle designations and the calibers they imply, read from a table.

Forty-eight regular expressions in :mod:`app.services.classify`, which is the
step that turns a dealer's shorthand into a cartridge: K31 is 7.5x55 Swiss,
vz.24 is 8mm Mauser, a Mauser ES340 is a .22 trainer. Every one of those is a
fact about rifles that somebody knows and could not type in.

Built like :mod:`app.services.countries` and for the same reason -- the
matching happens inside ``classify.enrich``, which scrapers call, and a scraper
has no database session and should not be given one. See that module for the
full argument; this one only differs in the shape of a rule.

**A rule is two lists of literal text and a switch.** It matches when any
*spelling* appears and, if *requires* is filled, when any of those appears as
well, anywhere in the same text. The second list is how the original table
expressed "Mauser and 8mm in the same listing" -- eleven of the forty-eight
were co-occurrence rules written ``X.*Y|Y.*X``, and a phrase cannot say that.
The switch is whole-word matching, which is the difference between "walther
pp", meant to catch a Walther PPK, and "ak", which must not catch Krakow.

**Order decides, not specificity.** The first rule that matches wins. That is
deliberate and was measured: scored on what they matched instead, the loose
co-occurrence rules beat the precise ones, and ``swiss`` + ``rifle`` relabeled
five Vetterli and Peabody rifles that state their own caliber in their titles.
"""

from __future__ import annotations

import logging
import re
import threading

from sqlalchemy import select

from ..models import CaliberDesignation

log = logging.getLogger("milsurp.designations")

_lock = threading.Lock()
#: (caliber, spellings, requires) in the order the rules are tried, where
#: *requires* is None for a rule that has no second condition.
_rules: list[tuple[str, re.Pattern[str], re.Pattern[str] | None]] | None = None
_warned = False


def invalidate() -> None:
    """Forget the compiled rules; the next read rebuilds them."""
    global _rules, _warned
    with _lock:
        _rules = None
        _warned = False


def compile_any(spellings: str | None, *, whole_word: bool) -> re.Pattern[str] | None:
    """One list of spellings as a pattern, or None when the list is empty.

    Longest first so a phrase is preferred to a word inside it, and the words
    of a phrase are joined with ``\\s+`` rather than a literal space so that
    "lee enfield" reaches "Lee  Enfield". A spelling that must also match with
    no space at all -- "stetienne", "gew71" -- is written out separately, which
    is what the seed does.

    ``whole_word`` bounds the match with ``(?<!\\w)``/``(?!\\w)`` rather than
    ``\\b``, because ``\\b`` does nothing useful beside a full stop and half of
    these spellings start or end with one.
    """
    alternatives = sorted(
        {" ".join(line.split()) for line in (spellings or "").splitlines() if line.strip()},
        key=len,
        reverse=True,
    )
    if not alternatives:
        return None
    lead, tail = (r"(?<!\w)", r"(?!\w)") if whole_word else ("", "")
    body = "|".join(
        lead + r"\s+".join(re.escape(word) for word in text.split()) + tail for text in alternatives
    )
    return re.compile(body, re.IGNORECASE)


def _load() -> list[tuple[str, re.Pattern[str], re.Pattern[str] | None]] | None:
    global _warned
    try:
        from ..database import session_scope

        with session_scope() as session:
            rows = (
                session.execute(
                    select(CaliberDesignation)
                    .where(CaliberDesignation.enabled.is_(True))
                    .order_by(CaliberDesignation.position, CaliberDesignation.id)
                )
                .scalars()
                .all()
            )
            built = []
            for row in rows:
                spellings = compile_any(row.spellings, whole_word=row.whole_word)
                if spellings is None:
                    continue  # a rule with no spellings matches nothing
                built.append(
                    (
                        row.caliber,
                        spellings,
                        # The second list is never whole-word bounded. It holds
                        # fragments on purpose -- "8mm", "6.5", "7.5x55" --
                        # and a dealer writes "7.65mm", where a trailing
                        # boundary would refuse the match.
                        compile_any(row.requires, whole_word=False),
                    )
                )
    except Exception:
        if not _warned:
            _warned = True
            log.warning(
                "The caliber designations table could not be read; falling back to the "
                "built-in list. Edits on the Classification page will not take effect "
                "until this is fixed.",
                exc_info=True,
            )
        return None
    return built or None


def rules() -> list[tuple[str, re.Pattern[str], re.Pattern[str] | None]] | None:
    """The compiled rules, or None when the caller should use the built-ins."""
    global _rules
    with _lock:
        if _rules is None:
            _rules = _load()
        return _rules


def match(text: str) -> str | None:
    """The caliber of the first rule that matches *text*, or None."""
    compiled = rules()
    if not compiled:
        return None
    for caliber, spellings, requires in compiled:
        if not spellings.search(text):
            continue
        if requires is not None and not requires.search(text):
            continue
        return caliber
    return None


def available() -> bool:
    """Whether the table is answering."""
    return rules() is not None
