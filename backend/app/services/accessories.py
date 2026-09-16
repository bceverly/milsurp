"""The words that decide whether a listing is a part or a gun.

Three short lists that used to be tuples in :mod:`app.services.classify`, read
together and in a fixed order: a gun sold *with* something is not an accessory,
a title that names a gun is not an accessory, and after those two vetoes the
accessory words themselves decide. Same registry shape as
:mod:`app.services.countries`; read that module for why it is a registry.

**Why this one is worth getting out of the source.** These were substring
tests, and one of them was quietly wrong for every Springfield in the catalog:
"spring" is inside "Springfield", so a Springfield Model 1903 was an accessory
and never got a caliber -- 23 of the 28 in the database. "cover" inside
"recovered" and "rail" inside "trail" are the same trap. The accessory words
match on word boundaries now; ``suffix`` is the one deliberate exception, for
an optic, which is named by what it is on the end of.

The two veto lists are still substring matches, because that is what they were
and narrowing them is a change somebody should make on purpose and measure.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

from sqlalchemy import select

from ..models import ClassifierKeyword

log = logging.getLogger("milsurp.accessories")

#: The three lists, and the only three values ``kind`` may take.
ACCESSORY = "accessory"
PROMOTIONAL = "promotional"
FIREARM = "firearm"
KINDS = (ACCESSORY, PROMOTIONAL, FIREARM)

#: How a word is matched, and the only three values ``match`` may take.
MATCHES = ("word", "suffix", "substring")


@dataclass(frozen=True)
class Lists:
    """What one read of the table compiles to."""

    #: The accessory words, as one alternation, or None when the list is empty.
    accessory: re.Pattern[str] | None
    #: Substring vetoes, lowercase.
    promotional: tuple[str, ...]
    firearm: tuple[str, ...]


_lock = threading.Lock()
_lists: Lists | None = None
_warned = False


def invalidate() -> None:
    """Forget the compiled lists; the next read rebuilds them."""
    global _lists, _warned
    with _lock:
        _lists = None
        _warned = False


def _compile(words: list[tuple[str, str]]) -> re.Pattern[str] | None:
    """The accessory words as one alternation, longest first.

    Longest first so a phrase is preferred to a word inside it, and the phrases
    keep their spaces: ``\\b`` works around "en bloc clip" as readily as around
    "helmet".
    """
    if not words:
        return None
    ordered = sorted(words, key=lambda pair: len(pair[0]), reverse=True)
    body = "|".join(
        (r"\w*" if match == "suffix" else "") + re.escape(word) for word, match in ordered
    )
    return re.compile(rf"\b(?:{body})\b")


def _load() -> Lists | None:
    global _warned
    try:
        from ..database import session_scope

        with session_scope() as session:
            rows = (
                session.execute(
                    select(ClassifierKeyword)
                    .where(ClassifierKeyword.enabled.is_(True))
                    .order_by(ClassifierKeyword.kind, ClassifierKeyword.keyword)
                )
                .scalars()
                .all()
            )
            built = Lists(
                accessory=_compile(
                    [
                        (row.keyword.strip().lower(), row.match)
                        for row in rows
                        if row.kind == ACCESSORY
                    ]
                ),
                promotional=tuple(
                    row.keyword.strip().lower() for row in rows if row.kind == PROMOTIONAL
                ),
                firearm=tuple(row.keyword.strip().lower() for row in rows if row.kind == FIREARM),
            )
    except Exception:
        if not _warned:
            _warned = True
            log.warning(
                "The classifier keywords table could not be read; falling back to the "
                "built-in lists. Edits on the Classification page will not take effect "
                "until this is fixed.",
                exc_info=True,
            )
        return None
    if built.accessory is None and not built.promotional and not built.firearm:
        return None
    return built


def lists() -> Lists | None:
    """The compiled lists, or None when the caller should use the built-ins."""
    global _lists
    with _lock:
        if _lists is None:
            _lists = _load()
        return _lists


def looks_like_one(title_lower: str) -> bool | None:
    """Whether the title names a part, or None when there is no table.

    The order is the whole rule and is the order the constants were read in: a
    gun sold *with* an accessory is a gun, a title that names a gun is a gun,
    and only then do the accessory words get a say.
    """
    tables = lists()
    if tables is None:
        return None
    if any(phrase in title_lower for phrase in tables.promotional):
        return False
    if any(word in title_lower for word in tables.firearm):
        return False
    return bool(tables.accessory.search(title_lower)) if tables.accessory else False
