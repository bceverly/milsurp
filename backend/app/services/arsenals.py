"""Which arsenal made this gun, read from its listing and settled by its model.

A collector's price often turns on the factory more than the model: an
International Harvester Garand against a Springfield, a Rock-Ola carbine
against an Inland, a Tula hex-receiver Mosin, a ``bcd`` K98k. Measured on
production 2026-10-04, the listings name it far more often than the catalog
recorded it: 95% of Garands, 93% of carbines, 92% of 1903s, 70% of Mosins and
59% of K98ks name an arsenal somewhere in their text. The maker field said
"Mosin-Nagant" on every one of 65 M91/30s.

**The armory already says which firms made which model** -- a model's
manufacturers *are* its arsenals -- and that list is what makes this safe. A
listing's arsenal is only ever looked for among the firms linked to the model
it matched, so a mark that would mean nothing on its own can be read where it
means something: ``SA`` on a Garand is Springfield Armory, ``SG`` on a carbine
is Saginaw, ``byf`` on a K98k is Mauser Oberndorf. Those marks live on the
maker (``Manufacturer.marks``) and are never matched anywhere else.

**When several are named, the most specific wins**, in this order:

1. the title over the description, always. The title is where a dealer says
   what the gun is; a description names the makers of its *parts* ("an
   Underwood dated 11-42 barrel" on a carbine) and quotes disclaimers ("any
   Rock Island Arsenal M1903 below 285,508" on a Springfield). Measured
   against production before this order was settled: description-first sent
   nine Springfield 1903s to Rock Island on the strength of a disclaimer;
2. within one, a firm whose name is not part of the model's own name --
   "Lee Enfield No.4 ... by Savage-Stevens" is a Savage, because "Enfield"
   there is the pattern's name;
3. a *mark* over a name -- "Mauser K98k bcd 43" is a Gustloff;
4. the earlier mention;
5. the longer one, so "Remington Rand" is not read as "Remington".

Two things a mention can be that are not an attribution, both found in
production's listings while this was written, are not counted:

* **a part.** "vlb ZF-41 scope & duv mount" names the maker of the mount; a
  mention followed by a word like *mount*, *scope*, *barrel* or *bolt* is
  passed over;
* **a list.** "(e.g., Mauser Oberndorf, Steyr, or Waffenwerke Brünn)" in a
  Yugoslav rework's description named three factories and attributed none. A
  description naming two or more of the model's factories -- not counting
  the pattern's own name -- is a list, a comparison or an inventory of
  parts, and is not read at all.

A firm that is only ever a design's name -- "Mosin-Nagant", "Arisaka",
"Carcano" -- is not linked to the models as an arsenal at all, so that "Mosin
Nagant M91/30" in a title cannot stand in the way of "Izhevsk" below it.
Springfield, Mauser and Enfield are real factories as well as names and stay.

**It never argues with a person.** It replaces a maker the rules or the armory
supplied (``derived``, ``catalog``), never one the vendor published, a person
corrected, or one whose origin is unknown -- see app/services/provenance.py.
Only approved, enabled models and makers take part, as everywhere in the
armory.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import ArmoryStatus, FirearmModel, Item
from . import provenance


@dataclass(frozen=True)
class _Firm:
    name: str
    #: The firm's name and aliases: matched ignoring case.
    names: re.Pattern[str] | None
    #: Its marks: matched ignoring case too, but only ever here.
    marks: re.Pattern[str] | None
    #: Whether one of its spellings is inside the model's own spellings --
    #: "Mosin-Nagant" inside "Mosin Nagant M91/30" -- so a mention of it may be
    #: the pattern's name rather than the factory's.
    in_model_name: bool


_lock = threading.Lock()
_cached: dict[int, list[_Firm]] | None = None


def forget() -> None:
    """Drop the compiled table. Called whenever the armory or the makers change."""
    global _cached
    with _lock:
        _cached = None


def _pattern(spellings: list[str], dated: bool = False) -> re.Pattern[str] | None:
    """Whole words only, longest first, and ``/`` counted as part of a word, so
    ``S/42`` is one mark and ``42`` inside it is not.

    ``dated`` lets a mark run straight into a two-digit year, as dealers write
    them: "Walther P38 AC40", "Mauser K98 BYF45" -- 19 production titles on
    2026-10-04. Exactly two digits, so a serial ("SG3276", "SA1168") is not a
    mark.
    """
    words = sorted({s.strip() for s in spellings if s and s.strip()}, key=len, reverse=True)
    if not words:
        return None
    body = "|".join(re.escape(word) for word in words)
    year = r"(?:\d\d(?![\w/]))|" if dated else ""
    return re.compile(rf"(?<![\w/])(?:{body})(?={year}(?![\w/]))", re.IGNORECASE)


def _lines(text: str | None) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _table(session: Session) -> dict[int, list[_Firm]]:
    global _cached
    with _lock:
        if _cached is not None:
            return _cached
    found: dict[int, list[_Firm]] = {}
    models = session.execute(
        select(FirearmModel)
        .options(selectinload(FirearmModel.manufacturers))
        .where(FirearmModel.status == ArmoryStatus.APPROVED, FirearmModel.enabled.is_(True))
    ).scalars()
    for model in models:
        own = " | ".join(model.spellings).lower()
        firms = []
        for maker in model.manufacturers:
            if maker.status != ArmoryStatus.APPROVED or not maker.enabled:
                continue
            spellings = maker.spellings
            firms.append(
                _Firm(
                    name=maker.name,
                    names=_pattern(spellings),
                    marks=_pattern(_lines(maker.marks), dated=True),
                    in_model_name=any(
                        re.search(rf"(?<!\w){re.escape(s.lower())}(?!\w)", own)
                        for s in spellings
                        if s.strip()
                    ),
                )
            )
        # One firm is not a choice: fill_in already names it from the model.
        if len(firms) > 1:
            found[model.id] = firms
    with _lock:
        _cached = found
    return found


#: A mention followed by one of these names a part, not the gun: "duv mount".
_PARTS = frozenset(
    {
        "mount",
        "mounts",
        "scope",
        "scopes",
        "sling",
        "slings",
        "bayonet",
        "bayonets",
        "barrel",
        "barrels",
        "bbl",
        "stock",
        "stocks",
        "bolt",
        "bolts",
        "magazine",
        "magazines",
        "mag",
        "mags",
        "sight",
        "sights",
        "rings",
        "base",
        "bases",
        "band",
        "bands",
        "trigger",
        "triggers",
        "handguard",
        "handguards",
        "parts",
        "part",
    }
)
_NEXT_WORD = re.compile(r"[\W_]*(\w+)")


def _first_attribution(pattern: re.Pattern[str] | None, text: str) -> re.Match[str] | None:
    """The first mention that is not followed by the name of a part."""
    if pattern is None:
        return None
    for hit in pattern.finditer(text):
        following = _NEXT_WORD.match(text, hit.end())
        if following and following.group(1).lower() in _PARTS:
            continue
        return hit
    return None


def arsenal_for(
    session: Session, model_id: int | None, title: str | None, description: str | None = None
) -> str | None:
    """The arsenal this listing names, among those of its model, or None."""
    if model_id is None:
        return None
    firms = _table(session).get(model_id)
    if not firms:
        return None
    best: tuple[int, int, int, int, int] | None = None
    winner: str | None = None
    for where, text in ((1, title or ""), (0, description or "")):
        if not text:
            continue
        hits = [
            (firm, by_mark, hit)
            for firm in firms
            for by_mark, pattern in ((1, firm.marks), (0, firm.names))
            if (hit := _first_attribution(pattern, text)) is not None
        ]
        if not where and len({f.name for f, _m, _h in hits if not f.in_model_name}) > 1:
            continue  # a list, not an attribution: see the module docstring
        for firm, by_mark, hit in hits:
            score = (
                where,
                0 if firm.in_model_name else 1,
                by_mark,
                -hit.start(),
                len(hit.group(0)),
            )
            if best is None or score > best:
                best, winner = score, firm.name
    return winner


#: The sources an arsenal may replace: the rules' guess and the armory's fill.
#: A vendor's own field, a person's correction and an unknown origin are kept.
REPLACEABLE = (provenance.DERIVED, provenance.CATALOG)


def apply(session: Session, item: Item, description: str | None = None) -> bool:
    """Set the listing's maker to the arsenal it names, where that is allowed.

    Returns whether anything changed. ``description`` is passed explicitly
    because the scan reads a vendor's prose only when it is trusted.
    """
    if item.firearm_model_id is None:
        return False
    if item.manufacturer and provenance.source_of(item, "manufacturer") not in REPLACEABLE:
        return False
    found = arsenal_for(session, item.firearm_model_id, item.title, description)
    if not found or found == item.manufacturer:
        return False
    provenance.claim(item, "manufacturer", found, provenance.CATALOG)
    return True


def backfill(session: Session, model_ids: list[int] | None = None) -> int:
    """Apply the arsenal step to every listing of these models (or of all).

    For an armory change that adds arsenals or marks to models whose listings
    were already filed. Returns how many listings changed.
    """
    table = _table(session)
    wanted = [m for m in (model_ids if model_ids is not None else list(table)) if m in table]
    if not wanted:
        return 0
    changed = 0
    for item in session.execute(select(Item).where(Item.firearm_model_id.in_(wanted))).scalars():
        if apply(session, item, item.description):
            changed += 1
    return changed
