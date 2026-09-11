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

import enum
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from sqlalchemy import and_, delete, func, or_, select, update
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
from . import classify, manufacturers

#: How many listing titles to keep on a pending row. Enough to judge it by,
#: and not so many that the column becomes a log.
MAX_SIGHTINGS = 5


@dataclass(frozen=True)
class Match:
    """What the table was able to say about a listing."""

    model: str | None = None
    #: The armory row this came from, so a listing can point back at it rather
    #: than carry a copy of its name that drifts when the row is renamed.
    model_id: int | None = None
    kind: FirearmKind | None = None
    caliber: str | None = None
    manufacturer: str | None = None
    #: Where the pattern comes from. Unlike the maker, this is never a choice:
    #: nine firms built the M1 Carbine and all nine of them built an American
    #: rifle, so the model can state it even when it cannot name a maker.
    country: str | None = None

    def __bool__(self) -> bool:
        return any((self.model, self.kind, self.caliber, self.manufacturer, self.country))


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
            select(Caliber)
            .where(
                Caliber.status == ArmoryStatus.APPROVED,
                # Added with the column in migration 0018, and the reason the
                # column exists: a cartridge switched off is one somebody has
                # ruled on, and it must stop matching without being deleted --
                # deleting is not a rejection here, because a surviving row is
                # what stops a scan proposing the name again.
                Caliber.enabled.is_(True),
            )
            .order_by(Caliber.name)
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

    def match(self, title: str, description: str | None = None) -> Match:  # noqa: ARG002
        """The model named in a listing's *title*. The description is not read.

        This is stricter than the maker lookup beside it, which does fall back
        to the description, and the difference is deliberate. A maker's name in
        the prose is usually still the maker. A model designation in the prose
        is very often a *comparison*: a CZ vz.50 is described as a Walther PP
        copy, an East German P1001 as a Walther PP copy, and a box of .32 ACP
        ammunition lists the pistols it suits. Reading those gave sixty-three
        listings the Walther PP as their model, of which a third were CZs and
        one was ammunition -- and each of them would then have taken the PP's
        caliber and kind.

        A dealer selling a gun puts its designation in the title. Where they
        have not, the honest answer is that the armory does not know.

        The ``description`` argument is kept so callers need not care, and so
        that the reason it is ignored has somewhere to live.
        """
        for pattern, found in self.rules:
            if pattern.search(title or "") and not _contradicted(title, found):
                return found
        return Match()


def _contradicted(title: str, found: Match) -> bool:
    """Whether the listing plainly says something else than this model does.

    A designation is not unique. "Model 1911" is a Colt automatic and a
    Schmidt-Rubin rifle; "Model 1917" is a Colt revolver and an Enfield rifle;
    "Model 1873" is a Winchester and a Colt. So a title reading "COLT MODEL
    1917 REVOLVER" matched the Enfield and would have filed a revolver under
    rifles, in .30-06, made by Winchester.

    The whole match is discarded rather than just its kind, because a model
    that is wrong about what kind of gun this is was not this gun: its caliber
    and its maker are wrong too. Matching continues down the list, so a
    genuinely better row further along still gets its turn.
    """
    if found.kind is None:
        return False
    stated = classify.stated_kind(title)
    if stated is None:
        return False
    return stated == ("handgun" if found.kind.is_long_gun else "rifle")


def _facts_known(row: FirearmModel) -> int:
    """How much this row can tell a caller, for breaking ties between rows."""
    return sum(
        1
        for fact in (row.kind, row.calibers, row.wikipedia_url, row.manufacturers, row.country)
        if fact
    )


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
                model_id=row.id,
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
                country=row.country,
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
        model_id=found.model_id,
        kind=found.kind,
        caliber=stated or found.caliber,
        manufacturer=found.manufacturer,
        country=found.country,
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
        # Flushed immediately. This session runs with autoflush off, so
        # without it the row just added is invisible to the next lookup in the
        # same session -- and a scan proposing the same unknown cartridge from
        # forty listings would add forty identical rows and fail the commit on
        # a UNIQUE violation. Every existing test committed between calls,
        # which is exactly why nothing caught it.
        session.flush()
        invalidate()
    elif seen_in and row.status == ArmoryStatus.PENDING:
        row.first_seen_in = _note_sighting(row.first_seen_in, seen_in)
    return row


def propose_manufacturer(session: Session, name: str, seen_in: str = "") -> Manufacturer | None:
    """Write down a firm nothing in the table explains.

    Returns None when the maker registry already recognizes the name under any
    of its spellings, so a scan meeting "Norinco" for the hundredth time stops
    proposing it the moment somebody approves the row.
    """
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return None
    if manufacturers.registry(session).extract(cleaned):
        return None

    row = session.execute(
        select(Manufacturer).where(func.lower(Manufacturer.name) == cleaned.lower())
    ).scalar_one_or_none()
    if row is None:
        row = Manufacturer(name=cleaned, status=ArmoryStatus.PENDING, first_seen_in=seen_in or None)
        session.add(row)
        # Flushed immediately. This session runs with autoflush off, so
        # without it the row just added is invisible to the next lookup in the
        # same session -- and a scan proposing the same unknown cartridge from
        # forty listings would add forty identical rows and fail the commit on
        # a UNIQUE violation. Every existing test committed between calls,
        # which is exactly why nothing caught it.
        session.flush()
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
        # Flushed immediately. This session runs with autoflush off, so
        # without it the row just added is invisible to the next lookup in the
        # same session -- and a scan proposing the same unknown cartridge from
        # forty listings would add forty identical rows and fail the commit on
        # a UNIQUE violation. Every existing test committed between calls,
        # which is exactly why nothing caught it.
        session.flush()
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


class ArmoryView(str, enum.Enum):
    """What the Showing filter on the armory can be set to.

    Deliberately *not* ``ArmoryStatus``. Status answers "has a person ruled on
    this row", and for three of the four answers that is the whole story --
    but "switched off" is a ruling that status has no value for, and reading
    the queue as "everything not yet approved" put rows somebody had already
    decided about back in front of them forever.
    """

    PENDING = "pending"
    APPROVED = "approved"
    MERGED = "merged"
    #: Ruled out. See _view_clause for why this is not simply "not enabled".
    DISABLED = "disabled"


def _view_clause(table: Any, view: ArmoryView) -> Any:
    """The rows one Showing setting means.

    Two things are worth saying out loud here.

    **Disabled is a bucket, not an overlay.** A row that is switched off is
    gone from Awaiting approval and from Production, rather than appearing in
    one of them greyed out. Somebody who turned a row off has finished with
    it, and leaving it in the queue is what this exists to stop.

    **Merging away already switches a row off** (see ``merge_manufacturers``),
    so Disabled has to exclude merged rows or it fills up with every merge
    that has ever been made -- which are not decisions about this row's own
    usefulness and already have a bucket of their own.
    """
    if view is ArmoryView.MERGED:
        return table.status == ArmoryStatus.MERGED
    if view is ArmoryView.DISABLED:
        return and_(table.enabled.is_(False), table.status != ArmoryStatus.MERGED)
    status = ArmoryStatus.PENDING if view is ArmoryView.PENDING else ArmoryStatus.APPROVED
    return and_(table.status == status, table.enabled.is_(True))


def filter_by_view(stmt: Any, table: Any, view: ArmoryView | None) -> Any:
    """Apply a Showing setting to a query, or leave it alone for "Everything"."""
    return stmt if view is None else stmt.where(_view_clause(table, view))


def pending_counts(session: Session) -> dict[str, int]:
    """How many rows of each kind are waiting on somebody, for the nav badge.

    The same definition the Awaiting approval filter uses, which is the point:
    a badge that counts rows the tab it links to does not show sends somebody
    looking for two manufacturers that are not there.
    """
    return {
        name: int(
            session.execute(
                select(func.count(table.id)).where(_view_clause(table, ArmoryView.PENDING))
            ).scalar_one()
        )
        for name, table in CURATED.items()
    }


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------
def promote(session: Session, table: str, ids: Iterable[int]) -> tuple[int, int]:
    """Move rows into production. Returns ``(rows moved, listings re-matched)``.

    The one gate between a name somebody typed -- or a scan guessed -- and a
    table the application treats as true. Everything on the pending side is
    inert: it fills in no caliber, decides no kind, and answers no filter. It
    exists so an admin can look at it and say yes.

    Deliberately not the reverse of anything. Sending a row back to pending is
    a separate action with a separate button, because "I have checked this"
    and "I no longer trust this" are different statements and collapsing them
    into a toggle invites the second by accident.
    """
    return _restatus(session, table, ids, ArmoryStatus.PENDING, ArmoryStatus.APPROVED)


def send_back(session: Session, table: str, ids: Iterable[int]) -> tuple[int, int]:
    """Return production rows to awaiting-approval, and stop them deciding.

    Returns ``(rows moved, listings re-matched)``, like :func:`promote`.
    """
    return _restatus(session, table, ids, ArmoryStatus.APPROVED, ArmoryStatus.PENDING)


def _restatus(
    session: Session,
    table: str,
    ids: Iterable[int],
    was: ArmoryStatus,
    now: ArmoryStatus,
) -> tuple[int, int]:
    """Move rows between two statuses and re-match what that changes.

    Returns ``(rows moved, listings re-matched)``. The second number is the
    point: this used to write a status and stop, so approving a model left
    every listing it now explains still saying it matched nothing until the
    next scan. An admin had no way to tell a working change from a no-op.
    """
    model = CURATED[table]
    rows = session.execute(select(model).where(model.id.in_(list(ids)))).scalars().all()
    moved = [row for row in rows if row.status == was]
    spellings = [text for row in moved for text in row.spellings]
    for row in moved:
        row.status = now
    if not moved:
        return 0, 0
    invalidate()
    # Manufacturers have re-derived their listings since they existed; models
    # and calibers are what this brings into line. The maker path is left
    # alone rather than duplicated -- see api/manufacturers.py.
    session.flush()
    touched = reprocess(session, spellings) if table != "manufacturers" else 0
    return len(moved), touched


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
#: The shipped armory, versioned in the repository beside the code.
#:
#: Under ``seed/`` and deliberately not ``data/``: this repository's .gitignore
#: carries an unanchored ``data/``, which matches a directory of that name at
#: any depth. The file sat there for a while and was never committed, and the
#: first anyone knew of it was twelve tests failing in CI on a machine that
#: had only ever seen the repository.
SEED_FILE = Path(__file__).resolve().parents[1] / "seed" / "armory.yaml"


@dataclass
class SeedReport:
    manufacturers: int = 0
    calibers: int = 0
    models: int = 0
    links: int = 0
    #: Blanks filled on rows that were already here. The one thing this seeder
    #: does to an existing row, and only ever to a field holding nothing.
    countries_filled: int = 0

    @property
    def total(self) -> int:
        return self.manufacturers + self.calibers + self.models + self.countries_filled


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
            enabled=bool(entry.get("enabled", True)),
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
            # The one exception to "an existing row is left exactly as it is",
            # and it is the same one-directional fill the rest of the armory
            # uses: a column holding nothing is not an answer somebody gave,
            # so writing one into it overrules nobody. Without this the country
            # column would have reached every new installation and none of the
            # running ones, where all ninety-four makers already existed.
            existing = makers[name.lower()]
            if entry.get("country") and not existing.country:
                existing.country = str(entry["country"]).strip()
                report.countries_filled += 1
            continue
        firm = Manufacturer(
            name=name,
            aliases=_lines(entry.get("aliases")),
            status=ArmoryStatus.PENDING,
            position=int(entry.get("position") or 1000),
            country=entry.get("country"),
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
            country=entry.get("country"),
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
    """The armory as plain data, ordered so that diffs mean something."""
    makers = (
        session.execute(select(Manufacturer).order_by(func.lower(Manufacturer.name)))
        .scalars()
        .all()
    )
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
        # The makers go out too. They were missed at first, which meant a
        # curated armory could be committed with its models and calibers and
        # silently without the firms that built them -- so a model naming a
        # maker the file never mentioned arrived somewhere else as a pending
        # row conjured from a bare name, with no aliases and no order.
        "manufacturers": [
            _without_blanks(
                {
                    "name": row.name,
                    "aliases": row.spellings[1:],
                    # Missed when the column was added, which is the same
                    # mistake as the makers themselves being missed above and
                    # cost the same thing: an export carried a curated armory
                    # out with every firm's country stripped, so the fill that
                    # took country coverage from 69% to 91% would have done
                    # nothing at all on the far end.
                    "country": row.country,
                    "status": row.status.value,
                    "position": row.position if row.position != 1000 else None,
                    "enabled": None if row.enabled else False,
                    "notes": row.notes,
                }
            )
            for row in makers
        ],
        "calibers": [
            _without_blanks(
                {
                    "name": row.name,
                    "aliases": row.spellings[1:],
                    "status": row.status.value,
                    "enabled": None if row.enabled else False,
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
                    "country": row.country,
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
    manufacturers: list[Change] = field(default_factory=list)
    calibers: list[Change] = field(default_factory=list)
    models: list[Change] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.manufacturers or self.calibers or self.models)

    def counted(self) -> dict[str, int]:
        every = [*self.manufacturers, *self.calibers, *self.models]
        return {
            action: sum(1 for change in every if change.action == action)
            for action in ("add", "update", "delete")
        }


def plan_sync(session: Session, path: Path) -> SyncPlan:
    """What :func:`apply_sync` would do, without doing any of it."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    plan = SyncPlan()

    firms = {str(e["name"]).strip().lower(): e for e in data.get("manufacturers") or []}
    for firm in session.execute(select(Manufacturer)).scalars():
        entry = firms.pop(firm.name.strip().lower(), None)
        if entry is None:
            plan.manufacturers.append(Change(firm.name, "delete"))
        elif differing := _maker_differences(firm, entry):
            plan.manufacturers.append(Change(firm.name, "update", differing))
    plan.manufacturers.extend(Change(str(e["name"]), "add") for e in firms.values())

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

    plan.manufacturers.sort(key=lambda c: (c.action, c.name.lower()))
    plan.calibers.sort(key=lambda c: (c.action, c.name.lower()))
    plan.models.sort(key=lambda c: (c.action, c.name.lower()))
    return plan


def _maker_differences(row: Manufacturer, entry: dict[str, Any]) -> list[str]:
    return _differences(
        {
            "aliases": row.spellings[1:],
            "status": row.status.value,
            "position": row.position,
            "enabled": row.enabled,
            "notes": row.notes,
        },
        {
            "aliases": [str(a) for a in entry.get("aliases") or []],
            "status": str(entry.get("status") or ArmoryStatus.PENDING.value),
            "position": int(entry.get("position") or 1000),
            "enabled": bool(entry.get("enabled", True)),
            "notes": entry.get("notes"),
        },
    )


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
            "country": row.country,
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
            "country": entry.get("country"),
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
    """Which fields differ, treating "empty" as one value however it is spelled.

    An empty textarea stores "", the export drops blanks, and reading the file
    back gives None -- so "" != None made a fresh export report two rows to
    update, forever, and the update never converged. Nothing distinguishes an
    empty note from an absent one, so nothing here should either.
    """
    return sorted(
        key for key, value in want.items() if _blankless(have.get(key)) != _blankless(value)
    )


def _blankless(value: Any) -> Any:
    return None if value in ("", [], {}) else value


def apply_sync(session: Session, path: Path, prune: bool = False) -> dict[str, int]:
    """Reconcile the database with the file. Returns what it did.

    Deletions happen only when *prune* is set, and only for rows the file does
    not mention. An armory is curated in two places -- the file, and whatever
    instance is running -- and quietly deleting an admin's row because it has
    not been exported yet is the one mistake this must not make.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    done = {"added": 0, "updated": 0, "deleted": 0}
    _sync_makers(session, data.get("manufacturers") or [], done, prune)
    calibers = _sync_calibers(session, data.get("calibers") or [], done, prune)
    _sync_models(session, data.get("models") or [], calibers, done, prune)
    if any(done.values()):
        invalidate()
    return done


def _sync_makers(
    session: Session, entries: list[dict[str, Any]], done: dict[str, int], prune: bool
) -> None:
    known = {
        row.name.strip().lower(): row for row in session.execute(select(Manufacturer)).scalars()
    }
    listed: set[str] = set()
    for entry in entries:
        name = str(entry["name"]).strip()
        listed.add(name.lower())
        row = known.get(name.lower())
        if row is None:
            row = Manufacturer(name=name)
            session.add(row)
            known[name.lower()] = row
            done["added"] += 1
        elif _maker_differences(row, entry):
            done["updated"] += 1
        else:
            continue
        row.aliases = _lines(entry.get("aliases"))
        row.status = ArmoryStatus(str(entry.get("status") or ArmoryStatus.PENDING.value))
        row.position = int(entry.get("position") or 1000)
        row.enabled = bool(entry.get("enabled", True))
        row.notes = entry.get("notes")

    if prune:
        for key, row in list(known.items()):
            if key not in listed:
                session.delete(row)
                done["deleted"] += 1


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
    row.country = entry.get("country")
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


def _escape_like(text: str) -> str:
    """Make a literal safe inside a LIKE pattern, with ! as the escape."""
    return text.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def reprocess(session: Session, spellings: Iterable[str]) -> int:
    """Re-match every listing whose text mentions one of ``spellings``.

    **The armory's edits used to write nothing.** Promoting a model set a
    status and stopped: the listings it now explains kept saying they matched
    nothing until the next scan or a hand-run ``reclassify``, so an admin who
    approved a row and looked at a listing saw no effect and had no way to tell
    a working change from a no-op. Approving a model is the most consequential
    edit here -- it is what creates the ``firearm_model_id`` links that drive
    the model filter, the armory panel and the price spectrum -- and it was the
    one that wrote nothing at all.

    Scoped rather than exhaustive, exactly as the maker version is: an edit can
    only change the answer for a listing whose text contains one of the strings
    involved, so those are the only rows fetched. Both directions are handled,
    because disabling a row has to *remove* the links it used to make.

    Only the model link and the caliber are touched. A listing's country, maker
    and kind are settled by rules that live elsewhere, and re-deriving them
    from here would quietly duplicate ``_apply_catalog`` in a second place --
    which is the mistake this codebase has already made twice. ``reclassify``
    remains the way to rebuild everything.
    """
    wanted = [text.strip() for text in spellings if text and text.strip()]
    if not wanted:
        return 0

    clauses = []
    for text in wanted:
        pattern = f"%{_escape_like(text)}%"
        # ilike, because every spelling in this module is matched
        # case-insensitively and SQLite's LIKE gives that for free where
        # PostgreSQL's does not.
        clauses.append(Item.title.ilike(pattern, escape="!"))
        clauses.append(Item.description.ilike(pattern, escape="!"))

    candidates = session.execute(select(Item).where(or_(*clauses))).scalars().all()
    changed = 0
    for item in candidates:
        found = match(session, item.title)
        stated = canonical_caliber(session, item.caliber) or item.caliber
        caliber = stated or found.caliber
        if item.firearm_model_id != found.model_id or item.caliber != caliber:
            item.firearm_model_id = found.model_id
            item.caliber = caliber
            changed += 1
    return changed


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
    # Added when the country column was, and missed here at the time: a merge
    # that dropped it on the floor lost the one fact the source row may have
    # been the only one to carry.
    if target.country is None:
        target.country = source.country
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


class PrimaryNameError(ValueError):
    """A primary-name change that would lose a spelling or invent one."""


#: Which column on a listing carries this table's canonical name, so a change
#: of primary can restamp it. A model has none: a listing points at the row by
#: id (``items.firearm_model_id``), which is exactly why renaming one is safe
#: and renaming the other two is not.
_LABEL_COLUMN = {Caliber: Item.caliber, Manufacturer: Item.manufacturer}


def set_primary(session: Session, table, row_id: int, name: str) -> int:
    """Promote one of a row's own spellings to be its name. Returns listings moved.

    "IWI" and "Israel Weapon Industries" are the same firm, and which of them
    is the *name* decides what gets written onto every listing the row matches.
    Changing it by hand is two edits that have to happen together -- rename the
    row, then swap the alias -- and in between the row either claims a spelling
    twice or has stopped recognizing one. Doing it in one step is the whole
    point of this function.

    Three things happen and none of them is optional:

    * the chosen spelling becomes the name;
    * the old name becomes an alias, because it is what dealers wrote and what
      the row was recognizing listings by -- dropping it would silently stop
      matching the very text the row exists for;
    * every listing stamped with the old name is restamped with the new one,
      so the browse filter does not end up offering both as separate answers.
      That is the same restamp a merge does, for the same reason.

    Only a spelling the row already has may be chosen. Inventing a new name
    here would be a rename wearing a disguise, and a rename has to go through
    the duplicate check that stops two rows claiming one string.
    """
    row = session.get(table, row_id)
    if row is None:
        raise PrimaryNameError("No such row.")

    wanted = (name or "").strip()
    if not wanted:
        raise PrimaryNameError("Pick a spelling.")

    match = next((s for s in row.spellings if s.lower() == wanted.lower()), None)
    if match is None:
        raise PrimaryNameError(
            f"{wanted!r} is not one of this row's spellings. Add it as an alias first."
        )
    if match == row.name:
        return 0

    previous = row.name

    # The chosen spelling is very often *also a row* -- a tombstone left by the
    # merge that put it here in the first place. Five of ".308 Winchester"'s
    # nine aliases are merged rows pointing back at it, which makes this the
    # common case rather than an edge: aliases mostly arrive by merging. Taking
    # the name without dealing with that violates the unique index on `name`,
    # which is an unexplained 500 in the middle of a rename.
    clash = session.execute(
        select(table).where(func.lower(table.name) == match.lower(), table.id != row.id)
    ).scalar_one_or_none()
    if clash is not None and clash.merged_into_id != row.id:
        raise PrimaryNameError(
            f"{match!r} is also a row of its own, and not one that was merged into this "
            f"one. Merge it in or delete it first, then this can take its name."
        )

    if clash is not None:
        # Swap, rather than delete: the tombstone is the record that these two
        # spellings were ever unified, and afterwards it reads "the old name was
        # merged into the new one" -- which is exactly what happened, told in
        # the naming that now applies.
        #
        # Through a parking name, because both engines check the unique index
        # per statement: the two rows may not hold one name even for an instant.
        clash.name = f"__primary-swap-{row.id}-{uuid4().hex}"
        session.flush()

    row.name = match
    # The old name first: it is the spelling with the most history behind it,
    # and the order of this list is the order the rules are built in.
    keep: list[str] = [previous]
    for spelling in row.spellings[1:]:
        if spelling.lower() not in {match.lower(), *(k.lower() for k in keep)}:
            keep.append(spelling)
    row.aliases = "\n".join(keep) or None

    if clash is not None:
        session.flush()
        clash.name = previous
        session.flush()

    column = _LABEL_COLUMN.get(table)
    restamped = (
        _restamp(session, update(Item).where(column == previous).values(**{column.key: match}))
        if column is not None
        else 0
    )
    invalidate()
    return restamped


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
