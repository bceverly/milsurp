"""How many rounds a gun holds: its magazine's, or its cylinder's.

Asked for on 2026-10-16: "capture capacity (I know that's a bit goofy with
semi-autos because you can get different magazines but let's go with the
non-California standard capacity and store it as an attribute of the model
and show it on the inventory details page ... and i'd like to be able to
search by capacity."

**Two places it comes from**, as the frame size does (app.services.frames).
A listing that states its capacity is taken at its word, with the words kept;
one that does not takes its model's standard capacity from the armory.

**What a listing says.** Measured over production's 16,912 gun listings on
2026-10-16, a capacity is written a handful of ways: "17rd" (a police
trade-in's title), "17+1", "One 17-round magazine included", "Capacity: 6",
"magazine capacity (incl) (1) 15rd", "6-Shot Revolver". Only a number tied
to a magazine, a cylinder or the word capacity is read -- "200 rounds through
it", a "50 round box" or "3rd generation" are not capacities -- and a number
no gun of the kind holds is passed over.

**The model's standard capacity** is the one its listings state most often,
where at least two agree -- with one exception that is the point of the
request: 10, the restricted-state count, gives way to the full capacity when
the model is commonly sold with more. A Glock 17's listings say 17 and 10;
its capacity is 17. A Ruger 10/22's say 10; its capacity is 10. Typed in the
Armory, it stays as typed.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

#: The longest quote kept, as for the barrel and the frame.
_QUOTE_CHARS = 160
#: The most a gun of each kind is taken to hold. Anything more is a box of
#: ammunition, a round count or a drum somebody is selling with it.
MOST = {"handgun": 50, "revolver": 12, "long": 100}
#: The restricted-state count, which gives way to a full one (see above).
RESTRICTED = 10

# A number of rounds, not a price, a decimal or part of a longer number:
# "17 round capacity 4.25\" barrel" is 17, not 4.
_N = r"(?<![\d.$#,/])(\d{1,3})(?!\.\d|\d)"
_ROUNDS = r"(?:rds?|rnds?|rounds?|shots?|shell)"
#: The ways a capacity is written, strongest first.
_PATTERNS = (
    # A labeled field: "Capacity: 6", "capacity 6 Shot", "magazine capacity
    # (incl) (1) 17rd", "Capacity: 10+1".
    re.compile(
        r"\bcapacity\b\s*(?:\(incl\)\s*\(\d+\)\s*|[:\-]\s*|is\s+|of\s+)?" + _N
        # Alone: not "Capacity 1 8 Round Magazine" (one magazine of eight),
        # "Capacity 1lb" or "Capacity 2\" Barrel", which ran into the next field.
        + r"(?!\s*/|\s+\d|\s*(?:lbs?|oz|in|inch|mm|x)\b|\s*[\"″”])",
        re.I,
    ),
    # "17+1", "15 + 1".
    re.compile(_N + r"\s*\+\s*1\b(?!\s*(?:/|\d))", re.I),
    # "17 round capacity", "10/13 round capacity", "17-round magazine",
    # "6 shot cylinder", "5 shot rotary magazine", "20rnd Magazines".
    re.compile(
        _N
        + r"(?:\s*/\s*(\d{1,3}))?[\s-]*"
        + _ROUNDS
        + r"[\s-]+(?:(?:double|single|stack|steel|factory|oem|detachable|box|rotary|"
        r"extended|flush|fit|metal|tube|tubular|internal|stripper)[\s-]+){0,2}"
        r"(?:capacity|magazines?|mags?|clips?|cylinders?|tube)\b",
        re.I,
    ),
    # "6-Shot Revolver", "8 shot, .357 Mag".
    re.compile(_N + r"[\s-]*shot\b(?![\s-]*(?:gun|shell|size|cup|bird|buck|lead|steel))", re.I),
)
#: In a title, a bare "17rd" or "6 RD" is the shops' way of giving it: Grab
#: a Gun's "Glock 17 Gen5 | 9mm | Night Sights | 17rd Pistol".
_TITLE_ROUNDS = re.compile(_N + r"[\s-]*(?:rd|rds|rnd|rnds|round|rounds)\b", re.I)
#: What a glued "3rd" must be followed by to be three rounds rather than the
#: third of something: "3rd Variation", "3rd Chinese Contract" are ordinals.
_ROUNDS_AFTER = re.compile(
    r"^\s*(?:mags?|magazines?|clips?|capacity|pistol|rifle|revolver|cylinder|$|[|,])", re.I
)
#: A count, not a capacity: rounds fired, a box of them, a round count.
_NOT_AFTER = re.compile(
    r"^\s*(?:through|fired|of\s+(?:ammo|ammunition)|count|box|boxes|downrange|or\s+less)\b",
    re.I,
)


def _quote(text: str, start: int, end: int) -> str:
    left = max(text.rfind(mark, 0, start) for mark in (". ", "\n", "|", "*"))
    left = max(left + 1, start - 60)
    rights = [i for i in (text.find(mark, end) for mark in (". ", "\n", "|", "*")) if i != -1]
    right = min(*rights, len(text), end + 50)
    return re.sub(r"\s+", " ", text[left:right]).strip(" ,;:-").rstrip(".")[:_QUOTE_CHARS]


def _most(kind: str | None, revolver: bool) -> int:
    if revolver:
        return MOST["revolver"]
    return MOST["handgun"] if kind == "handgun" else MOST["long"]


def _plausible(number: int, kind: str | None, revolver: bool) -> bool:
    return 1 <= number <= _most(kind, revolver)


def _ordinal(text: str, found: re.Match[str]) -> bool:
    """A glued "3rd" or "23rd" that is not followed by what holds rounds."""
    glued = text[found.start(1) : found.end()].lower().replace(" ", "")
    number = found.group(1)
    return (
        glued.startswith(f"{number}rd")
        and number.endswith("3")
        and not number.endswith("13")
        and not _ROUNDS_AFTER.match(text[found.end() :])
    )


def _hits(
    text: str, patterns: tuple[re.Pattern[str], ...], kind: str | None, revolver: bool
) -> list[tuple[int, int, str]]:
    """Each capacity the patterns find in *text*: ``(where, rounds, quote)``."""
    found = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            if _ordinal(text, match) or _NOT_AFTER.match(text[match.end() :]):
                continue
            numbers = [int(g) for g in match.groups() if g and g.isdigit()]
            # "10/13 round capacity": two magazines; the larger is standard.
            number = max(numbers) if numbers else 0
            if _plausible(number, kind, revolver):
                found.append((match.start(), number, _quote(text, match.start(), match.end())))
    return found


def read(
    title: str, description: str | None, *, kind: str | None = None, revolver: bool = False
) -> tuple[int | None, str | None]:
    """The capacity a listing states, and the words it said it in.

    ``kind`` is "handgun" or "long" (a rifle or shotgun), ``revolver`` whether
    it is one: each bounds what a capacity can be.
    """
    # A title is one short line: the first capacity it names, whichever way
    # ("with 20rnd and 10rnd Magazines" is the 20). A description is prose:
    # its strongest way of saying it first.
    title_hits = _hits(title or "", (*_PATTERNS, _TITLE_ROUNDS), kind, revolver)
    if title_hits:
        return min(title_hits)[1:]
    for pattern in _PATTERNS:
        hits = _hits(description or "", (pattern,), kind, revolver)
        if hits:
            return min(hits)[1:]
    return None, None


def kind_of(item: Any) -> tuple[str | None, bool]:
    """A listing's kind for :func:`read`: handgun or long gun, and revolver."""
    kind = getattr(item, "kind", None) or ""
    revolver = "revolver" in kind
    if getattr(item, "is_pistol", False):
        return "handgun", revolver
    if getattr(item, "is_rifle", False):
        return "long", revolver
    return None, revolver


def applies(item: Any) -> bool:
    return bool(
        (getattr(item, "is_rifle", False) or getattr(item, "is_pistol", False))
        and not getattr(item, "is_parts_kit", False)
    )


def apply(item: Any) -> None:
    """Read one listing's capacity, or take its model's; store it.

    As the frame size: the listing's own words first, kept as
    ``capacity_quote``; where it says nothing, its model's standard capacity
    from the armory, with no quote.
    """
    if not applies(item):
        item.capacity = item.capacity_quote = None
        return
    kind, revolver = kind_of(item)
    number, quote = read(item.title or "", item.description, kind=kind, revolver=revolver)
    if number is None:
        model = getattr(item, "firearm_model", None)
        number = getattr(model, "capacity", None) if model is not None else None
    item.capacity = number
    item.capacity_quote = quote


def standard(stated: list[int]) -> int | None:
    """A model's standard capacity from what its listings state.

    The most common, where at least two listings agree; but 10, the
    restricted-state count, gives way to the most common higher one when
    that is stated at least a third as often (a Glock 17's 17 over its 10s).
    """
    counts = Counter(stated)
    if not counts:
        return None
    number, times = counts.most_common(1)[0]
    if number == RESTRICTED:
        higher = [(n, t) for n, t in counts.most_common() if n > RESTRICTED]
        if higher and higher[0][1] >= max(2, times / 3):
            number, times = higher[0]
    return number if times >= 2 else None


def backfill(session: Any) -> dict[str, int]:
    """Read every stored gun's capacity; give each model with none its
    standard capacity from its listings; then fill in the listings that state
    none from their model. Migration 0080 and Site settings' re-read share it.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import load_only, selectinload

    from ..models import FirearmModel, Item

    counts = {"examined": 0, "stated": 0, "models": 0, "from_armory": 0}
    guns = (
        select(Item).where(
            (Item.is_rifle.is_(True)) | (Item.is_pistol.is_(True)), Item.is_parts_kit.is_(False)
        )
        # Only the columns read and written: a migration runs this, and later
        # columns must not break it (see frames.backfill).
        .options(
            load_only(
                Item.id,
                Item.title,
                Item.description,
                Item.kind,
                Item.is_rifle,
                Item.is_pistol,
                Item.is_parts_kit,
                Item.firearm_model_id,
                Item.capacity,
                Item.capacity_quote,
            ),
            selectinload(Item.firearm_model).load_only(FirearmModel.id, FirearmModel.capacity),
        )
    )
    stated: dict[int, list[int]] = {}
    items = list(session.execute(guns).scalars())
    for item in items:
        counts["examined"] += 1
        kind, revolver = kind_of(item)
        number, quote = read(item.title or "", item.description, kind=kind, revolver=revolver)
        item.capacity, item.capacity_quote = number, quote
        if number is not None:
            counts["stated"] += 1
            if item.firearm_model_id is not None:
                stated.setdefault(item.firearm_model_id, []).append(number)
    for model in session.execute(
        select(FirearmModel)
        .where(FirearmModel.capacity.is_(None))
        .options(load_only(FirearmModel.id, FirearmModel.capacity))
    ).scalars():
        found = standard(stated.get(model.id, []))
        if found is not None:
            model.capacity = found
            counts["models"] += 1
    session.flush()
    for item in items:
        if item.capacity is None and item.firearm_model is not None and item.firearm_model.capacity:
            item.capacity = item.firearm_model.capacity
            counts["from_armory"] += 1
    session.flush()
    return counts
