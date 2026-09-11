"""The armory, editable. Every route here is admin-only.

Two states and one gate. A row is either *awaiting approval* -- proposed by a
scan, or arrived in the seed file -- or it is *production*, meaning somebody
who knows the trade has looked at it and said yes. Only production rows decide
anything: the lookups that fill in a missing caliber or say what kind of gun a
listing is read approved rows and nothing else, so nothing can quietly start
rewriting the armory because a scan guessed at a name.

Promoting is therefore the only interesting write here, and it is deliberately
one-way: sending a row back is a separate action with its own button, because
"I have checked this" and "I no longer trust this" are different statements
and a toggle invites the second by accident.

Merging is the other half. Names arrive spelled several ways -- "Mosin" for
Mosin-Nagant, "7.65mm Browning" for .32 ACP -- and a merge folds one row into
another, moving its spellings across so nothing stops being recognized, and
restamping the listings that carried the old name. The merged row stays,
marked and pointing at its target, because an admin who merges the wrong pair
should have something to look at rather than an archaeology exercise -- and,
since ``unmerge``, something to act on. A merge now writes down what it took
before it takes it, so the undo can give back the links and the aliases rather
than only un-hiding the row.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..deps import AdminUser, DbSession
from ..models import (
    Caliber,
    FirearmKind,
    FirearmModel,
    Item,
    Manufacturer,
    firearm_model_calibers,
)
from ..schemas import (
    ArmoryAction,
    ArmoryIds,
    ArmoryKind,
    ArmoryMerge,
    ArmoryPrimaryName,
    ArmorySummary,
    CaliberCreate,
    CaliberOut,
    CaliberUpdate,
    FirearmModelCreate,
    FirearmModelOut,
    FirearmModelUpdate,
)
from ..services import armory as service
from ..services import classify

router = APIRouter(prefix="/armory", tags=["armory"])

#: How the nine-ish kinds are written on screen. Held here rather than in the
#: frontend so the labels and the enum cannot drift apart, and so the browse
#: page's rifle/handgun split is visible at the point the choice is made.
KIND_LABELS: dict[FirearmKind, str] = {
    FirearmKind.RIFLE: "Rifle",
    FirearmKind.CARBINE: "Carbine",
    FirearmKind.SHOTGUN: "Shotgun",
    FirearmKind.PISTOL: "Pistol",
    FirearmKind.REVOLVER: "Revolver",
    FirearmKind.FLINTLOCK_RIFLE: "Flintlock rifle",
    FirearmKind.FLINTLOCK_CARBINE: "Flintlock carbine",
    FirearmKind.FLINTLOCK_PISTOL: "Flintlock pistol",
    FirearmKind.PERCUSSION_RIFLE: "Percussion rifle",
    FirearmKind.PERCUSSION_CARBINE: "Percussion carbine",
    FirearmKind.PERCUSSION_PISTOL: "Percussion pistol",
    FirearmKind.PERCUSSION_REVOLVER: "Percussion revolver",
}


# ---------------------------------------------------------------------------
# Shaping rows for the page
# ---------------------------------------------------------------------------
def _caliber_counts(session: DbSession) -> dict[str, int]:
    rows = session.execute(
        select(Item.caliber, func.count(Item.id))
        .where(Item.caliber.is_not(None))
        .group_by(Item.caliber)
    ).all()
    return {name: count for name, count in rows if name}


def _listings_per_model(session: DbSession) -> dict[int, int]:
    """How many listings each model currently accounts for.

    One grouped query rather than one per row: the makers tab has done this
    since it existed and the models tab was the one place the number was
    missing, which made "is this row worth filling in?" the question the page
    could not answer.

    Counted over *active* listings only, the way the maker tally is: a de-listed
    gun is not something a decision about this row will affect today.
    """
    rows = session.execute(
        select(Item.firearm_model_id, func.count(Item.id))
        .where(Item.firearm_model_id.is_not(None), Item.is_active.is_(True))
        .group_by(Item.firearm_model_id)
    ).all()
    return {model_id: count for model_id, count in rows if model_id}


def _models_per_caliber(session: DbSession) -> dict[int, int]:
    rows = session.execute(
        select(
            firearm_model_calibers.c.caliber_id,
            func.count(firearm_model_calibers.c.firearm_model_id),
        ).group_by(firearm_model_calibers.c.caliber_id)
    ).all()
    return {caliber_id: count for caliber_id, count in rows if caliber_id}


def _caliber_out(row: Caliber, items: dict[str, int], models: dict[int, int]) -> CaliberOut:
    return CaliberOut(
        id=row.id,
        name=row.name,
        aliases=row.aliases,
        status=row.status,
        notes=row.notes,
        first_seen_in=row.first_seen_in,
        merged_into=row.merged_into.name if row.merged_into else None,
        item_count=items.get(row.name, 0),
        model_count=models.get(row.id, 0),
        enabled=row.enabled,
    )


def _model_out(row: FirearmModel, matched: int = 0) -> FirearmModelOut:
    return FirearmModelOut(
        id=row.id,
        name=row.name,
        aliases=row.aliases,
        kind=row.kind,
        country=row.country,
        caliber_ids=[cartridge.id for cartridge in row.calibers],
        calibers=row.caliber_names,
        manufacturer_ids=[maker.id for maker in row.manufacturers],
        manufacturers=[maker.name for maker in row.manufacturers],
        wikipedia_url=row.wikipedia_url,
        status=row.status,
        position=row.position,
        enabled=row.enabled,
        notes=row.notes,
        first_seen_in=row.first_seen_in,
        merged_into=row.merged_into.name if row.merged_into else None,
        item_count=matched,
    )


def _makers(session: DbSession, ids: list[int]) -> list[Manufacturer]:
    if not ids:
        return []
    found = session.execute(select(Manufacturer).where(Manufacturer.id.in_(ids))).scalars().all()
    missing = set(ids) - {maker.id for maker in found}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No such manufacturer: {', '.join(str(i) for i in sorted(missing))}.",
        )
    return list(found)


def _calibers(session: DbSession, ids: list[int]) -> list[Caliber]:
    if not ids:
        return []
    found = session.execute(select(Caliber).where(Caliber.id.in_(ids))).scalars().all()
    missing = set(ids) - {cartridge.id for cartridge in found}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No such caliber: {', '.join(str(i) for i in sorted(missing))}.",
        )
    return list(found)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
@router.get("/summary", response_model=ArmorySummary)
def summary(_admin: AdminUser, session: DbSession) -> ArmorySummary:
    return ArmorySummary(**service.pending_counts(session))


@router.get("/kinds", response_model=list[ArmoryKind])
def kinds(_admin: AdminUser) -> list[ArmoryKind]:
    return [
        ArmoryKind(value=kind.value, label=label, is_handgun=kind.is_handgun)
        for kind, label in KIND_LABELS.items()
    ]


@router.get("/countries", response_model=list[str])
def countries(_admin: AdminUser) -> list[str]:
    """Every country the classifier is able to name a listing with.

    Offered as suggestions on the model form for the same reason KIND_LABELS
    lives here: the armory's answer and the classifier's answer end up in the
    same ``items.country`` column, and a model recorded as "USSR" against
    titles read as "Russia" would split one country into two filters that each
    show half the rifles.

    Suggestions, not a whitelist. The column is free text and the list is a
    dozen countries short of the world.
    """
    return sorted({country for _pattern, country in classify.COUNTRY_PATTERNS})


@router.get("/calibers", response_model=list[CaliberOut])
def list_calibers(
    _admin: AdminUser,
    session: DbSession,
    view: service.ArmoryView | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=100),
) -> list[CaliberOut]:
    stmt = select(Caliber).options(selectinload(Caliber.merged_into)).order_by(Caliber.name)
    stmt = service.filter_by_view(stmt, Caliber, view)
    if search:
        stmt = stmt.where(Caliber.name.ilike(f"%{search}%") | Caliber.aliases.ilike(f"%{search}%"))
    items, models = _caliber_counts(session), _models_per_caliber(session)
    return [_caliber_out(row, items, models) for row in session.execute(stmt).scalars()]


@router.get("/models", response_model=list[FirearmModelOut])
def list_models(
    _admin: AdminUser,
    session: DbSession,
    view: service.ArmoryView | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=100),
) -> list[FirearmModelOut]:
    stmt = (
        select(FirearmModel)
        .options(
            selectinload(FirearmModel.manufacturers),
            selectinload(FirearmModel.calibers),
            selectinload(FirearmModel.merged_into),
        )
        .order_by(FirearmModel.name)
    )
    stmt = service.filter_by_view(stmt, FirearmModel, view)
    if search:
        stmt = stmt.where(
            FirearmModel.name.ilike(f"%{search}%") | FirearmModel.aliases.ilike(f"%{search}%")
        )
    counts = _listings_per_model(session)
    return [_model_out(row, counts.get(row.id, 0)) for row in session.execute(stmt).scalars()]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
@router.post("/calibers", response_model=CaliberOut, status_code=status.HTTP_201_CREATED)
def create_caliber(payload: CaliberCreate, _admin: AdminUser, session: DbSession) -> CaliberOut:
    _reject_duplicate(session, Caliber, payload.name)
    row = Caliber(**_emptied(payload.model_dump()))
    session.add(row)
    session.commit()
    service.invalidate()
    return _caliber_out(row, _caliber_counts(session), _models_per_caliber(session))


@router.patch("/calibers/{caliber_id}", response_model=CaliberOut)
def update_caliber(
    caliber_id: int, payload: CaliberUpdate, _admin: AdminUser, session: DbSession
) -> CaliberOut:
    row = _row(session, Caliber, caliber_id)
    changes = _emptied(payload.model_dump(exclude_unset=True))
    if "name" in changes and changes["name"] != row.name:
        _reject_duplicate(session, Caliber, changes["name"])
    # Both sides of the edit: the spellings it used to answer to have to be
    # re-matched as well as the ones it answers to now, or a removed alias
    # leaves its listings pointing at a rule that no longer exists.
    spellings = list(row.spellings)
    for field, value in changes.items():
        setattr(row, field, value)
    session.flush()
    service.invalidate()
    service.reprocess(session, [*spellings, *row.spellings])
    session.commit()
    return _caliber_out(row, _caliber_counts(session), _models_per_caliber(session))


@router.delete("/calibers/{caliber_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_caliber(caliber_id: int, _admin: AdminUser, session: DbSession) -> None:
    row = _row(session, Caliber, caliber_id)
    spellings = list(row.spellings)
    session.delete(row)
    session.flush()
    service.invalidate()
    service.reprocess(session, spellings)
    session.commit()


@router.post("/models", response_model=FirearmModelOut, status_code=status.HTTP_201_CREATED)
def create_model(
    payload: FirearmModelCreate, _admin: AdminUser, session: DbSession
) -> FirearmModelOut:
    _reject_duplicate(session, FirearmModel, payload.name)
    data = _emptied(payload.model_dump())
    makers = _makers(session, data.pop("manufacturer_ids"))
    cartridges = _calibers(session, data.pop("caliber_ids"))
    row = FirearmModel(**data)
    row.manufacturers = makers
    row.calibers = cartridges
    session.add(row)
    session.commit()
    service.invalidate()
    return _model_out(row)


@router.patch("/models/{model_id}", response_model=FirearmModelOut)
def update_model(
    model_id: int, payload: FirearmModelUpdate, _admin: AdminUser, session: DbSession
) -> FirearmModelOut:
    row = _row(session, FirearmModel, model_id)
    changes = _emptied(payload.model_dump(exclude_unset=True))
    if "name" in changes and changes["name"] != row.name:
        _reject_duplicate(session, FirearmModel, changes["name"])
    if "manufacturer_ids" in changes:
        row.manufacturers = _makers(session, changes.pop("manufacturer_ids") or [])
    if "caliber_ids" in changes:
        row.calibers = _calibers(session, changes.pop("caliber_ids") or [])
    # Both sides of the edit -- see update_caliber for why.
    spellings = list(row.spellings)
    for field, value in changes.items():
        setattr(row, field, value)
    session.flush()
    service.invalidate()
    service.reprocess(session, [*spellings, *row.spellings])
    session.commit()
    return _model_out(row, _listings_per_model(session).get(row.id, 0))


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: int, _admin: AdminUser, session: DbSession) -> None:
    row = _row(session, FirearmModel, model_id)
    spellings = list(row.spellings)
    session.delete(row)
    session.flush()
    service.invalidate()
    # Or the listings it matched keep pointing at a row that has gone. The FK
    # is ON DELETE SET NULL, so they would not dangle -- but the ones it used
    # to explain would silently stop being explained by anything, with nothing
    # said about it.
    service.reprocess(session, spellings)
    session.commit()


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
@router.post("/{table}/promote", response_model=ArmoryAction)
def promote(table: str, payload: ArmoryIds, _admin: AdminUser, session: DbSession) -> ArmoryAction:
    """Move rows into production, where they start deciding things."""
    _known_table(table)
    moved, touched = service.promote(session, table, payload.ids)
    session.commit()
    return ArmoryAction(
        changed=moved,
        items_restamped=touched,
        message=(
            f"{moved} moved into production."
            + (f" {touched} listing(s) re-matched." if touched else "")
            if moved
            else "Nothing moved; those rows are already in production."
        ),
    )


@router.post("/{table}/send-back", response_model=ArmoryAction)
def send_back(
    table: str, payload: ArmoryIds, _admin: AdminUser, session: DbSession
) -> ArmoryAction:
    """Return rows to awaiting-approval, and stop them deciding anything."""
    _known_table(table)
    moved, touched = service.send_back(session, table, payload.ids)
    session.commit()
    return ArmoryAction(
        changed=moved,
        items_restamped=touched,
        message=(
            f"{moved} sent back for approval."
            + (f" {touched} listing(s) re-matched." if touched else "")
            if moved
            else "Nothing moved; those rows are already awaiting approval."
        ),
    )


@router.post("/{table}/merge", response_model=ArmoryAction)
def merge(table: str, payload: ArmoryMerge, _admin: AdminUser, session: DbSession) -> ArmoryAction:
    """Fold one row into another, keeping every spelling the first one caught."""
    _known_table(table)
    merger = {
        "models": service.merge_models,
        "calibers": service.merge_calibers,
        "manufacturers": service.merge_manufacturers,
    }[table]
    try:
        restamped = merger(session, payload.source_id, payload.target_id)
    except service.MergeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return ArmoryAction(
        changed=1,
        items_restamped=restamped,
        message=(
            f"Merged. {restamped} listing(s) restamped."
            if restamped
            else "Merged. No listings carried the old name."
        ),
    )


@router.post("/{table}/{row_id}/unmerge", response_model=ArmoryAction)
def unmerge(table: str, row_id: int, _admin: AdminUser, session: DbSession) -> ArmoryAction:
    """Bring a merged-away row back, and make the target give its name back.

    The other half of the promise the merged row was kept for. Until this
    existed, an admin who merged the wrong pair had "something to look at" and
    no way to act on it.
    """
    _known_table(table)
    try:
        note, changed = service.unmerge(session, table, row_id)
    except service.UnmergeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return ArmoryAction(
        changed=1,
        items_restamped=changed,
        message=(
            f"Un-merged {note}. {changed} listing(s) re-matched."
            if changed
            else f"Un-merged {note}. No listings changed."
        ),
    )


@router.post("/{table}/{row_id}/primary", response_model=ArmoryAction)
def set_primary(
    table: str,
    row_id: int,
    payload: ArmoryPrimaryName,
    _admin: AdminUser,
    session: DbSession,
) -> ArmoryAction:
    """Promote one of a row's own spellings to be its name.

    Not the same operation as editing the Name field, which is why it is not
    that. A rename leaves the old spelling behind -- the row stops recognizing
    the text it was built to recognize -- and it leaves every listing already
    stamped with the old name pointing at a name nothing has any more. This
    keeps the old name as an alias and restamps the listings, in one step.
    """
    _known_table(table)
    try:
        restamped = service.set_primary(session, service.CURATED[table], row_id, payload.name)
    except service.PrimaryNameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return ArmoryAction(
        changed=1,
        items_restamped=restamped,
        message=(
            f"{payload.name} is now the primary name. {restamped} listing(s) restamped."
            if restamped
            else f"{payload.name} is now the primary name."
        ),
    )


@router.post("/seed", response_model=ArmoryAction)
def seed(_admin: AdminUser, session: DbSession) -> ArmoryAction:
    """Add anything in the shipped armory file this database does not have.

    Additive only, and everything arrives awaiting approval. Safe to press
    twice: the second press adds nothing.
    """
    report = service.seed(session)
    session.commit()
    return ArmoryAction(
        changed=report.total,
        message=(
            f"Added {report.manufacturers} manufacturer(s), {report.calibers} caliber(s) "
            f"and {report.models} model(s), all awaiting approval."
            if report.total
            else "Nothing to add; this database already has everything in the file."
        ),
    )


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------
#: The optional text fields, where an empty box means "nothing" rather than
#: "the empty string". Storing "" makes a row that differs from an untouched
#: one in the database and not on the screen, which is how an export and a
#: sync ended up disagreeing forever about two Walthers.
_OPTIONAL_TEXT = ("aliases", "notes", "wikipedia_url", "first_seen_in", "country")


def _emptied(changes: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (
            None
            if key in _OPTIONAL_TEXT and isinstance(value, str) and not value.strip()
            else value
        )
        for key, value in changes.items()
    }


def _known_table(table: str) -> None:
    if table not in service.CURATED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown armory table {table!r}. Valid: {', '.join(service.CURATED)}.",
        )


def _row(session: DbSession, table, row_id: int):
    row = session.get(table, row_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return row


def _reject_duplicate(session: DbSession, table, name: str) -> None:
    """Names are the identity here, so two rows may not share one.

    Case-insensitively: ".30-06" and ".30-06" differing only in case would be
    two rows that match exactly the same text, and whichever came first would
    win by accident.
    """
    clash = session.execute(
        select(table).where(func.lower(table.name) == name.strip().lower())
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{name!r} already exists. Merge into it rather than adding a second row.",
        )
