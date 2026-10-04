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

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..deps import AdminUser, AppConfig, DbSession
from ..logsafe import client_address
from ..models import (
    ArmoryStatus,
    AuditEvent,
    Caliber,
    FirearmKind,
    FirearmModel,
    Item,
    Manufacturer,
    firearm_model_calibers,
    utcnow,
)
from ..schemas import (
    ArmoryAction,
    ArmoryIds,
    ArmoryKind,
    ArmoryMerge,
    ArmoryPrimaryName,
    ArmorySummary,
    ArmorySyncChange,
    ArmorySyncPlan,
    ArmoryWrite,
    CaliberCreate,
    CaliberOut,
    CaliberUpdate,
    FirearmModelCreate,
    FirearmModelOut,
    FirearmModelUpdate,
)
from ..services import armory as service
from ..services import armorybulk, armoryundo, audit, classify, mailer
from ..services import search as search_service

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

    Every listing it accounts for, not only the ones still for sale -- which is
    what the eye beside the number opens (``availability=all``), and what the
    makers and calibers tabs have always counted.

    This used to filter to active listings, on the reading that a de-listed gun
    is not something a decision about this row will affect today. Two things
    were wrong with it. The comment claimed it matched the maker tally and did
    not: neither the maker nor the caliber count has ever filtered, so the
    models tab was the odd one out of three. And it made the number disagree
    with the link beside it -- "10/22" read 0 Listings, and clicking its eye
    showed the Ruger it accounts for. A number you cannot verify by clicking it
    is worse than one that counts a sold rifle, and 13 rows read 0 while
    explaining something, which is an invitation to delete them.
    """
    rows = session.execute(
        select(Item.firearm_model_id, func.count(Item.id))
        .where(Item.firearm_model_id.is_not(None))
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


def _model_out(row: FirearmModel, matched: int = 0, mentions: int | None = None) -> FirearmModelOut:
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
        mention_count=mentions,
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
    rows = list(session.execute(stmt).scalars())
    # A pending row links nothing, so its link count is always 0 and useless
    # for deciding whether to approve it. What it would explain is how many
    # listings name it -- counted for every pending row in one read.
    pending = [row.name for row in rows if row.status == ArmoryStatus.PENDING]
    mentions = search_service.count_mentions_many(session, pending)
    return [
        _model_out(
            row,
            counts.get(row.id, 0),
            mentions.get(row.name) if row.status == ArmoryStatus.PENDING else None,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
@router.post("/calibers", response_model=CaliberOut, status_code=status.HTTP_201_CREATED)
def create_caliber(
    payload: CaliberCreate, admin: AdminUser, request: Request, session: DbSession
) -> CaliberOut:
    _reject_duplicate(session, Caliber, payload.name)
    row = Caliber(**_emptied(payload.model_dump()))
    session.add(row)
    session.flush()
    _record(session, admin, request, audit.ARMORY_CREATED, "caliber", row, _status_word(row))
    session.commit()
    service.invalidate()
    return _caliber_out(row, _caliber_counts(session), _models_per_caliber(session))


@router.patch("/calibers/{caliber_id}", response_model=ArmoryWrite)
def update_caliber(
    caliber_id: int,
    payload: CaliberUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> ArmoryWrite:
    row = _row(session, Caliber, caliber_id)
    changes = _emptied(payload.model_dump(exclude_unset=True))
    if "name" in changes and changes["name"] != row.name:
        _reject_duplicate(session, Caliber, changes["name"])
    # Both sides of the edit: the spellings it used to answer to have to be
    # re-matched as well as the ones it answers to now, or a removed alias
    # leaves its listings pointing at a rule that no longer exists.
    spellings = list(row.spellings)
    # Taken before anything is written, which is the only moment it exists.
    before = armoryundo.snapshot(row)
    for field, value in changes.items():
        setattr(row, field, value)
    session.flush()
    service.invalidate()
    changed = service.reprocess(session, [*spellings, *row.spellings])
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_EDITED,
        target_type="caliber",
        target_id=row.id,
        target_label=row.name,
        detail=", ".join(sorted(changes)),
        ip_address=client_address(request),
        before=before,
    )
    session.commit()
    return ArmoryWrite(
        caliber=_caliber_out(row, _caliber_counts(session), _models_per_caliber(session)),
        listings_changed=changed,
    )


@router.delete("/calibers/{caliber_id}", response_model=ArmoryWrite)
def delete_caliber(
    caliber_id: int, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryWrite:
    """Remove a cartridge, and say how many listings stopped carrying it.

    A body rather than 204, for the reason the maker endpoints already return
    one: deleting a row silently unlinks every listing it explained, and a
    dialog that closes on success tells an admin nothing about the several
    hundred rows that just changed underneath it.
    """
    row = _row(session, Caliber, caliber_id)
    spellings = list(row.spellings)
    before, label, was_id = armoryundo.snapshot(row), row.name, row.id
    session.delete(row)
    session.flush()
    service.invalidate()
    changed = service.reprocess(session, spellings)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_DELETED,
        target_type="caliber",
        target_id=was_id,
        target_label=label,
        detail=f"{changed} listing(s) re-matched",
        ip_address=client_address(request),
        before=before,
    )
    session.commit()
    return ArmoryWrite(listings_changed=changed)


@router.post("/models", response_model=FirearmModelOut, status_code=status.HTTP_201_CREATED)
def create_model(
    payload: FirearmModelCreate, admin: AdminUser, request: Request, session: DbSession
) -> FirearmModelOut:
    _reject_duplicate(session, FirearmModel, payload.name)
    data = _emptied(payload.model_dump())
    makers = _makers(session, data.pop("manufacturer_ids"))
    cartridges = _calibers(session, data.pop("caliber_ids"))
    row = FirearmModel(**data)
    row.manufacturers = makers
    row.calibers = cartridges
    session.add(row)
    session.flush()
    _record(session, admin, request, audit.ARMORY_CREATED, "model", row, _status_word(row))
    session.commit()
    service.invalidate()
    return _model_out(row)


@router.patch("/models/{model_id}", response_model=ArmoryWrite)
def update_model(
    model_id: int,
    payload: FirearmModelUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> ArmoryWrite:
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
    before = armoryundo.snapshot(row)
    for field, value in changes.items():
        setattr(row, field, value)
    session.flush()
    service.invalidate()
    changed = service.reprocess(session, [*spellings, *row.spellings])
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_EDITED,
        target_type="model",
        target_id=row.id,
        target_label=row.name,
        detail=", ".join(sorted(changes)),
        ip_address=client_address(request),
        before=before,
    )
    session.commit()
    return ArmoryWrite(
        model=_model_out(row, _listings_per_model(session).get(row.id, 0)),
        listings_changed=changed,
    )


@router.delete("/models/{model_id}", response_model=ArmoryWrite)
def delete_model(
    model_id: int, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryWrite:
    row = _row(session, FirearmModel, model_id)
    spellings = list(row.spellings)
    before, label, was_id = armoryundo.snapshot(row), row.name, row.id
    session.delete(row)
    session.flush()
    service.invalidate()
    # Or the listings it matched keep pointing at a row that has gone. The FK
    # is ON DELETE SET NULL, so they would not dangle -- but the ones it used
    # to explain would silently stop being explained by anything, with nothing
    # said about it.
    changed = service.reprocess(session, spellings)
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_DELETED,
        target_type="model",
        target_id=was_id,
        target_label=label,
        detail=f"{changed} listing(s) re-matched",
        ip_address=client_address(request),
        before=before,
    )
    session.commit()
    return ArmoryWrite(listings_changed=changed)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
@router.post("/{table}/promote", response_model=ArmoryAction)
def promote(
    table: str, payload: ArmoryIds, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Move rows into production, where they start deciding things."""
    _known_table(table)
    pending = _rows_where(session, table, payload.ids, approved=False)
    moved, touched = service.promote(session, table, payload.ids)
    for row in pending:
        _record(session, admin, request, audit.ARMORY_APPROVED, _TARGET[table], row)
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
    table: str, payload: ArmoryIds, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Return rows to awaiting-approval, and stop them deciding anything."""
    _known_table(table)
    approved = _rows_where(session, table, payload.ids, approved=True)
    moved, touched = service.send_back(session, table, payload.ids)
    for row in approved:
        _record(session, admin, request, audit.ARMORY_SENT_BACK, _TARGET[table], row)
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


@router.post("/{table}/disable", response_model=ArmoryAction)
def disable_rows(
    table: str, payload: ArmoryIds, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Switch a selection off: out of matching and out of the queue, but kept,
    so a scan does not propose the same names again. See services/armorybulk."""
    _known_table(table)
    moved, touched = armorybulk.disable(
        session, table, payload.ids, actor=admin, ip_address=client_address(request)
    )
    session.commit()
    return ArmoryAction(
        changed=moved,
        items_restamped=touched,
        message=(
            f"{moved} switched off." + (f" {touched} listing(s) re-matched." if touched else "")
            if moved
            else "Nothing changed; those rows were already off."
        ),
    )


@router.post("/{table}/delete", response_model=ArmoryAction)
def delete_rows(
    table: str, payload: ArmoryIds, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Delete a selection. Each row is audited with the snapshot revert needs."""
    _known_table(table)
    gone, touched = armorybulk.delete(
        session, table, payload.ids, actor=admin, ip_address=client_address(request)
    )
    session.commit()
    return ArmoryAction(
        changed=gone,
        items_restamped=touched,
        message=(
            f"{gone} deleted." + (f" {touched} listing(s) re-matched." if touched else "")
            if gone
            else "Nothing deleted; those rows were already gone."
        ),
    )


@router.post("/{table}/merge", response_model=ArmoryAction)
def merge(
    table: str, payload: ArmoryMerge, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Fold one row into another, keeping every spelling the first one caught."""
    _known_table(table)
    source = session.get(service.CURATED[table], payload.source_id)
    target = session.get(service.CURATED[table], payload.target_id)
    source_name = source.name if source else str(payload.source_id)
    merger = {
        "models": service.merge_models,
        "calibers": service.merge_calibers,
        "manufacturers": service.merge_manufacturers,
    }[table]
    try:
        restamped = merger(session, payload.source_id, payload.target_id)
    except service.MergeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record(
        session,
        admin,
        request,
        audit.ARMORY_MERGED,
        _TARGET[table],
        target,
        f"{source_name} merged into it; {restamped} listing(s) restamped",
        label=target.name if target else str(payload.target_id),
    )
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
def unmerge(
    table: str, row_id: int, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
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
    _record(
        session,
        admin,
        request,
        audit.ARMORY_UNMERGED,
        _TARGET[table],
        session.get(service.CURATED[table], row_id),
        f"{note}; {changed} listing(s) re-matched",
    )
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
    admin: AdminUser,
    request: Request,
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
        row = session.get(service.CURATED[table], row_id)
        old_name = row.name if row else None
        restamped = service.set_primary(session, service.CURATED[table], row_id, payload.name)
    except service.PrimaryNameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record(
        session,
        admin,
        request,
        audit.ARMORY_RENAMED,
        _TARGET[table],
        row,
        f"was {old_name}; {restamped} listing(s) restamped",
    )
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


#: What the email says to do with the file.
#:
#: Prose rather than a copy-and-paste command line, deliberately. The steps are
#: the same on every checkout; the commands are not -- the branch, the remote
#: and whether there is a review step are all site policy, and a message that
#: guessed at them would be wrong on somebody's machine while looking
#: authoritative. Naming the file to replace is the part nobody can guess.
_EXPORT_STEPS = (
    (
        "Replace <code>backend/app/seed/armory.yaml</code> in your checkout "
        "with the attached file, then read the diff before you commit it."
    ),
    (
        "The diff <em>is</em> the review. The export is ordered by name so it "
        "shows what changed rather than how the rows came back from the "
        "database."
    ),
    (
        "It carries the whole armory, including rows that are still awaiting "
        "approval. Those are usually proposals this instance made from its own "
        "listings, and they are the ones worth a second look."
    ),
)


def _export_email(rows: int, when: datetime) -> tuple[str, str]:
    steps = "".join(f"<li>{step}</li>" for step in _EXPORT_STEPS)
    html = (
        "<p>The armory from this instance is attached: "
        f"<strong>{rows:,}</strong> models and cartridges, exported "
        f"{when.strftime('%d %B %Y at %H:%M UTC')}.</p>"
        f"<ol>{steps}</ol>"
    )
    return "Armory export", html


@router.get("/export")
def export_armory_file(_admin: AdminUser, session: DbSession) -> Response:
    """The armory as the file the repository commits.

    A plain link, which only works because the session is a cookie: a bearer
    token in `sessionStorage` could not authenticate a navigation, and this
    would have needed fetching as a blob and handing back to the page.
    """
    text, _rows = service.export_text(session)
    return Response(
        content=text,
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="armory.yaml"'},
    )


@router.post("/export/email", response_model=ArmoryAction)
def email_armory_file(admin: AdminUser, session: DbSession, config: AppConfig) -> ArmoryAction:
    """Mail the armory to the administrator who asked for it.

    To their own address and no other: this is a file from inside the
    application's database, and a box that could send it anywhere is a way to
    exfiltrate the catalog with one stolen session.
    """
    if not admin.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account has no email address to send it to.",
        )
    text, rows = service.export_text(session)
    subject, html = _export_email(rows, utcnow())
    try:
        mailer.send_html(
            admin.email,
            subject,
            html,
            config=config,
            attachments={"armory.yaml": text.encode("utf-8")},
        )
    except mailer.MailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not send it: {exc}",
        ) from exc
    return ArmoryAction(
        changed=rows,
        message=f"Sent {rows:,} rows to {admin.email}.",
    )


@router.post("/revert/{event_id}", response_model=ArmoryAction)
def revert_edit(
    event_id: int, admin: AdminUser, request: Request, session: DbSession
) -> ArmoryAction:
    """Put an armory row back the way it was before one logged change.

    The event is the thing somebody is looking at when they want to undo it, so
    the undo is addressed by event rather than by row. See
    :mod:`app.services.armoryundo` for why a delete comes back with a new id
    and why that turns out not to matter.
    """
    event = session.get(AuditEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such change.")
    try:
        done = armoryundo.revert(session, event, admin, client_address(request))
    except armoryundo.CannotRevert as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    restored = "restored" if done.recreated else "put back"
    moved = f" {done.listings_changed:,} listing(s) re-matched." if done.listings_changed else ""
    return ArmoryAction(
        changed=1,
        items_restamped=done.listings_changed,
        message=f"{done.label} {restored}.{moved}",
    )


@router.post("/seed", response_model=ArmoryAction)
def seed(admin: AdminUser, request: Request, session: DbSession) -> ArmoryAction:
    """Add anything in the shipped armory file this database does not have.

    Additive only, and everything arrives awaiting approval. Safe to press
    twice: the second press adds nothing.
    """
    events: list[service.LoadEvent] = []
    report = service.seed(session, events=events)
    if report.total:
        # One per row, so the log says what arrived, and one summary on top.
        service.record_load(
            session,
            events,
            actor=admin,
            source="the shipped armory",
            ip_address=client_address(request),
        )
        audit.record(
            session,
            actor=admin,
            action=audit.ARMORY_SEEDED,
            target_type="armory",
            target_label="Shipped armory loaded",
            detail=(
                f"{report.manufacturers} manufacturer(s), {report.calibers} caliber(s), "
                f"{report.models} model(s) added, awaiting approval"
            ),
            ip_address=client_address(request),
        )
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


def _plan_out(plan: service.SyncPlan) -> ArmorySyncPlan:
    def rows(changes: list[service.Change]) -> list[ArmorySyncChange]:
        # Never a deletion from here: the page does not prune.
        return [
            ArmorySyncChange(name=change.name, action=change.action, fields=change.fields)
            for change in changes
            if change.action != "delete"
        ]

    out = ArmorySyncPlan(
        manufacturers=rows(plan.manufacturers),
        calibers=rows(plan.calibers),
        models=rows(plan.models),
    )
    every = [*out.manufacturers, *out.calibers, *out.models]
    out.added = sum(1 for change in every if change.action == "add")
    out.updated = sum(1 for change in every if change.action == "update")
    return out


@router.get("/sync/plan", response_model=ArmorySyncPlan)
def sync_plan(_admin: AdminUser, session: DbSession) -> ArmorySyncPlan:
    """What applying the shipped armory would change here, changing nothing.

    Shown before the change is made, because it overwrites: a row this
    database has edited since the file was exported is put back to what the
    file says. The plan is how somebody sees that before it happens.
    """
    return _plan_out(service.plan_sync(session, service.SEED_FILE))


@router.post("/sync", response_model=ArmoryAction)
def apply_shipped(admin: AdminUser, request: Request, session: DbSession) -> ArmoryAction:
    """Make this database's armory match the shipped file -- and re-match listings.

    The page's way to take up a curated armory: statuses, aliases, merges and
    corrections as the file has them, rows added as the file has them rather
    than awaiting approval (the file is itself somebody's reviewed export).
    Nothing is deleted. Every row changed is written to the audit log with what
    it held before, so each can be undone from the log on its own; then the
    listings that mention any spelling involved, before or after, are matched
    again, as an edit by hand does.
    """
    events: list[service.LoadEvent] = []
    done = service.apply_sync(session, service.SEED_FILE, prune=False, events=events)
    if not events:
        return ArmoryAction(changed=0, message="Nothing to change; this armory matches the file.")

    service.record_load(
        session,
        events,
        actor=admin,
        source="the shipped armory",
        ip_address=client_address(request),
    )
    audit.record(
        session,
        actor=admin,
        action=audit.ARMORY_SYNCED,
        target_type="armory",
        target_label="Shipped armory applied",
        detail=f"{done['added']} added, {done['updated']} changed",
        ip_address=client_address(request),
    )
    session.flush()
    restamped = service.rematch_after_load(session, events)
    session.commit()
    return ArmoryAction(
        changed=done["added"] + done["updated"],
        items_restamped=restamped,
        message=(
            f"Added {done['added']} and changed {done['updated']} row(s) from the shipped "
            f"armory; each is in the audit log."
            + (f" {restamped:,} listing(s) re-matched." if restamped else "")
        ),
    )


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------
#: What the audit log calls a row of each table.
_TARGET = {"models": "model", "calibers": "caliber", "manufacturers": "manufacturer"}


def _status_word(row: Any) -> str:
    status_value = getattr(row, "status", None)
    return "approved" if status_value == ArmoryStatus.APPROVED else "awaiting approval"


def _rows_where(session: DbSession, table: str, ids: list[int], *, approved: bool) -> list[Any]:
    """The rows of a selection a promote or send-back will actually move."""
    model = service.CURATED[table]
    in_production = model.status == ArmoryStatus.APPROVED
    return list(
        session.execute(
            select(model).where(model.id.in_(ids), in_production if approved else ~in_production)
        ).scalars()
    )


def _record(
    session: DbSession,
    admin: Any,
    request: Request,
    action: str,
    target_type: str,
    row: Any,
    detail: str | None = None,
    *,
    label: str | None = None,
) -> None:
    """Write one armory event. Never raises; see audit.record."""
    audit.record(
        session,
        actor=admin,
        action=action,
        target_type=target_type,
        target_id=getattr(row, "id", None),
        target_label=label or getattr(row, "name", None),
        detail=detail,
        ip_address=client_address(request),
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
