"""The canonical list of models, calibers and who made what.

Everything else in this application reads a listing and *guesses*. This module
is the opposite: a table of things somebody who knows the trade has stated, and
which the guesses defer to.

Two jobs, and the second is the reason for the first.

**Saying the same cartridge once.** A dealer writes ".32 ACP" and another
writes "7.65mm Browning"; one writes ".30-06" and another "7.62x63mm". Those
are the same round, and until they are one row a filter on either shows half
the listings. :func:`canonical_caliber` maps any spelling to the one this
application uses.

**Filling in what a listing does not say.** "RUSSIAN M44 CARBINES" names no
maker and no cartridge, and is a Mosin-Nagant in 7.62x54R. Matching the model
supplies both, and also what kind of gun it is -- which is the only way to tell
a flintlock pistol from a percussion revolver, both of which the browse filter
calls a handgun and neither of which the title has to spell out.

Nothing here invents anything. A name that nothing in the table explains is
written down *once* as a pending row for an admin to rule on, and a pending row
takes no part in matching until they do. That is the whole of the discovery
mechanism: the question gets asked once and then waits somewhere it can be
answered, rather than being asked on every scan and answered by nobody.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from ..models import (
    ArmoryStatus,
    Caliber,
    FirearmKind,
    FirearmModel,
    Item,
    Manufacturer,
    firearm_model_manufacturers,
)
from . import manufacturers

#: How many listing titles to keep on a pending row. Enough to judge it by,
#: and not so many that the column becomes a log.
MAX_SIGHTINGS = 5


@dataclass(frozen=True)
class Match:
    """What the table was able to say about a listing."""

    model: str | None = None
    kind: FirearmKind | None = None
    caliber: str | None = None
    manufacturer: str | None = None

    def __bool__(self) -> bool:
        return any((self.model, self.kind, self.caliber, self.manufacturer))


# ---------------------------------------------------------------------------
# Calibers
# ---------------------------------------------------------------------------
class CaliberRegistry:
    """Every spelling of every cartridge, longest first.

    Longest first matters more here than anywhere else in the application.
    "7.62x54R" contains "7.62", "9x19mm" contains "9x19", and ".30-06
    Springfield" contains ".30-06" -- and every one of those shorter strings is
    also a real spelling of something. Trying the longest first is what stops
    "7.62x54R" being read as a bare "7.62".
    """

    def __init__(self, rules: list[tuple[str, re.Pattern[str]]]) -> None:
        self.rules = rules

    def __len__(self) -> int:
        return len(self.rules)

    def canonical(self, text: str | None) -> str | None:
        if not text:
            return None
        for name, pattern in self.rules:
            if pattern.search(text):
                return name
        return None


def _caliber_rules(session: Session) -> list[tuple[str, re.Pattern[str]]]:
    rows = (
        session.execute(
            select(Caliber).where(Caliber.status == ArmoryStatus.APPROVED).order_by(Caliber.name)
        )
        .scalars()
        .all()
    )
    # Sorted by the longest spelling each row has, so a row whose *name* is
    # short but which owns a long alias is still tried before a row that only
    # has short ones.
    ordered = sorted(rows, key=lambda row: max((len(s) for s in row.spellings), default=0))
    return [(row.name, manufacturers.pattern_for(row.spellings)) for row in reversed(ordered)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ModelRegistry:
    """The model rules, in the order the admin put them in."""

    def __init__(self, rules: list[tuple[re.Pattern[str], Match]]) -> None:
        self.rules = rules

    def __len__(self) -> int:
        return len(self.rules)

    def match(self, title: str, description: str | None = None) -> Match:
        """The model named in a listing, preferring the title.

        The title is where a vendor says what they are selling; the
        description is where they talk about it, and on a flyer read by OCR it
        carries whatever the neighboring panel said. Same reasoning as
        :meth:`manufacturers.Registry.extract_from`, and the same order.
        """
        for pattern, found in self.rules:
            if pattern.search(title or ""):
                return found
        if description:
            for pattern, found in self.rules:
                if pattern.search(f"{title or ''} {description}"):
                    return found
        return Match()


def _facts_known(row: FirearmModel) -> int:
    """How much this row can tell a caller, for breaking ties between rows."""
    return sum(1 for fact in (row.kind, row.calibers, row.wikipedia_url, row.manufacturers) if fact)


def _model_rules(session: Session) -> list[tuple[re.Pattern[str], Match]]:
    rows = (
        session.execute(
            select(FirearmModel)
            .options(selectinload(FirearmModel.manufacturers), selectinload(FirearmModel.calibers))
            .where(
                FirearmModel.enabled.is_(True),
                FirearmModel.status == ArmoryStatus.APPROVED,
            )
            .order_by(FirearmModel.position, FirearmModel.id)
        )
        .scalars()
        .all()
    )
    # Between two rows that both match, the one that can say more wins.
    #
    # "RUSSIAN M44 CARBINES" matches a bare "M44" carried over from the old
    # one-maker-per-model table and also "Mosin-Nagant M44", which knows it is
    # a carbine in 7.62x54R. Returning the first because its id is lower is an
    # accident of history, and the answer is strictly worse. Position still
    # decides first, so an admin who wants a particular order still gets it.
    rows = sorted(rows, key=lambda row: (row.position, -_facts_known(row), row.id))
    return [
        (
            manufacturers.pattern_for(row.spellings),
            Match(
                model=row.name,
                kind=row.kind,
                # Only when there is exactly one and so no choice to make. An
                # M95 may be 8x50mmR or 8x56mmR, and the model does not say
                # which this one is -- see FirearmModel.only_caliber.
                caliber=row.only_caliber,
                # Only when the answer is not a choice. Nine firms built the
                # M1 Carbine, and a title naming none of them does not tell us
                # which -- so the model says nothing about the maker rather
                # than picking one. With a single maker on the row there is
                # nothing to pick and the fact is simply true.
                manufacturer=(row.manufacturers[0].name if len(row.manufacturers) == 1 else None),
            ),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
# Compiling every rule for every listing of a two-hundred-listing scan is
# wasted work, so both registries are built once and dropped when the tables
# change. Any writer outside this module must call invalidate().
_lock = threading.Lock()
_calibers: CaliberRegistry | None = None
_models: ModelRegistry | None = None


def invalidate() -> None:
    """Forget the compiled rules; the next read rebuilds them.

    The maker registry goes with them, and must. Its rules are built partly
    from this table now -- a model with exactly one maker names that maker --
    so promoting a model, editing its makers, or approving a firm all change
    what the maker matcher will say. Leaving that cache alone meant promoting
    "Inland" and then finding that "Inland M1 Carbine" still had no maker,
    with nothing on screen to explain it.
    """
    global _calibers, _models
    with _lock:
        _calibers = None
        _models = None
    manufacturers.invalidate()


def caliber_registry(session: Session) -> CaliberRegistry:
    global _calibers
    with _lock:
        if _calibers is None:
            _calibers = CaliberRegistry(_caliber_rules(session))
        return _calibers


def model_registry(session: Session) -> ModelRegistry:
    global _models
    with _lock:
        if _models is None:
            _models = ModelRegistry(_model_rules(session))
        return _models


# ---------------------------------------------------------------------------
# What the rest of the application asks
# ---------------------------------------------------------------------------
def canonical_caliber(session: Session, text: str | None) -> str | None:
    """The spelling this application uses for whatever cartridge that names.

    Returns None when nothing in the table recognizes it, which is not the
    same as "there is no cartridge here" -- it means nobody has told us about
    this one yet. Callers keep what they had.
    """
    return caliber_registry(session).canonical(text)


def match(session: Session, title: str, description: str | None = None) -> Match:
    """Everything the table can say about this listing."""
    return model_registry(session).match(title, description)


def fill_in(
    session: Session,
    title: str,
    description: str | None = None,
    caliber: str | None = None,
) -> Match:
    """The model's facts, with the listing's own caliber normalized and kept.

    The listing wins on caliber when it has one. A model's caliber is what it
    left the factory with, and sixty years of surplus is full of guns that were
    rebarreled, rechambered or sold as something else -- so the table fills a
    blank and never overrules a dealer who has the thing in their hand.

    It does get normalized either way. That is not overruling anybody: ".32
    ACP" and "7.65mm Browning" are the same answer written twice, and the
    filter can only offer one of them.
    """
    found = match(session, title, description)
    stated = canonical_caliber(session, caliber) or (caliber.strip() if caliber else None)
    return Match(
        model=found.model,
        kind=found.kind,
        caliber=stated or found.caliber,
        manufacturer=found.manufacturer,
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _note_sighting(existing: str | None, title: str) -> str:
    """Add a title to the handful kept on a pending row, without repeats."""
    seen = [line for line in (existing or "").splitlines() if line.strip()]
    if title in seen:
        return "\n".join(seen)
    return "\n".join([*seen, title][-MAX_SIGHTINGS:])


def propose_caliber(session: Session, name: str, seen_in: str = "") -> Caliber | None:
    """Write down a cartridge spelling nothing in the table explains.

    Returns the pending row, or None when the table already knows this one --
    including when it knows it under a different name, which is the case that
    matters: a scan meeting "7.65mm Browning" for the hundredth time should not
    keep proposing it just because the canonical row is called ".32 ACP".
    """
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return None
    if canonical_caliber(session, cleaned):
        return None

    row = session.execute(
        select(Caliber).where(func.lower(Caliber.name) == cleaned.lower())
    ).scalar_one_or_none()
    if row is None:
        row = Caliber(name=cleaned, status=ArmoryStatus.PENDING, first_seen_in=seen_in or None)
        session.add(row)
        invalidate()
    elif seen_in and row.status == ArmoryStatus.PENDING:
        row.first_seen_in = _note_sighting(row.first_seen_in, seen_in)
    return row


def propose_model(session: Session, name: str, seen_in: str = "") -> FirearmModel | None:
    """Write down a model designation nothing in the table explains."""
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return None
    if match(session, cleaned).model:
        return None

    row = session.execute(
        select(FirearmModel).where(func.lower(FirearmModel.name) == cleaned.lower())
    ).scalar_one_or_none()
    if row is None:
        row = FirearmModel(name=cleaned, status=ArmoryStatus.PENDING, first_seen_in=seen_in or None)
        session.add(row)
        invalidate()
    elif seen_in and row.status == ArmoryStatus.PENDING:
        row.first_seen_in = _note_sighting(row.first_seen_in, seen_in)
    return row


#: The three tables that hold reference data an admin curates. Named once so
#: the pending count, the promote action and the API all agree on the list.
#:
#: Typed loosely on purpose: these are ORM classes chosen by name at runtime
#: from a fixed set, and the three share the shape this module uses -- an
#: ``id``, a ``name`` and a ``status`` -- without sharing a base class that
#: says so. A union here only moves the casts to every call site.
CURATED: dict[str, Any] = {
    "models": FirearmModel,
    "calibers": Caliber,
    "manufacturers": Manufacturer,
}


def pending_counts(session: Session) -> dict[str, int]:
    """How many rows of each kind are waiting on somebody, for the nav badge."""
    return {
        name: int(
            session.execute(
                select(func.count(table.id)).where(table.status == ArmoryStatus.PENDING)
            ).scalar_one()
        )
        for name, table in CURATED.items()
    }


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------
def promote(session: Session, table: str, ids: Iterable[int]) -> int:
    """Move rows from awaiting-approval into production. Returns how many.

    The one gate between a name somebody typed -- or a scan guessed -- and a
    table the application treats as true. Everything on the pending side is
    inert: it fills in no caliber, decides no kind, and answers no filter. It
    exists so an admin can look at it and say yes.

    Deliberately not the reverse of anything. Sending a row back to pending is
    a separate action with a separate button, because "I have checked this"
    and "I no longer trust this" are different statements and collapsing them
    into a toggle invites the second by accident.
    """
    model = CURATED[table]
    rows = session.execute(select(model).where(model.id.in_(list(ids)))).scalars().all()
    moved = 0
    for row in rows:
        if row.status == ArmoryStatus.PENDING:
            row.status = ArmoryStatus.APPROVED
            moved += 1
    if moved:
        invalidate()
    return moved


def send_back(session: Session, table: str, ids: Iterable[int]) -> int:
    """Return production rows to awaiting-approval, and stop them deciding."""
    model = CURATED[table]
    rows = session.execute(select(model).where(model.id.in_(list(ids)))).scalars().all()
    moved = 0
    for row in rows:
        if row.status == ArmoryStatus.APPROVED:
            row.status = ArmoryStatus.PENDING
            moved += 1
    if moved:
        invalidate()
    return moved


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
#: The starting armory, versioned in the repository beside the code.
SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "armory.yaml"


@dataclass
class SeedReport:
    manufacturers: int = 0
    calibers: int = 0
    models: int = 0
    links: int = 0

    @property
    def total(self) -> int:
        return self.manufacturers + self.calibers + self.models


def _lines(values: Iterable[object] | None) -> str | None:
    """A list from the seed file as the one-per-line text the columns hold."""
    return "\n".join(str(value) for value in values or []) or None


def seed(session: Session, path: Path | None = None) -> SeedReport:
    """Add what the seed file has and the database does not.

    Additive, and only additive, matching on the name. A row already present
    is left exactly as it is -- edits, approvals, notes and all -- whatever the
    file now says. That makes this safe to run on every deploy, which is the
    point: it is how a later release's additions reach an installation that is
    already running, and how the armory reaches every new instance.

    One consequence to know about: a row *deleted* from the database comes back
    as pending on the next seed, because "missing" and "deleted" look the same
    from here. Deleting is therefore not how a row gets rejected. Leaving it
    pending, or turning ``enabled`` off, both keep it out of matching and both
    survive a re-seed. Honoring a deletion would need a tombstone table, which
    is a lot of machinery for a case an existing state already covers.

    Everything arrives *pending*. Nothing in the file has been checked by the
    person who runs the site, so nothing in it decides anything until they
    promote it.
    """
    data = yaml.safe_load((path or SEED_FILE).read_text(encoding="utf-8")) or {}
    report = SeedReport()

    calibers: dict[str, Caliber] = {
        found.name.lower(): found for found in session.execute(select(Caliber)).scalars()
    }
    for entry in data.get("calibers") or []:
        name = str(entry["name"]).strip()
        if name.lower() in calibers:
            continue
        cartridge = Caliber(
            name=name,
            aliases=_lines(entry.get("aliases")),
            status=ArmoryStatus.PENDING,
        )
        session.add(cartridge)
        calibers[name.lower()] = cartridge
        report.calibers += 1

    makers: dict[str, Manufacturer] = {
        found.name.lower(): found for found in session.execute(select(Manufacturer)).scalars()
    }
    for entry in data.get("manufacturers") or []:
        name = str(entry["name"]).strip()
        if name.lower() in makers:
            continue
        firm = Manufacturer(
            name=name,
            aliases=_lines(entry.get("aliases")),
            status=ArmoryStatus.PENDING,
            position=int(entry.get("position") or 1000),
        )
        session.add(firm)
        makers[name.lower()] = firm
        report.manufacturers += 1

    seen = {name.lower() for name in session.execute(select(FirearmModel.name)).scalars()}
    for entry in data.get("models") or []:
        name = str(entry["name"]).strip()
        if name.lower() in seen:
            continue
        kind = entry.get("kind")
        gun = FirearmModel(
            name=name,
            aliases=_lines(entry.get("aliases")),
            kind=FirearmKind(kind) if kind else None,
            wikipedia_url=entry.get("wikipedia"),
            status=ArmoryStatus.PENDING,
        )
        gun.calibers = [
            calibers[name.strip().lower()]
            for name in _caliber_list(entry)
            if name.strip().lower() in calibers
        ]
        for maker_name in entry.get("manufacturers") or []:
            key = str(maker_name).strip().lower()
            maker = makers.get(key)
            if maker is None:
                # A maker named on a model but nowhere in the file's own
                # manufacturers list. Created rather than dropped, because a
                # model losing half its makers silently is worse than a row an
                # admin has to look at -- and it arrives pending like
                # everything else, so it decides nothing until they do.
                maker = Manufacturer(name=str(maker_name).strip(), status=ArmoryStatus.PENDING)
                session.add(maker)
                makers[key] = maker
                report.manufacturers += 1
            gun.manufacturers.append(maker)
        session.add(gun)
        seen.add(name.lower())
        report.models += 1
        if gun.wikipedia_url:
            report.links += 1

    if report.total:
        invalidate()
    return report


# ---------------------------------------------------------------------------
# The round trip: database to flat file and back
# ---------------------------------------------------------------------------
# Two directions, and they are not symmetric.
#
# `export` writes what the database holds, in a stable order, into the same
# shape the seed file uses -- so a curated armory can be committed, reviewed
# as a diff, and carried to another instance. Statuses go with it: a row this
# admin has promoted is a row the next instance should get as production, and
# dropping that on the way out would make every export a demotion.
#
# `sync` reads such a file and reconciles the database with it: adding what is
# missing, correcting what differs, and -- only when explicitly asked --
# removing what the file no longer lists. It is the destructive counterpart to
# `seed`, which is why it plans first and applies second. Nobody should learn
# what a sync was going to delete by reading the result.
_EXPORT_HEADER = """\
# Exported catalog -- models, calibers, and who made what.
#
# Written by `milsurp catalog export`. Safe to commit: the order is stable, so
# a diff shows what actually changed rather than how the rows happened to come
# back from the database.
#
# `milsurp catalog sync --file <this>` reconciles a database with it. That
# reads statuses, so a row promoted to production here arrives as production
# there. Rows in the database and not in this file are left alone unless
# --prune is given.
"""


def export_armory(session: Session) -> dict[str, Any]:
    """The catalog as plain data, ordered so that diffs mean something."""
    calibers = session.execute(select(Caliber).order_by(func.lower(Caliber.name))).scalars().all()
    models = (
        session.execute(
            select(FirearmModel)
            .options(selectinload(FirearmModel.manufacturers), selectinload(FirearmModel.calibers))
            .order_by(func.lower(FirearmModel.name))
        )
        .scalars()
        .all()
    )
    return {
        "calibers": [
            _without_blanks(
                {
                    "name": row.name,
                    "aliases": row.spellings[1:],
                    "status": row.status.value,
                    "notes": row.notes,
                }
            )
            for row in calibers
        ],
        "models": [
            _without_blanks(
                {
                    "name": row.name,
                    "aliases": row.spellings[1:],
                    "kind": row.kind.value if row.kind else None,
                    "calibers": sorted(row.caliber_names),
                    "manufacturers": sorted(row.manufacturer_names),
                    "wikipedia": row.wikipedia_url,
                    "status": row.status.value,
                    "position": row.position if row.position != 1000 else None,
                    "enabled": None if row.enabled else False,
                    "notes": row.notes,
                }
            )
            for row in models
        ],
    }


def write_export(session: Session, path: Path) -> int:
    """Write the catalog to *path*. Returns how many rows were written."""
    data = export_armory(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(_EXPORT_HEADER + "\n" + body, encoding="utf-8")
    return len(data["calibers"]) + len(data["models"])


def _without_blanks(row: dict[str, Any]) -> dict[str, Any]:
    """Drop the keys with nothing in them, so the file stays readable."""
    return {key: value for key, value in row.items() if value not in (None, "", [], {})}


@dataclass
class Change:
    """One difference between the file and the database."""

    name: str
    action: str  # "add" | "update" | "delete"
    #: Which fields differ, for an update. The whole point of showing a plan.
    fields: list[str] = field(default_factory=list)


@dataclass
class SyncPlan:
    calibers: list[Change] = field(default_factory=list)
    models: list[Change] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.calibers or self.models)

    def counted(self) -> dict[str, int]:
        every = [*self.calibers, *self.models]
        return {
            action: sum(1 for change in every if change.action == action)
            for action in ("add", "update", "delete")
        }


def plan_sync(session: Session, path: Path) -> SyncPlan:
    """What :func:`apply_sync` would do, without doing any of it."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    plan = SyncPlan()

    cartridges = {str(e["name"]).strip().lower(): e for e in data.get("calibers") or []}
    for cartridge in session.execute(select(Caliber)).scalars():
        entry = cartridges.pop(cartridge.name.strip().lower(), None)
        if entry is None:
            plan.calibers.append(Change(cartridge.name, "delete"))
        elif differing := _caliber_differences(cartridge, entry):
            plan.calibers.append(Change(cartridge.name, "update", differing))
    plan.calibers.extend(Change(str(e["name"]), "add") for e in cartridges.values())

    guns = {str(e["name"]).strip().lower(): e for e in data.get("models") or []}
    for gun in session.execute(
        select(FirearmModel).options(
            selectinload(FirearmModel.manufacturers), selectinload(FirearmModel.calibers)
        )
    ).scalars():
        entry = guns.pop(gun.name.strip().lower(), None)
        if entry is None:
            plan.models.append(Change(gun.name, "delete"))
        elif differing := _model_differences(gun, entry):
            plan.models.append(Change(gun.name, "update", differing))
    plan.models.extend(Change(str(e["name"]), "add") for e in guns.values())

    plan.calibers.sort(key=lambda c: (c.action, c.name.lower()))
    plan.models.sort(key=lambda c: (c.action, c.name.lower()))
    return plan


def _caliber_differences(row: Caliber, entry: dict[str, Any]) -> list[str]:
    return _differences(
        {
            "aliases": row.spellings[1:],
            "status": row.status.value,
            "notes": row.notes,
        },
        {
            "aliases": [str(a) for a in entry.get("aliases") or []],
            "status": str(entry.get("status") or ArmoryStatus.PENDING.value),
            "notes": entry.get("notes"),
        },
    )


def _model_differences(row: FirearmModel, entry: dict[str, Any]) -> list[str]:
    return _differences(
        {
            "aliases": row.spellings[1:],
            "kind": row.kind.value if row.kind else None,
            "calibers": sorted(row.caliber_names),
            "manufacturers": sorted(row.manufacturer_names),
            "wikipedia": row.wikipedia_url,
            "status": row.status.value,
            "position": row.position,
            "enabled": row.enabled,
            "notes": row.notes,
        },
        {
            "aliases": [str(a) for a in entry.get("aliases") or []],
            "kind": entry.get("kind"),
            "calibers": sorted(_caliber_list(entry)),
            "manufacturers": sorted(str(m) for m in entry.get("manufacturers") or []),
            "wikipedia": entry.get("wikipedia"),
            "status": str(entry.get("status") or ArmoryStatus.PENDING.value),
            "position": int(entry.get("position") or 1000),
            "enabled": bool(entry.get("enabled", True)),
            "notes": entry.get("notes"),
        },
    )


def _caliber_list(entry: dict[str, Any]) -> list[str]:
    """The cartridges an entry names, however it names them.

    ``calibers:`` is the form this writes; ``caliber:`` is accepted because a
    model with one is the common case and a human editing the file by hand
    will write the singular without thinking about it.
    """
    values = entry.get("calibers")
    if values is None:
        single = entry.get("caliber")
        values = [single] if single else []
    return [str(value) for value in values]


def _differences(have: dict[str, Any], want: dict[str, Any]) -> list[str]:
    return sorted(key for key, value in want.items() if have.get(key) != value)


def apply_sync(session: Session, path: Path, prune: bool = False) -> dict[str, int]:
    """Reconcile the database with the file. Returns what it did.

    Deletions happen only when *prune* is set, and only for rows the file does
    not mention. An armory is curated in two places -- the file, and whatever
    instance is running -- and quietly deleting an admin's row because it has
    not been exported yet is the one mistake this must not make.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    done = {"added": 0, "updated": 0, "deleted": 0}
    calibers = _sync_calibers(session, data.get("calibers") or [], done, prune)
    _sync_models(session, data.get("models") or [], calibers, done, prune)
    if any(done.values()):
        invalidate()
    return done


def _sync_calibers(
    session: Session, entries: list[dict[str, Any]], done: dict[str, int], prune: bool
) -> dict[str, Caliber]:
    known = {row.name.strip().lower(): row for row in session.execute(select(Caliber)).scalars()}
    listed: set[str] = set()
    for entry in entries:
        name = str(entry["name"]).strip()
        listed.add(name.lower())
        row = known.get(name.lower())
        if row is None:
            row = Caliber(name=name)
            session.add(row)
            known[name.lower()] = row
            done["added"] += 1
        elif _caliber_differences(row, entry):
            done["updated"] += 1
        else:
            continue
        row.aliases = _lines(entry.get("aliases"))
        row.status = ArmoryStatus(str(entry.get("status") or ArmoryStatus.PENDING.value))
        row.notes = entry.get("notes")

    if prune:
        for key, row in list(known.items()):
            if key not in listed:
                session.delete(row)
                known.pop(key)
                done["deleted"] += 1
    return known


def _sync_models(
    session: Session,
    entries: list[dict[str, Any]],
    calibers: dict[str, Caliber],
    done: dict[str, int],
    prune: bool,
) -> None:
    makers = {
        row.name.strip().lower(): row for row in session.execute(select(Manufacturer)).scalars()
    }
    known = {
        row.name.strip().lower(): row
        for row in session.execute(
            select(FirearmModel).options(
                selectinload(FirearmModel.manufacturers), selectinload(FirearmModel.calibers)
            )
        ).scalars()
    }
    listed: set[str] = set()
    for entry in entries:
        name = str(entry["name"]).strip()
        listed.add(name.lower())
        row = known.get(name.lower())
        if row is None:
            row = FirearmModel(name=name)
            session.add(row)
            known[name.lower()] = row
            done["added"] += 1
        elif _model_differences(row, entry):
            done["updated"] += 1
        else:
            continue
        _write_model(row, entry, calibers, makers)

    if prune:
        for key, row in list(known.items()):
            if key not in listed:
                session.delete(row)
                done["deleted"] += 1


def _write_model(
    row: FirearmModel,
    entry: dict[str, Any],
    calibers: dict[str, Caliber],
    makers: dict[str, Manufacturer],
) -> None:
    kind = entry.get("kind")
    row.aliases = _lines(entry.get("aliases"))
    row.kind = FirearmKind(str(kind)) if kind else None
    row.calibers = [
        calibers[name.strip().lower()]
        for name in _caliber_list(entry)
        if name.strip().lower() in calibers
    ]
    row.wikipedia_url = entry.get("wikipedia")
    row.status = ArmoryStatus(str(entry.get("status") or ArmoryStatus.PENDING.value))
    row.position = int(entry.get("position") or 1000)
    row.enabled = bool(entry.get("enabled", True))
    row.notes = entry.get("notes")
    # A maker named in the file but absent from the manufacturers table is
    # skipped rather than invented, for the same reason as in seed(): a
    # manufacturer row carries matching rules of its own.
    row.manufacturers = [
        makers[str(m).strip().lower()]
        for m in entry.get("manufacturers") or []
        if str(m).strip().lower() in makers
    ]


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------
class MergeError(ValueError):
    """A merge that would lose information or make no sense."""


def _restamp(session: Session, statement) -> int:
    """Run an UPDATE and report how many listings it touched."""
    return int(session.execute(statement).rowcount or 0)  # type: ignore[attr-defined]


def merge_manufacturers(session: Session, source_id: int, target_id: int) -> int:
    """Fold one maker into another: "Mosin" into "Mosin-Nagant".

    The source's spellings move to the target, so every listing the source used
    to catch is still caught -- by the right name. Its models move too, and any
    listing already stamped with the old name is restamped.

    The row itself stays, marked merged and pointing at the target. Deleting it
    would be tidier and worse: an admin who merges the wrong pair has no way
    back, and a row that says what became of it is the difference between an
    undo and an archaeology exercise.
    """
    source, target = _merge_pair(session, Manufacturer, source_id, target_id)

    target.aliases = _merged_aliases(target, source)
    for model in list(source.firearm_models):
        if model not in target.firearm_models:
            target.firearm_models.append(model)
    session.execute(
        delete(firearm_model_manufacturers).where(
            firearm_model_manufacturers.c.manufacturer_id == source.id
        )
    )
    restamped = _restamp(
        session,
        update(Item).where(Item.manufacturer == source.name).values(manufacturer=target.name),
    )

    source.status = ArmoryStatus.MERGED
    source.merged_into_id = target.id
    source.enabled = False
    invalidate()
    return restamped


def merge_calibers(session: Session, source_id: int, target_id: int) -> int:
    """Fold one cartridge into another: "7.65mm Browning" into ".32 ACP"."""
    source, target = _merge_pair(session, Caliber, source_id, target_id)

    target.aliases = _merged_aliases(target, source)
    # Every model that named the old cartridge names the new one instead,
    # without ending up naming both.
    for gun in session.execute(
        select(FirearmModel).options(selectinload(FirearmModel.calibers))
    ).scalars():
        if source in gun.calibers:
            gun.calibers.remove(source)
            if target not in gun.calibers:
                gun.calibers.append(target)
    restamped = _restamp(
        session, update(Item).where(Item.caliber == source.name).values(caliber=target.name)
    )

    source.status = ArmoryStatus.MERGED
    source.merged_into_id = target.id
    invalidate()
    return restamped


def merge_models(session: Session, source_id: int, target_id: int) -> int:
    """Fold one model into another: "M1 Garand Rifle" into "M1 Garand"."""
    source, target = _merge_pair(session, FirearmModel, source_id, target_id)

    target.aliases = _merged_aliases(target, source)
    for maker in list(source.manufacturers):
        if maker not in target.manufacturers:
            target.manufacturers.append(maker)
    # A blank on the target is worth filling from the source; a value on it is
    # not worth overwriting, because the target is the row being kept.
    if target.kind is None:
        target.kind = source.kind
    for cartridge in list(source.calibers):
        if cartridge not in target.calibers:
            target.calibers.append(cartridge)

    source.manufacturers.clear()
    source.calibers.clear()
    source.status = ArmoryStatus.MERGED
    source.merged_into_id = target.id
    source.enabled = False
    invalidate()
    return 0


def _merge_pair(session: Session, table, source_id: int, target_id: int):
    if source_id == target_id:
        raise MergeError("A row cannot be merged into itself.")
    source = session.get(table, source_id)
    target = session.get(table, target_id)
    if source is None or target is None:
        raise MergeError("Both rows must exist.")
    if target.status == ArmoryStatus.MERGED:
        raise MergeError(f"{target.name!r} has itself been merged away; pick the row it went into.")
    return source, target


def _merged_aliases(target, source) -> str | None:
    """The target's spellings plus the source's, canonical names included.

    The source's *name* is the important one: it is what a listing said, and
    dropping it would mean the merge quietly stopped recognizing the very text
    that prompted it.
    """
    keep: list[str] = []
    for spelling in [*target.spellings[1:], *source.spellings]:
        if spelling.lower() not in {
            *(item.lower() for item in keep),
            target.name.strip().lower(),
        }:
            keep.append(spelling)
    return "\n".join(keep) or None


# ---------------------------------------------------------------------------
# Applying the catalog to what is already stored
# ---------------------------------------------------------------------------
def restate(session: Session, items: Iterable[Item]) -> dict[str, int]:
    """Fill in blanks on stored listings from the table. Returns what changed.

    Only blanks, and only normalization. This never argues with a caliber a
    dealer stated -- see :func:`fill_in` -- so running it is safe at any time
    and running it twice does nothing the second time.
    """
    changed = {"caliber": 0, "manufacturer": 0, "model": 0}
    for item in items:
        found = fill_in(session, item.title, item.description, item.caliber)
        if found.caliber and found.caliber != item.caliber:
            item.caliber = found.caliber
            changed["caliber"] += 1
        if found.manufacturer and not item.manufacturer:
            item.manufacturer = found.manufacturer
            changed["manufacturer"] += 1
        if found.model:
            changed["model"] += 1
    return changed
