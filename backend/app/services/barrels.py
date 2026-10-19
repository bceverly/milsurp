"""A listing's barrel: how long it is, and whether its muzzle is threaded.

Asked for on 2026-10-13: both captured for every firearm, read from the
listing's own words, searchable by length, and used to narrow the variants a
listing could be. Until then the length was read only from the titles of
models still in production (app.services.variants), 315 of 16,535 firearms.

**Where the words are.** Measured over production's 16,535 firearm listings
that day: 8,805 mention a barrel somewhere in the title or description, and
the length comes in a dozen spellings -- '24" round barrel', "22 ½ inch
octagon barrel", '3-1/4" barrel', '2" BBL', "Barrel Length: 24.6 inches (625
mm)", "barrel length of 4.6 inches", '33" round rifled .577 caliber barrel',
"Barrels: 23" Inch". A length is only read where it is tied to the barrel --
beside the word, or under a "Barrel Length" label -- because a listing is
full of other lengths: overall, length of pull, sight radius, a shotgun's
chamber and shells, a twist rate, a bayonet. The one exception is the title of
a handgun or a modern long gun, where a bare '4"' or "16in" is the barrel by
the shops' convention (Greentop's '3" MATTE'); that is the rule
app.services.variants always used.

**Not every length beside "barrel" is the barrel's.** "Shortened by 3/4
inch", "3" from the muzzle", a barrel band, a barrel extension, the barrel's
date: each is excluded by the word in front or behind.

**Threaded means the muzzle**, for a suppressor, a brake or a flash hider:
"threaded barrel", "the muzzle is threaded 5/8x24", '4.5" THREADED', a thread
pitch ("1/2x28", "14x1 LH"), a thread protector. Not an M1's "barrel threads",
which are where the barrel screws into the receiver; not a shotgun "threaded
for choke tubes"; not a ramrod's threaded tip. A spec table's "Threaded Barrel:
No" and "non-threaded" are a stated no.

**Three states, as with the traits**: a length, or none; threaded, stated
not threaded, or nothing said -- and nothing said is the common answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .carry import _FRACTIONS

#: Where each quote is kept in ``Item.barrel_quotes``.
LENGTH = "length"
THREADED = "threaded"

#: The longest quote kept, as in app.services.traits.
_QUOTE_CHARS = 160

#: The plausible lengths, in inches. A handgun's run from a derringer's inch
#: to a Contender's or a Buntline's foot and more; a long gun's from a short-
#: barreled rifle's 7.5" to a fowler's 51". An unknown kind takes both.
HANDGUN = (1.0, 20.0)
LONG_GUN = (7.0, 60.0)

# A number of inches: a whole number, a decimal, or a whole and a fraction
# written any of the ways the shops write one -- "22 1/2", "20-1/2", "3 ¼",
# "22½". Never preceded by a digit, a point or a slash: "3/4" alone is a
# fraction of an inch, not a length of four. Nor by an opening quote: '“2” ON
# TOP OF BARREL' is a stamp quoted, not two inches.
_NUMBER = (
    r"(?<![\d./“\u2018])(\d{1,4}(?:\.\d{1,3})?)"
    r"(?:(?:\s+|\s*-\s*|\s*(?:&|and)\s*)(\d{1,2})/(\d{1,2})|\s*([¼½¾]))?"
)
# What says inches: a mark, the word, its abbreviation.
_INCH = r"(?:\s*(?:\"|”|″|“|''|\u2019\u2019|â€³|â€\x9d)|\s*-?\s*inch(?:es)?\b|\s*in\b\.?)"
_MM = r"\s*(mm|cm)\b"

# The words that may sit between a length and "barrel": "24" round barrel",
# '33" round rifled .577 caliber barrel', '28" Vent Rib Barrel'. Short and
# without a sentence's punctuation, so the length and the barrel are one
# phrase.
_BETWEEN = r"(?:[\s,-]+(?:[a-z][a-z/&'-]*|&|\.?\d{2,3}\s*(?:cal\.?|caliber)|\d{1,2}\s*ga\.?)){0,6}?"
_BARREL_WORD = r"\s*(?:barrel(?:s|ed)?|bbls?\b\.?)"
# A barrel band, its extension, its date: the word after "barrel" that makes
# the phrase about something else.
_NOT_THE_BARREL = re.compile(
    r"^\s*(?:band|bands|extension|lug|wedge|nut|key|shroud|bushing|ring|tang|channel|"
    r"weight|weights|date|dated|marking|markings|mark|stamp|address|tenon|loop|"
    r"rib\s+(?:sight|mount)|action|receiver|liner|insert|handle|shaped|style)\b",
    re.I,
)
# A length that is something else: "shortened by 3/4"", "cut 2" from the
# muzzle", "1:10" twist".
_NOT_A_LENGTH_BEFORE = re.compile(
    r"(?:\bby|\bcut|\bremoved|\bshortened|\bextended|\bfrom|\bof\s+pull|\bpull|"
    r"\bradius|\bchamber(?:ed)?|\boverall|\boal|\btotal|\bscope|\btwist|1:|\bx)\s*$",
    re.I,
)
_NOT_A_LENGTH_AFTER = re.compile(
    r"^\s*(?:from|of\s+(?:the\s+)?muzzle|shorter|longer|twist|chamber|shells?|long\s+overall|"
    r"lop|length\s+of\s+pull|sight\s+radius|magnum\s+shells?)\b",
    re.I,
)
# An overall length stated just before: "The overall length is 58 inches, the
# barrel is 43 ½ inches", "Overall Length: 55.5" Barrel: 37". Only the label
# itself -- '55" o/a with 39" octagon barrel' gives the barrel second.
_OVERALL_BEFORE = re.compile(
    r"(?:overall|o/a|o\.a\.|\boal|total)(?:\s+length)?\s*(?:is|:|of|measures|=)?\s*"
    r"(?:(?:approx(?:imately|\.)?|about|around)\s*)?$",
    re.I,
)
# Words between a length and "barrel" that make it some other length:
# '13 1/2" trigger pull with a browned octagonal barrel', "7 inch steel rod
# with walnut barrel handle".
#
# Nor a mark on it: 'A 1" LIGHT SCRATCH ON THE BARREL'. A word describing the
# barrel sits between ("round", "octagon", "vent rib"); a preposition or a
# blemish means the length is of something on it.
_OTHER_MEASURE = re.compile(
    r"\b(?:pull|drop|overall|o/a|oal|wide|twist|chambers?|rod|stock|sight|radius|scope|"
    r"on|of|to|from|near|along|across|under|at|"
    r"scratch(?:es)?|dings?|dents?|nicks?|gouges?|cracks?|spots?|patch(?:es)?|areas?|"
    r"sections?|lines?|pitting|wear|marks?)\b",
    re.I,
)
# A barrel's shape, whose "to" is not a preposition: '2 1/2" OCTAGON TO ROUND
# BARREL', '.64 cal. octagon-to-multi sided-to-round steel barrel'.
_SHAPE = re.compile(r"\boctagon(?:al)?(?:[\s-]+to[\s-]+[a-z ]+?)?[\s-]+to[\s-]+round\b", re.I)
# A cut stated after the original: "7-1/2 inch round barrel has been shortened
# to 5-1/2 inches". What it is now is what is for sale.
_SHORTENED_TO = re.compile(
    rf"(?:barrel|bbl)[^.;\n]{{0,40}}?\b(?:shortened|cut(?:\s+down)?|reduced|cropped)\s+to\s+"
    rf"(?:(?:approx(?:imately|\.)?|about|around)\s*)?{_NUMBER}{_INCH}",
    re.I,
)
# A metric label's own conversion: "Barrel Length: 600 mm (24 in)".
_INCHES_BESIDE = re.compile(rf"^\s*[(/]\s*{_NUMBER}{_INCH}", re.I)

# And in a title's bare lengths, an overall length too: '27" overall'. Not
# after a label, where "Overall Length" is only the next field.
_OVERALL_AFTER = re.compile(r"^\s*(?:overall|oal|o\.a\.l\.)\b", re.I)

_LENGTH_BEFORE_BARREL = re.compile(
    rf"{_NUMBER}(?:{_INCH}|{_MM}){_BETWEEN}{_BARREL_WORD}",
    re.I,
)
# "Barrel Length: 18.5"", "barrel length of 4.6 inches", "Barrel: 22"",
# "Barrels: 23" Inch", "barrel is 20 inches", "BBL 16"". A label may give
# millimeters alone ("Barrel length: 600 mm").
_BARREL_THEN_LENGTH = re.compile(
    rf"(?:barrel(?:s)?|bbl\.?)(?:\s+(?:leng?th|lenght|size))?\s*"
    rf"(?:[:=-]|\bis\b|\bof\b|\bmeasures\b|\bat\b|\bto\b|\b(?:shortened|cut(?:\s+down)?)\s+to\b)?"
    rf"\s*(?:(?:approx(?:imately|\.)?|about|around|roughly|~)\s*)?{_NUMBER}(?:{_INCH}|{_MM})",
    re.I,
)
# A labeled length with no unit, inches understood: "Barrel Length: 28.5
# Total Length: 48.5 in", "Overall Length: 55.5" Barrel: 37". Only after the
# label and its colon, and never a date ("Barrel: 8-43").
_LABEL_NO_UNIT = re.compile(
    rf"barrels?(?:\s+(?:leng?th|lenght|size))?\s*:\s*{_NUMBER}"
    rf"(?![\d./-]|\s*(?:mm|cm|\"|”|″|in\b|inch))",
    re.I,
)
# A decimal straight before "barrel" in a title, no unit: '18.5 Barrel'.
_DECIMAL_BEFORE_BARREL = re.compile(r"(?<![\d./])(\d{1,2}\.\d{1,3})\s+barrel\b", re.I)
# The title convention: a bare length in a handgun's or a modern gun's title.
_BARE_LENGTH = re.compile(rf"{_NUMBER}{_INCH}", re.I)

# Hedges and generic prose: "the barrel length is usually about 59 cm" is the
# model, not this gun. Read in the few words in front of the match.
_GENERIC_BEFORE = re.compile(
    r"\b(?:usually|typically|normally|commonly|either|or\s+a|"
    r"available\s+(?:in|with))\b[^.;\n]{0,40}$",
    re.I,
)


def _inches(found: re.Match[str], start: int = 1) -> float | None:
    groups = found.re.groups or 0
    whole, num, den, glyph = (
        found.group(start + offset) if start + offset <= groups else None for offset in range(4)
    )
    if not whole:
        return None
    try:
        length = float(whole)
    except ValueError:
        return None
    if num and den and float(den) and float(num) < float(den):
        length += float(num) / float(den)
    if glyph:
        length += _FRACTIONS[glyph]
    unit = found.group(start + 4) if groups >= start + 4 else None
    if unit:
        length = length / 25.4 if unit.lower() == "mm" else length / 2.54
    return round(length, 3)


def _quote(text: str, start: int, end: int) -> str:
    """The phrase around a match, trimmed to a sentence's worth."""
    left = max(
        text.rfind(".", 0, start - 1) if start > 1 else -1,
        text.rfind("\n", 0, start),
        text.rfind(";", 0, start),
    )
    left = max(left + 1, start - 60)
    right_candidates = [text.find(mark, end) for mark in (".", "\n", ";")]
    right = min([c for c in right_candidates if c != -1] or [len(text)])
    right = min(right, end + 60)
    quote = re.sub(r"\s+", " ", text[left:right]).strip(" ,;:-")
    return quote[:_QUOTE_CHARS]


def _plausible(length: float | None, long_gun: bool | None) -> bool:
    if length is None:
        return False
    if long_gun is None:
        low, high = HANDGUN[0], LONG_GUN[1]
    else:
        low, high = LONG_GUN if long_gun else HANDGUN
    return low <= length <= high


def _not_the_barrels(pattern: re.Pattern[str], match: re.Match[str], text: str) -> bool:
    """Whether a length found beside "barrel" is some other length after all."""
    before = text[max(0, match.start() - 60) : match.start()]
    after = text[match.end() :]
    if _OVERALL_BEFORE.search(before[-30:]) or _GENERIC_BEFORE.search(before):
        return True
    if pattern is _LENGTH_BEFORE_BARREL:
        return bool(
            _NOT_THE_BARREL.match(after)
            or _NOT_A_LENGTH_BEFORE.search(before[-20:])
            or _OTHER_MEASURE.search(_SHAPE.sub(" ", match.group(0)))
        )
    return bool(_NOT_A_LENGTH_AFTER.match(after))


def _tied_lengths(
    text: str, long_gun: bool | None, *, title: bool = False
) -> list[tuple[float, int, int]]:
    """Every length tied to the barrel in the text, in order: (inches, start, end)."""
    found: list[tuple[float, int, int]] = []
    patterns = [_BARREL_THEN_LENGTH, _LENGTH_BEFORE_BARREL, _LABEL_NO_UNIT]
    if title:
        # Only a title: a spec table's "Magazine Count : 2.00 Barrel
        # Description" is a count beside the next label (a PPK/S, 2026-10-13).
        patterns.append(_DECIMAL_BEFORE_BARREL)
    for match in _SHORTENED_TO.finditer(text):
        length = _inches(match)
        if _plausible(length, long_gun):
            assert length is not None
            # Ahead of every other statement: the length before the cut is
            # usually stated first, in the same sentence.
            return [(length, match.start(), match.end())]
    for pattern in patterns:
        for match in pattern.finditer(text):
            if _not_the_barrels(pattern, match, text):
                continue
            length = _inches(match)
            beside = (
                _INCHES_BESIDE.match(text[match.end() :])
                if match.re.groups >= 5 and match.group(5)
                else None
            )
            if beside:
                length = _inches(beside)
            if _plausible(length, long_gun):
                assert length is not None
                found.append((length, match.start(), match.end()))
    found.sort(key=lambda row: row[1])
    return found


def read_length(
    title: str, description: str | None, *, long_gun: bool | None, bare_title: bool = True
) -> tuple[float | None, str | None]:
    """The barrel length the listing states, in inches, and the words it said it in.

    The title first, tied to the barrel and then bare: it is the shop's
    summary of this gun. Then the description's first statement -- a later
    one is as often a second barrel, a part that came with it, or the original
    length before a cut.
    """
    tied = _tied_lengths(title or "", long_gun, title=True)
    if tied:
        length, start, end = tied[0]
        return length, _quote(title, start, end)
    bare = _bare_title_length(title, long_gun) if bare_title and title else None
    if bare is not None:
        return bare
    tied = _tied_lengths(description or "", long_gun)
    if tied:
        length, start, end = tied[0]
        return length, _quote(description or "", start, end)
    return None, None


def _bare_title_length(title: str, long_gun: bool | None) -> tuple[float, str] | None:
    lengths = []
    for match in _BARE_LENGTH.finditer(title):
        if _NOT_A_LENGTH_AFTER.match(title[match.end() :]) or _OVERALL_AFTER.match(
            title[match.end() :]
        ):
            continue
        if _NOT_A_LENGTH_BEFORE.search(title[max(0, match.start() - 20) : match.start()]):
            continue
        length = _inches(match)
        # The title rule's own ranges (app.services.variants): a long gun's
        # title is full of other lengths below ten inches.
        low, high = (10.0, 34.0) if long_gun else (1.0, 8.5)
        if length is not None and low <= length <= high:
            lengths.append((length, match.start(), match.end()))
    if lengths:
        length, start, end = min(lengths)
        return length, _quote(title, start, end)
    return None


# --- threading ----------------------------------------------------------------
_PITCH = (
    r"(?:(?:\d/\d{1,2}|[½¼¾⅝])[\"”]?\s*[x×-]\s*\d{2}(?:\s*(?:tpi|rh|lh))?"
    r"|m?\d{2}(?:\.\d)?\s*(?:mm)?\s*[x×]\s*1(?:\.\d{1,2})?(?:\s*mm)?\s*"
    r"(?:lh|rh|(?:left|right)(?:[\s-]*hand(?:ed)?)?)"
    r"|m\d{2}(?:\.\d)?\s*[x×]\s*1(?:\.\d{1,2})?)"
)
_THREADED_YES = re.compile(
    r"\bthreaded\s+(?:[a-z-]+\s+){0,2}?(?:barrel|bbl|muzzle)\b"
    r"|\b(?:barrel|bbl|muzzle)\b[^.;\n]{0,40}?\b(?:is|are|comes|been|was|and)\s+threaded\b"
    r"|\b(?:barrel|bbl|muzzle)\s+threaded\b"
    r"|\bthreaded\s+(?:at|for|to\s+accept)\s+(?:the\s+)?(?:muzzle|front|suppressor|a\s+suppressor|"
    r"muzzle\s+devices?|compensators?|brakes?|a\s+muzzle)"
    r"|\bthreaded\s*(?:for\s*)?(?:muzzle\s*)?" + _PITCH + r"|\b"
    r"(?:muzzle\s+)?threads?\s*(?:pitch|pattern|size)?\s*:?\s*"
    + _PITCH
    + r"|"
    + _PITCH
    + r"\s*(?:muzzle\s+)?(?:thread(?:ed|s)?|tpi)\b"
    r"|\bthread\s+protector\b"
    r"|\d(?:\.\d+)?\s*(?:\"|”|″|in\b)\s*threaded\b"
    r"|\bthreaded\s+\d{1,2}\s*[x×-]\s*1\s*(?:lh|rh)\b",
    re.I,
)
_THREADED_NO = re.compile(
    r"\bthreaded(?:\s+barrel)?\s*:\s*(?:no|none|n)\b"
    r"|\b(?:w/o|without)\s+(?:an?\s+)?threaded\b"
    r"|\b(?:non|un)[\s-]?threaded\b"
    r"|\bnot\s+threaded\b"
    r"|\b(?:barrel|muzzle)\s+(?:is|are)\s+not\s+threaded\b",
    re.I,
)
# What else is threaded: a choke tube's seat, an M1's barrel shank, a ramrod.
_THREADED_ELSEWHERE = re.compile(
    r"\bchokes?\b|\bchoke\s+tubes?\b|\bramrod\b|\brod\b|\bnipples?\b|\bplug(?:ged)?\b|"
    r"\blanyard\b|\bscope\b|\bstock\b|\bhandguard\b|\breceiver\b|\bcap\b|\btip\b",
    re.I,
)
# "has been threaded" in "a prior owner had threaded the muzzle" reads right;
# "threads" alone in "barrel threads, and sight knurlings" is an M1's shank.
# A spare barrel is not the one on the gun: "spare unthreaded barrel",
# "SPARE THREADED BARREL" say nothing about it.
_SPARE_BEFORE = re.compile(r"\b(?:spare|extra|additional|second|2nd)\s+(?:[a-z]+\s+)?$", re.I)


def _elsewhere(text: str, start: int, end: int) -> bool:
    near = text[max(0, start - 30) : end + 30]
    return bool(re.search(r"\bchoke", near, re.I)) or bool(
        _THREADED_ELSEWHERE.search(near)
        and not re.search(r"barrel|muzzle|bbl|suppressor", text[start:end], re.I)
    )


def read_threaded(title: str, description: str | None) -> tuple[bool | None, str | None]:
    """Whether the listing says its muzzle is threaded, and the words it said it in."""
    for text in (title or "", description or ""):
        for no in _THREADED_NO.finditer(text):
            if _elsewhere(text, no.start(), no.end()):
                continue
            if _SPARE_BEFORE.search(text[max(0, no.start() - 25) : no.start()]):
                continue
            return False, _quote(text, no.start(), no.end())
        for yes in _THREADED_YES.finditer(text):
            if _SPARE_BEFORE.search(text[max(0, yes.start() - 25) : yes.start()]):
                continue
            if _elsewhere(text, yes.start(), yes.end()):
                continue
            return True, _quote(text, yes.start(), yes.end())
    return None, None


@dataclass(frozen=True)
class Reading:
    inches: float | None = None
    threaded: bool | None = None
    quotes: dict[str, str] = field(default_factory=dict)


def read(title: str, description: str | None, *, long_gun: bool | None) -> Reading:
    """The barrel this listing's words describe. Never raises."""
    inches, length_quote = read_length(title, description, long_gun=long_gun)
    threaded, threaded_quote = read_threaded(title, description)
    quotes = {}
    if length_quote:
        quotes[LENGTH] = length_quote
    if threaded_quote:
        quotes[THREADED] = threaded_quote
    return Reading(inches=inches, threaded=threaded, quotes=quotes)


def is_firearm(item: object) -> bool:
    """Whether a listing is a gun, and so has a barrel to describe."""
    return bool(
        (getattr(item, "is_rifle", False) or getattr(item, "is_pistol", False))
        and not getattr(item, "is_parts_kit", False)
    )


def _long_gun(is_rifle: bool, is_pistol: bool) -> bool | None:
    if is_rifle and not is_pistol:
        return True
    if is_pistol and not is_rifle:
        return False
    return None


def apply(item: Any) -> None:
    """Read one listing's barrel and store it; nothing for a listing that is not a gun.

    Overwritten each time, like the traits: none of it is a value a vendor
    supplied that needs protecting, and a description that grows a sentence
    should be re-read.
    """
    if not is_firearm(item):
        item.barrel_inches = item.barrel_threaded = item.barrel_quotes = None
        return
    found = read(
        item.title or "",
        item.description,
        long_gun=_long_gun(bool(item.is_rifle), bool(item.is_pistol)),
    )
    item.barrel_inches = found.inches
    item.barrel_threaded = found.threaded
    item.barrel_quotes = found.quotes or None


def backfill(session: Any, *, batch: int = 1000) -> dict[str, int]:
    """Read every stored gun's barrel. Shared by migration 0074 and ``cli.py
    barrels-backfill``, for the reason traits.backfill is."""
    from typing import cast

    from sqlalchemy import Table, bindparam, select, update

    from ..models import Item

    counts = {"examined": 0, "length": 0, "threaded": 0, "not_threaded": 0}
    table = cast(Table, Item.__table__)
    query = (
        select(table.c.id, table.c.title, table.c.description, table.c.is_rifle, table.c.is_pistol)
        .where(
            (table.c.is_rifle.is_(True)) | (table.c.is_pistol.is_(True)),
            table.c.is_parts_kit.is_(False),
        )
        .order_by(table.c.id)
    )
    pending: list[dict[str, object]] = []

    def write() -> None:
        session.execute(
            update(table).where(table.c.id == bindparam("_id")),
            pending,
        )
        pending.clear()

    for item_id, title, description, is_rifle, is_pistol in session.execute(query).all():
        counts["examined"] += 1
        found = read(title or "", description, long_gun=_long_gun(is_rifle, is_pistol))
        counts["length"] += found.inches is not None
        counts["threaded"] += found.threaded is True
        counts["not_threaded"] += found.threaded is False
        pending.append(
            {
                "_id": item_id,
                "barrel_inches": found.inches,
                "barrel_threaded": found.threaded,
                "barrel_quotes": found.quotes or None,
            }
        )
        if len(pending) >= batch:
            write()
    if pending:
        write()
    expire = getattr(session, "expire_all", None)
    if callable(expire):
        expire()
    return counts


def refresh(session: Any) -> dict[str, int]:
    """Re-read every gun's barrel, every handgun's frame size and every gun's
    capacity, serial and year made, then re-match the listings of models still made to
    their versions, which the first two narrow. What Site settings' "Re-read
    listing details" runs (services/makerjobs)."""
    from sqlalchemy import select

    from ..models import FirearmModel, Item
    from . import capacity, frames, serials, variants

    counts = backfill(session)
    framed = frames.backfill(session)
    held = capacity.backfill(session)
    made = serials.backfill(session)
    session.commit()
    counts = {
        **counts,
        "frames_stated": framed["stated"],
        "frames_from_armory": framed["from_armory"],
        "years_stated": made["stated"],
        "years_from_tables": made["table"],
        "years_placed": made["placed"],
        "capacity_stated": held["stated"],
        "capacity_from_armory": held["from_armory"],
    }
    relinked = 0
    modern = select(FirearmModel.id).where(FirearmModel.modern_production.is_(True))
    for item in session.execute(select(Item).where(Item.firearm_model_id.in_(modern))).scalars():
        was = item.variant_id
        variants.settle(session, item)
        relinked += int(item.variant_id != was)
    session.commit()
    return {**counts, "relinked": relinked}
