"""When a gun was made: the year a listing states, or one its serial number places.

Asked for on 2026-10-15: "take listings ... where they list serial number in
the description and do a serial number lookup to determine the approximate
year of manufacture".

**The year first, in the dealer's words.** Many listings say it outright:
"Manufactured in 1945 at Springfield", "Date Manufactured: 1942", "Serial no.
165791. Manufactured circa mid-late 1942", "placing production in
approximately 1945". Only phrases about *making* are read -- never a bare year,
which on these titles is as often a model ("Model 1903", "1911", "M1917") or
an import ("1971 IMPORT"), and never the start of a production run ("Remington
began M1903 production in September 1941 at serial number 3,000,000").

**Then the serial**, only where the listing labels it -- "Serial no. 165791",
"Serial # 5121908", "Serial Number: 253765", "Serial#: AB167255", "S/N
12345" -- because a description is full of other numbers: SKUs, stock
numbers, drawing numbers. A partly hidden one ("serial number 10550xx", "in
the 5,8xx,xxx serial range") is kept as the range it could be.

**A serial is dated by a published table first** (2026-10-19): the
armory's serial ranges (``models.SerialRange``), each read from a source it
names -- the M1 Garand's Springfield and Winchester numbers, the M1 Carbine's
contractor blocks. Never a table typed from memory: a wrong one would be
worse than none, because it is believed.

**Then by evidence.** A serial no table covers is placed between the
listings of the same model and maker that state both a serial and a year:
the nearest below and the nearest above. Only where both exist and agree to
within :data:`MAX_SPAN` years -- "1943-1944", never a guess past the ends of
what is known.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

#: The widest estimate given, in years: a serial between a 1943 and a 1945
#: listing is "1943-1945"; wider than that says nothing worth showing.
MAX_SPAN = 2
#: The fewest listings stating both a serial and a year that a model and
#: maker need before any serial of theirs is placed.
MIN_EVIDENCE = 5
#: The share of neighbors, in serial order, allowed to run backward in year.
#: A model numbered straight through -- the M1 Garand, the M1 Carbine -- has
#: almost none; one whose numbers restart every year or block -- the P38, the
#: Luger, the K98k, with their year codes and letter suffixes -- has many,
#: and a serial alone cannot date it.
MAX_BACKWARD = 0.1
#: The earliest year read: the oldest guns sold here are flintlocks.
EARLIEST = 1700
#: The longest quote kept, as for the barrel.
_QUOTE_CHARS = 160

STATED = "stated"
TABLE = "table"
SERIAL = "serial"

# -- The serial number ---------------------------------------------------------
#: A serial: up to three letters, then digits -- a comma between groups, an
#: "x" for one hidden -- then up to two letters. "AB167255", "38828A",
#: "3,372,270", "10550xx".
_VALUE = r"([A-Z]{0,3}-?\d[\d,]*(?:[xX*]+[\dxX*,]*)?[A-Z]{0,2})"
_LABELED = re.compile(
    r"(?<![\w/])(?:serial(?:\s*(?:number|num\.?|no\.?|#))?|s/n|s\.n\.|SN(?=\s*[:#]))"
    r"\s*(?:is\s+|of\s+)?[:#]?\s*[\"“”']?" + _VALUE + r"(?![\w-])",
    re.I,
)
#: "in the 5,8xx,xxx serial range", "serial numbered in the 3,xxx,xxx range".
_RANGE = re.compile(
    r"(?:in|from)\s+the\s+" + _VALUE + r"\s+(?:serial(?:\s+number)?\s+)?range\b",
    re.I,
)
#: Words after a number that make it something else: a serial "range" is
#: handled above; a "serial number 3 digit" is a description of one.
_NOT_A_SERIAL_AFTER = re.compile(r"^\s*(?:digits?|rounds?|rd|mm|inch|in\b|\")", re.I)


@dataclass(frozen=True)
class Serial:
    text: str
    #: The serial's number, or the range a partly hidden one could be.
    low: int
    high: int
    quote: str
    #: Its letters in front, which are part of where it falls: Walther's "BC"
    #: block is not its "AG" block.
    prefix: str = ""


def _quote(text: str, start: int, end: int) -> str:
    left = max(text.rfind(mark, 0, start) for mark in (". ", "\n", "|"))
    left = max(left + 1, start - 70)
    rights = [i for i in (text.find(mark, end) for mark in (". ", "\n", "|")) if i != -1]
    right = min(*rights, len(text), end + 70)
    return re.sub(r"\s+", " ", text[left:right]).strip(" ,;:-").rstrip(".")[:_QUOTE_CHARS]


#: A serial's parts: its letters in front, its number, its letters after.
_PARTS = re.compile(r"([A-Za-z]{0,3})-?(\d[\d,]*(?:[xX*][\dxX*,]*)?)([A-WYZa-wyz]{0,2})")


def _number(value: str) -> tuple[str, int, int] | None:
    """A serial's prefix, its number, and the range a hidden digit allows:
    "AB167255" is AB 167255; "10550xx" is 1055000-1055099; "3,733,xxx"
    3733000-3733999."""
    parts = _PARTS.fullmatch(value)
    if not parts:
        return None
    digits = re.sub(r"[xX*]", "x", parts.group(2).replace(",", ""))
    if len(digits) < 3 or len(digits) > 9:
        return None
    return parts.group(1).upper(), int(digits.replace("x", "0")), int(digits.replace("x", "9"))


def read_serial(title: str, description: str | None) -> Serial | None:
    """The serial number the listing gives, labeled as one."""
    for text in (description or "", title or ""):
        for pattern in (_LABELED, _RANGE):
            for found in pattern.finditer(text):
                value = found.group(1).strip(",")
                if _NOT_A_SERIAL_AFTER.match(text[found.end() :]):
                    continue
                number = _number(value)
                if number is None:
                    continue
                prefix, low, high = number
                return Serial(value, low, high, _quote(text, found.start(), found.end()), prefix)
    return None


# -- A year stated --------------------------------------------------------------
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_PART = r"(?:(?:early|mid|late|the\s+end\s+of|spring|summer|fall|autumn|winter)[\s,\u2013-]*(?:to\s+|-\s*|\u2013\s*)?(?:late\s+|mid\s+)?(?:of\s+)?)?"
_YEAR = r"(1[789]\d\d|20[0-2]\d)"
#: "1954-1955", "1954-55", "1943/44".
_YEARS = _YEAR + r"(?:\s*(?:-|\u2013|/|to)\s*(\d{4}|\d{2})(?!\d))?"
#: "1917 production", "1942 mfg", "1944 manufacture". Not part of a model's
#: name ("P2020 Made in USA"), not where it was made ("Model 1907 Made in
#: USA"), and not a count ("ONLY 2000 MADE": see _COUNT_BEFORE).
_YEAR_FIRST = re.compile(
    r"(?<![A-Za-z\d-])"
    + _YEARS
    + r"\s+(?:production|manufacture|mfg\b\.?|mfd\b\.?|made\b(?!\s+in\s+(?!\d)))",
    re.I,
)
_STATED = (
    # A labeled field: "Date Manufactured: 1942", "Year of Manufacture 1917".
    re.compile(
        r"\b(?:date|year)\s+(?:of\s+)?(?:manufacture[d]?|mfg\.?|production|made)\s*[:\-]?\s*"
        + _PART
        + rf"(?:{_MONTH}\s+)?"
        + _YEARS,
        re.I,
    ),
    re.compile(r"\b(?:mfg\.?|manufactured)\s*(?:date|year)?\s*:\s*" + _YEARS, re.I),
    # Prose: "Manufactured in 1945", "made circa mid-late 1942", "produced
    # during 1944", "placing production in approximately 1945".
    re.compile(
        r"\b(?:manufactured|made|produced|built|mfg\.?|mfd\.?|placing\s+(?:its\s+)?production|"
        r"places?\s+(?:its\s+)?(?:manufacture|production))"
        r"\s+(?:in|during|circa|c\.|ca\.|around|about|approximately|approx\.?|sometime\s+in)"
        r"(?:\s+(?:circa|approximately|about|around|the\s+year))?\s+"
        + _PART
        + rf"(?:{_MONTH}\s*(?:of\s+)?)?"
        + _YEARS,
        re.I,
    ),
    # "Built 1911", "Manufactured 1943": the year straight after, as
    # Rock Island Auction writes it (2026-10-19). Not a count: "manufactured
    # 2000 rifles".
    re.compile(
        r"\b(?:built|manufactured|mfd\.?|mfg\.?)\s+"
        + _YEARS
        + r"(?!\s+(?:units|rifles|pistols|revolvers|guns|examples|of)\b)",
        re.I,
    ),
    _YEAR_FIRST,
    # "receiver circa January 1941", "circa 1944": a date for this gun.
    re.compile(r"\bcirca\s+" + _PART + rf"(?:{_MONTH}\s+)?" + _YEARS, re.I),
)
#: A year that starts or ends a production run, or is history, not this gun:
#: "began M1903 production in September 1941", "production ended in 1945".
#: And a year something else happened to it: "sold in a DCM Lottery circa
#: 1995", "rebuilt circa 1952", "imported in 1989" (2026-10-19).
_RUN_BEFORE = re.compile(
    r"\b(?:began|begun|begin|start(?:ed|ing)?|commenced|ended|ceased|stopped|until|"
    r"first|last|resumed|from|since|between|sold|imported|rebuilt|refurbished|reworked|"
    r"refinished|purchased|bought|lottery)\b[\w\s,.'-]{0,40}$",
    re.I,
)
#: A number of guns, not a year: "only 2000 made", "a total of 1,800 made".
_COUNT_BEFORE = re.compile(r"\b(?:only|just|total\s+of|some|approximately|about)\s*$", re.I)
_RUN_AFTER = re.compile(r"^\s*(?:to|until|through|and)\s+(?:\d{4}|the\b)", re.I)


@dataclass(frozen=True)
class Made:
    year_from: int
    year_to: int
    source: str
    quote: str


def _years(found: re.Match[str], first: int) -> tuple[int, int] | None:
    start = int(found.group(first))
    end_text = found.group(first + 1)
    end = start
    if end_text:
        end = int(end_text) if len(end_text) == 4 else start // 100 * 100 + int(end_text)
    this_year = datetime.now(UTC).year
    if not EARLIEST <= start <= end <= this_year or end - start > 10:
        return None
    return start, end


def read_stated_year(title: str, description: str | None) -> Made | None:
    """The year of manufacture the listing states, in its own words."""
    for text in (description or "", title or ""):
        hits = []
        for pattern in _STATED:
            for found in pattern.finditer(text):
                first = next(i for i in range(1, (pattern.groups or 0) + 1) if found.group(i))
                if _RUN_BEFORE.search(text[max(0, found.start() - 60) : found.start()]):
                    continue
                if _RUN_AFTER.match(text[found.end() :]):
                    continue
                if pattern is _YEAR_FIRST and _COUNT_BEFORE.search(text[: found.start()]):
                    continue
                years = _years(found, first)
                # "circa 1840s": the decade.
                if (
                    years
                    and years[0] == years[1]
                    and re.match(r"['\u2019]?s\b", text[found.end() :])
                ):
                    years = (years[0], min(years[0] + 9, datetime.now(UTC).year))
                if years:
                    hits.append((found.start(), years, found))
        if hits:
            _start, (year_from, year_to), found = min(hits, key=lambda hit: hit[0])
            return Made(year_from, year_to, STATED, _quote(text, found.start(), found.end()))
    return None


# -- Placing a serial between listings that state their year --------------------
@dataclass(frozen=True)
class Evidence:
    serial: int
    year_from: int
    year_to: int
    item_id: int
    prefix: str = ""


def place(serial: Serial, evidence: list[Evidence]) -> tuple[int, int, str] | None:
    """The years a serial falls between, from the listings that state both:
    the nearest below it and the nearest above, when they agree to within
    :data:`MAX_SPAN` years. A partly hidden serial must fall wholly between
    them. Returns ``(from, to, note)``, or None."""
    evidence = without_outliers([e for e in evidence if e.prefix == serial.prefix])
    if not runs_straight(evidence):
        return None
    below = [e for e in evidence if e.serial <= serial.low]
    above = [e for e in evidence if e.serial >= serial.high]
    if not below or not above:
        return None
    low = max(below, key=lambda e: (e.serial, e.year_from))
    high = min(above, key=lambda e: (e.serial, -e.year_to))
    year_from, year_to = min(low.year_from, high.year_from), max(low.year_to, high.year_to)
    # A listing below that states a later year than one above: the dealers
    # disagree here, and nothing can be said.
    if low.year_from > high.year_to or year_to - year_from > MAX_SPAN:
        return None
    note = (
        f"between serials {low.serial:,} ({_span(low.year_from, low.year_to)}) and "
        f"{high.serial:,} ({_span(high.year_from, high.year_to)}), as listings here state"
    )
    return year_from, year_to, note


def without_outliers(evidence: list[Evidence]) -> list[Evidence]:
    """The evidence without a year its neighbors on both sides contradict.

    A listing's stated year is sometimes not when the gun was made: a 1952
    National Match rebuild, a 1995 sale. Between two Springfield M1s of 1943
    and 1944, a "1952" is that, and it is left out rather than allowed to
    make the whole model look as if its numbers restart.
    """
    ordered = sorted(evidence, key=lambda e: (e.serial, e.year_from))
    kept = []
    for at, point in enumerate(ordered):
        before = ordered[at - 1] if at else None
        after = ordered[at + 1] if at + 1 < len(ordered) else None
        if (
            before
            and after
            and before.year_from <= after.year_to
            and not before.year_from - 1 <= point.year_from <= after.year_to + 1
        ):
            continue
        kept.append(point)
    return kept


def runs_straight(evidence: list[Evidence]) -> bool:
    """Whether a model's serials rise with its years, as the listings state
    them: enough of them, and few neighbors running backward.

    Measured on production's listings on 2026-10-15: placed among every
    listing, a serial's year was right 81 times in 101, and the misses were
    the P38, Luger, K98k, Nambu and K11, whose numbers restart. This is the
    test that tells those from the M1s, from the evidence itself rather than
    a list of models.
    """
    if len(evidence) < MIN_EVIDENCE:
        return False
    ordered = sorted(evidence, key=lambda e: (e.serial, e.year_from))
    backward = sum(1 for one, two in pairwise(ordered) if two.year_to < one.year_from)
    return backward <= MAX_BACKWARD * (len(ordered) - 1)


def _span(year_from: int, year_to: int) -> str:
    return str(year_from) if year_from == year_to else f"{year_from}-{year_to}"


def _maker(value: str | None) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())


def evidence_for(session: Any, model_id: int | None, maker: str | None) -> list[Evidence]:
    """The listings of a model and maker that state both a serial and a year.
    A serial is only placed among guns from the same maker: the M1 Garand's
    Winchester and Springfield numbers overlap."""
    if model_id is None or not _maker(maker):
        return []
    from sqlalchemy import select

    from ..models import Item

    rows = session.execute(
        select(
            Item.id,
            Item.manufacturer,
            Item.serial,
            Item.serial_low,
            Item.serial_high,
            Item.made_from,
            Item.made_to,
        ).where(
            Item.firearm_model_id == model_id,
            Item.made_source == STATED,
            Item.serial_low.is_not(None),
        )
    ).all()
    return [
        Evidence(low, year_from, year_to, item_id, prefix_of(text))
        for item_id, made_by, text, low, high, year_from, year_to in rows
        if low == high and _maker(made_by) == _maker(maker)
    ]


def prefix_of(text: str | None) -> str:
    number = _number(text or "")
    return number[0] if number else ""


def suffix_of(text: str | None) -> str:
    """The letters after a serial's number, which a published table can turn
    on: Colt's post-war Single Action Army is "…SA", a Python "…E" (2026-10-19)."""
    parts = _PARTS.fullmatch(text or "") if _number(text or "") else None
    return parts.group(3).upper() if parts else ""


# -- Storing it -----------------------------------------------------------------
def is_firearm(item: Any) -> bool:
    return bool(
        (getattr(item, "is_rifle", False) or getattr(item, "is_pistol", False))
        and not getattr(item, "is_parts_kit", False)
    )


def read(item: Any) -> None:
    """The listing's serial and stated year, from its words alone."""
    if not is_firearm(item):
        item.serial = item.serial_low = item.serial_high = None
        item.made_from = item.made_to = item.made_source = item.made_quote = None
        return
    serial = read_serial(item.title or "", item.description)
    item.serial = serial.text[:32] if serial else None
    item.serial_low = serial.low if serial else None
    item.serial_high = serial.high if serial else None
    stated = read_stated_year(item.title or "", item.description)
    if stated:
        item.made_from, item.made_to = stated.year_from, stated.year_to
        item.made_source, item.made_quote = STATED, stated.quote
    else:
        item.made_from = item.made_to = item.made_source = item.made_quote = None


#: A copy of a gun, whose serial is its own maker's and not the original's: a
#: Uberti Single Action Army numbered in Colt's 1890s range is not an 1890s
#: Colt (production, 2026-10-19). The makers are the ones that reproduce the
#: designs the tables cover.
_REPRODUCTION = re.compile(
    r"\b(?:replica|reproduction|repro|non-?firing|miniature|scale\s+model|uberti|pietta|"
    r"cimarron|miroku|chiappa|armi\s+san\s+marco|taylor'?s\s*(?:&|and)\s*co|navy\s+arms|"
    r"hy\s+hunter|great\s+western|e\.?m\.?f\.?\b|american\s+western\s+arms|"
    r"standard\s+manufacturing|rossi|puma)\b",
    re.I,
)


def _names(text: str, spelling: str) -> bool:
    """Whether *text* names *spelling*: whole words, with a space and a
    hyphen alike -- "SMITH CORONA" names Smith-Corona, "REMINGTON-UMC"
    names Remington."""
    words = [re.escape(word) for word in re.split(r"[\s-]+", spelling.strip()) if word]
    if not words:
        return False
    return bool(re.search(r"(?<!\w)" + r"[\s-]*".join(words) + r"(?!\w)", text, re.I))


def _spellings(session: Any, maker: str) -> list[str]:
    """Every spelling of the armory's maker of this name, or just the name."""
    from sqlalchemy import func, select

    from ..models import Manufacturer

    cache: dict[str, list[str]] = session.info.setdefault("serials_maker_spellings", {})
    if maker not in cache:
        row = session.execute(
            select(Manufacturer).where(func.lower(Manufacturer.name) == maker.lower())
        ).scalar_one_or_none()
        cache[maker] = row.spellings if row is not None else [maker]
    return cache[maker]


def _text(item: Any) -> str:
    return f"{item.title or ''}\n{item.description or ''}"


def datable(session: Any, item: Any) -> bool:
    """Whether a serial may date this listing at all, by a table or among
    other listings: not a reproduction (:data:`_REPRODUCTION`), and a maker,
    if it has one, that the listing names in its own words (2026-10-19)."""
    text = _text(item)
    if _REPRODUCTION.search(text):
        return False
    return not item.manufacturer or any(
        _names(text, name) for name in _spellings(session, item.manufacturer)
    )


def from_table(session: Any, item: Any) -> tuple[int, int, str] | None:
    """The years a published table gives the listing's serial, and a note
    naming the range and its source; None where no range of the model's, for
    its maker, holds the whole serial.

    Only for a listing that names the range's maker in its own words: a maker
    read from anything else ("Colt" out of a ".45 Colt" caliber, "Winchester"
    for a Krag matched to the Model 1892) dated the wrong guns.

    A range with no maker is the model's whatever the maker. A partly hidden
    serial must fall wholly inside a range; two ranges that both hold it
    (tables that overlap) are taken together if they agree to within
    :data:`MAX_SPAN` years.
    """
    if item.firearm_model_id is None or item.serial_low is None:
        return None
    from urllib.parse import urlparse

    from sqlalchemy import select

    from ..models import SerialRange

    text = _text(item)
    maker = _maker(item.manufacturer)
    hits = [
        row
        for row in session.execute(
            select(SerialRange).where(
                SerialRange.model_id == item.firearm_model_id,
                SerialRange.prefix == prefix_of(item.serial),
                SerialRange.suffix == suffix_of(item.serial),
                SerialRange.serial_low <= item.serial_low,
                SerialRange.serial_high >= item.serial_high,
            )
        ).scalars()
        if row.manufacturer is None
        or (
            maker
            and maker in {_maker(name) for name in row.manufacturer.spellings}
            and any(_names(text, name) for name in row.manufacturer.spellings)
        )
    ]
    if not hits:
        return None
    year_from = min(row.year_from for row in hits)
    year_to = max(row.year_to for row in hits)
    if year_to - year_from > MAX_SPAN:
        return None
    first = min(hits, key=lambda row: row.serial_low)
    whose = f"{first.manufacturer.name}'s " if first.manufacturer else ""
    where = urlparse(first.source).netloc.removeprefix("www.") or first.source
    low = f"{first.prefix}{first.serial_low:,}{first.suffix}"
    high = f"{first.prefix}{first.serial_high:,}{first.suffix}"
    note = (
        f"in {whose}{low} to {high}, "
        f"made {_span(first.year_from, first.year_to)}, as {where} publishes"
    )
    return year_from, year_to, note


def estimate(session: Any, item: Any, *, tables: bool = True) -> None:
    """Date a serial with no stated year: by a published table, or else among
    the listings that state one. ``tables`` is False only for migration 0077,
    which runs before 0081 has made the table of them."""
    if item.made_source == STATED or item.serial_low is None:
        return
    if not datable(session, item):
        item.made_from = item.made_to = item.made_source = item.made_quote = None
        return
    found = from_table(session, item) if tables else None
    source = TABLE
    if found is None:
        found = place(
            Serial(
                item.serial or "", item.serial_low, item.serial_high, "", prefix_of(item.serial)
            ),
            evidence_for(session, item.firearm_model_id, item.manufacturer),
        )
        source = SERIAL
    if found:
        item.made_from, item.made_to, note = found
        item.made_source, item.made_quote = source, note[:200]
    else:
        item.made_from = item.made_to = item.made_source = item.made_quote = None


def apply(session: Any, item: Any) -> None:
    """Read one listing's serial and year, and place the serial if it must."""
    read(item)
    estimate(session, item)


def backfill(session: Any, *, tables: bool = True) -> dict[str, int]:
    """Read every stored gun, then place every serial with no stated year.

    Two passes because the second leans on the first: a serial is placed among
    the listings that state their year, every one of which has to be read
    before any is placed. Migration 0077 and Site settings' re-read share it.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import load_only

    from ..models import Item

    counts = {"examined": 0, "serial": 0, "stated": 0, "table": 0, "placed": 0}
    # Only the columns read and written, for the reason frames.backfill
    # gives: migration 0077 runs this, and later columns must not break it.
    guns = (
        select(Item)
        .where((Item.is_rifle.is_(True)) | (Item.is_pistol.is_(True)), Item.is_parts_kit.is_(False))
        .options(
            load_only(
                Item.id,
                Item.title,
                Item.description,
                Item.manufacturer,
                Item.firearm_model_id,
                Item.is_rifle,
                Item.is_pistol,
                Item.is_parts_kit,
                Item.serial,
                Item.serial_low,
                Item.serial_high,
                Item.made_from,
                Item.made_to,
                Item.made_source,
                Item.made_quote,
            )
        )
    )
    for item in session.execute(guns).scalars():
        counts["examined"] += 1
        read(item)
        counts["serial"] += item.serial is not None
        counts["stated"] += item.made_source == STATED
    session.flush()
    waiting = guns.where(Item.serial_low.is_not(None), Item.made_source.is_(None))
    for item in session.execute(waiting).scalars():
        estimate(session, item, tables=tables)
        counts["table"] += item.made_source == TABLE
        counts["placed"] += item.made_source == SERIAL
    session.flush()
    return counts
