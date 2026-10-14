"""A handgun's frame size: full size, compact, subcompact -- or a revolver's frame.

Asked for on 2026-10-14: captured for every listing as the barrel is, kept in
the armory on models and their variants, and used to narrow the versions a
listing could be wherever both sides know it and a version matches.

**Two vocabularies, one field.** A semi-automatic's size is the class it is
sold in -- Full size, Compact, Subcompact, Micro, Long slide -- with the 1911
names put on that scale: a Government is full size, a Commander compact, an
Officer's subcompact. A revolver's is its frame: Smith & Wesson's letters
(J, K, L, N, X) or the small / medium / large frame other makers write.

**Where the words are.** Measured over production's 8,804 handguns on
2026-10-14. A title is the shop's summary, and its size words are the
version's name: "SIG P320 Full size", "BERETTA 92X RDO COMPACT", "WALTHER PDP
FS", "Glock G43X Sub-Compact". A description is mostly prose, and its
"compact" mostly an adjective -- "a compact and reliable firearm", "in a more
compact and lighter weight pistol", "compact design" -- which calls a Walther
PP or a P-64 compact and says nothing about a version. So from a description
only a labeled field ("Frame Size: Compact") or a capitalized size word naming
a version ("Tanfoglio Mossad Compact 9mm", "P320 Full Size 40 SW"), never one
an article or adjective introduces, and never a "Full-Size Grip". Read that
way the text gives a size for 292 of 8,545 pistols and revolvers; the armory supplies the rest, for
a model that is only ever one size (a Glock 19 is a compact).
"""

from __future__ import annotations

import re
from typing import Any

FULL = "Full size"
COMPACT = "Compact"
SUBCOMPACT = "Subcompact"
MICRO = "Micro"
LONG_SLIDE = "Long slide"
#: A semi-automatic's sizes, largest to smallest.
PISTOL_SIZES = (LONG_SLIDE, FULL, COMPACT, SUBCOMPACT, MICRO)
#: A revolver's frames: Smith & Wesson's letters, then everybody else's words.
REVOLVER_FRAMES = (
    "J-frame",
    "K-frame",
    "L-frame",
    "N-frame",
    "X-frame",
    "Small frame",
    "Medium frame",
    "Large frame",
)
SIZES = PISTOL_SIZES + REVOLVER_FRAMES

#: The longest quote kept, as for the barrel.
_QUOTE_CHARS = 160

_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (SUBCOMPACT, re.compile(r"\bsub[\s-]*compact\b", re.I)),
    (
        MICRO,
        re.compile(
            r"\bmicro(?:[\s-]*compact)?\b(?![\s-]*(?:galil|uzi|draco|ak|dot|red|meter|adjust))",
            re.I,
        ),
    ),
    (LONG_SLIDE, re.compile(r"\blong[\s-]*slide\b", re.I)),
    (FULL, re.compile(r"\bfull[\s-]*sized?\b", re.I)),
    (COMPACT, re.compile(r"(?<![\w-])(?<!sub )compact\b", re.I)),
    # The 1911's names. "Government" only as the model's name -- "U.S.
    # Government property" is not a size -- and "Officer's" only as the ACP,
    # never Colt's Officer's Model revolver or a police officer.
    (
        FULL,
        re.compile(
            r"\b(?:government|gov't|govt)\s+(?:model|size|frame|1911)\b"
            r"|\b1911(?:-?a1)?\s+gov(?:ernment|'?t)\b|\bcolt\s+gov(?:ernment|'?t)\b",
            re.I,
        ),
    ),
    (COMPACT, re.compile(r"\bcommander\b", re.I)),
    (
        SUBCOMPACT,
        re.compile(
            r"\bofficer'?s?\s+(?:acp|size|frame|model\s+1911)\b|\b1911\s+officer'?s?\b", re.I
        ),
    ),
)
#: "WALTHER PDP FS PRE OWNED": the shops' abbreviation, in a title, in capitals.
_FS = re.compile(r"(?<![\w/])FS(?![\w/])")
_LETTER_FRAME = re.compile(r"\b([JKLNX])[\s-]*frame\b", re.I)
_WORD_FRAME = re.compile(r"\b(small|medium|large)[\s-]*frame\b", re.I)
_LABEL = re.compile(
    r"\b(?:frame\s+size|size)\s*:\s*"
    r"(full[\s-]*size|compact|sub[\s-]*compact|micro|long[\s-]*slide|mid[\s-]*size)\b",
    re.I,
)
#: A grip, a holster or a magazine "full size" is not the gun's: the P320
#: Carry is a compact slide on a "Full-Size Grip".
_NOT_AFTER = re.compile(
    r"^[\s-]*(?:grips?|holsters?|mags?|magazines?|cases?|optics?|backstraps?)\b", re.I
)
#: Prose introducing an adjective: "a compact", "more compact", "is compact".
_DESCRIBING = re.compile(
    r"\b(?:a|an|the|this|its|their|more|very|quite|extremely|super|for|is|and|in|of|"
    r"little|small|handy)\s*$",
    re.I,
)


def normalize(text: str | None) -> str | None:
    """A typed or scraped size in the vocabulary: "full-size" -> "Full size"."""
    if not text:
        return None
    for size in SIZES:
        if text.strip().lower() == size.lower():
            return size
    found, _quote = read(text, None, revolver=None)
    return found


def _quote(text: str, start: int, end: int) -> str:
    left = max(text.rfind(mark, 0, start) for mark in (".", "\n", ";", "|"))
    left = max(left + 1, start - 60)
    rights = [i for i in (text.find(mark, end) for mark in (".", "\n", ";", "|")) if i != -1]
    right = min(*rights, len(text), end + 60)
    return re.sub(r"\s+", " ", text[left:right]).strip(" ,;:-")[:_QUOTE_CHARS]


def _shouting(text: str) -> bool:
    """A description in capitals, where a capital letter says nothing."""
    head = text[:400]
    letters = sum(ch.isalpha() for ch in head)
    return letters > 0 and sum(ch.isupper() for ch in head) > 0.6 * letters


def _acceptable(text: str, found: re.Match[str], in_title: bool) -> bool:
    if _NOT_AFTER.match(text[found.end() :]):
        return False
    if in_title:
        return True
    if not found.group(0)[:1].isupper() and not _shouting(text):
        return False
    before = text[max(0, found.start() - 20) : found.start()]
    # An article or adjective in front, or the start of a sentence: prose.
    return not (_DESCRIBING.search(before) or re.search(r"(?:^|[.!?]\s*)$", before))


def _pistol_size(text: str, in_title: bool) -> tuple[str, str] | None:
    if in_title and (found := _FS.search(text)):
        return FULL, _quote(text, found.start(), found.end())
    hits = [
        (found.start(), size, found.end())
        for size, pattern in _WORDS
        for found in pattern.finditer(text)
        if _acceptable(text, found, in_title)
    ]
    if not hits:
        return None
    hits.sort()
    # "a full-size long-slide handgun": the longer slide is the version.
    chosen = next((hit for hit in hits if hit[1] == LONG_SLIDE), hits[0])
    return chosen[1], _quote(text, chosen[0], chosen[2])


def _revolver_frame(text: str) -> tuple[str, str] | None:
    if found := _LETTER_FRAME.search(text):
        return f"{found.group(1).upper()}-frame", _quote(text, found.start(), found.end())
    if found := _WORD_FRAME.search(text):
        return f"{found.group(1).capitalize()} frame", _quote(text, found.start(), found.end())
    return None


def read(
    title: str, description: str | None, *, revolver: bool | None
) -> tuple[str | None, str | None]:
    """The frame size the listing states, and the words it said it in.

    ``revolver`` picks the vocabulary: True a revolver's frame, False a
    pistol's size, None either (a variant's label, a typed value).
    """
    for text, in_title in ((title or "", True), (description or "", False)):
        if (found := _LABEL.search(text)) and (word := normalize_word(found.group(1))):
            return word, _quote(text, found.start(), found.end())
        if revolver is not False and (frame := _revolver_frame(text)):
            return frame
        if revolver is not True and (sized := _pistol_size(text, in_title)):
            return sized
    return None, None


def normalize_word(word: str) -> str | None:
    key = re.sub(r"[\s-]+", " ", word.strip().lower())
    return {
        "full size": FULL,
        "compact": COMPACT,
        "mid size": COMPACT,
        "sub compact": SUBCOMPACT,
        "subcompact": SUBCOMPACT,
        "micro": MICRO,
        "long slide": LONG_SLIDE,
    }.get(key)


#: Kinds of handgun with a frame size to state. A flintlock or a percussion
#: pistol has none worth naming.
_PISTOL_KINDS = {None, "", "pistol"}
_REVOLVER_KINDS = {"revolver", "percussion_revolver"}


def vocabulary_for(kind: str | None) -> bool | None:
    """True for a revolver, False for a pistol, None for neither."""
    if kind in _REVOLVER_KINDS:
        return True
    if kind in _PISTOL_KINDS:
        return False
    return None


def applies(item: Any) -> bool:
    kind = getattr(item, "kind", None)
    return bool(
        getattr(item, "is_pistol", False)
        and not getattr(item, "is_parts_kit", False)
        and (kind in _PISTOL_KINDS or kind in _REVOLVER_KINDS)
    )


def apply(item: Any) -> None:
    """Read one listing's frame size, or take its model's; store it.

    The listing's own words first, kept as ``frame_quote``; where they say
    nothing, the armory's answer for a model that is only ever one size, with
    no quote -- the page says it came from the armory.
    """
    if not applies(item):
        item.frame_size = item.frame_quote = None
        return
    size, quote = read(
        item.title or "", item.description, revolver=vocabulary_for(getattr(item, "kind", None))
    )
    if size is None:
        model = getattr(item, "firearm_model", None)
        size = getattr(model, "frame_size", None) if model is not None else None
    item.frame_size = size
    item.frame_quote = quote


def backfill(session: Any) -> dict[str, int]:
    """Read every stored handgun's frame size. Migration 0075 and the Site
    settings re-read share it. ORM rather than Core: the model's size is
    the fallback."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from ..models import Item

    counts = {"examined": 0, "stated": 0, "from_armory": 0}
    query = (
        select(Item)
        .where(Item.is_pistol.is_(True), Item.is_parts_kit.is_(False))
        .options(selectinload(Item.firearm_model))
    )
    for item in session.execute(query).scalars():
        counts["examined"] += 1
        apply(item)
        if item.frame_quote:
            counts["stated"] += 1
        elif item.frame_size:
            counts["from_armory"] += 1
    session.flush()
    return counts


def label_variants(session: Any) -> int:
    """Give each variant with no frame size the one its label states. Returns
    how many were given one."""
    from sqlalchemy import select

    from ..models import ModelVariant

    given = 0
    for variant in session.execute(
        select(ModelVariant).where(ModelVariant.frame_size.is_(None))
    ).scalars():
        size, _quote = read(variant.label, None, revolver=None)
        if size:
            variant.frame_size = size
            given += 1
    session.flush()
    return given


class UnknownFrameSize(ValueError):
    """A typed frame size this vocabulary cannot read."""


def checked(text: str | None) -> str | None:
    """A typed size in the vocabulary, None for blank, or UnknownFrameSize."""
    if not text or not text.strip():
        return None
    size = normalize(text)
    if size is None:
        raise UnknownFrameSize(f"Unknown frame size {text!r}. Valid: {', '.join(SIZES)}.")
    return size
