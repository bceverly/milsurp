"""The backup schedule, and taking one now.

Administrator-only. Three settings and one button: whether snapshots are taken,
how often, how many to keep, and "do it now".

**Where files land is not on this page.** ``backups.directory`` stays in
config.yaml, because a text box that can point the writer at any path on the
server is a worse idea than a default nobody can change from a browser. What is
here is policy; where it lands is the machine's business.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from ..deps import AdminUser, AppConfig, DbSession
from ..schemas import BackupSettingsOut, BackupSettingsUpdate, BackupSnapshotOut, BackupStateOut
from ..services import backup as backup_service

router = APIRouter(prefix="/admin/backups", tags=["backups"])

#: Frequencies the page offers. A free-text number of hours invites "1", which
#: on a large database is a snapshot still running when the next one starts.
ALLOWED_INTERVAL_HOURS = (6, 12, 24, 48, 72, 168)

#: How many snapshots may be kept. The ceiling is about disk: these are full
#: copies, and ten of a 30 MB database is already 300 MB.
ALLOWED_KEEP = (3, 5, 10, 20, 30)


def _state(session: DbSession, config: AppConfig) -> BackupStateOut:
    row = backup_service.settings(session)
    directory = config.backups.directory
    snapshots = [
        BackupSnapshotOut(
            name=path.name,
            bytes=path.stat().st_size,
            taken_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        )
        for path in backup_service.existing(directory)
    ]
    return BackupStateOut(
        settings=BackupSettingsOut.model_validate(row, from_attributes=True),
        directory=str(directory),
        engine=config.database.engine,
        # A .dump needs pg_restore and a .db opens with sqlite3; saying which
        # here saves somebody finding out at the worst possible moment.
        restore_hint=(
            f"pg_restore --clean --if-exists -d {config.database.name} <file>"
            if config.database.is_postgres
            else "stop the service and move the file into place"
        ),
        snapshots=snapshots,
        total_bytes=sum(s.bytes for s in snapshots),
        interval_choices=list(ALLOWED_INTERVAL_HOURS),
        keep_choices=list(ALLOWED_KEEP),
    )


@router.get("", response_model=BackupStateOut)
def read_backups(_admin: AdminUser, session: DbSession, config: AppConfig) -> BackupStateOut:
    return _state(session, config)


@router.patch("", response_model=BackupStateOut)
def update_backups(
    payload: BackupSettingsUpdate,
    _admin: AdminUser,
    session: DbSession,
    config: AppConfig,
) -> BackupStateOut:
    row = backup_service.settings(session)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.interval_hours is not None:
        if payload.interval_hours not in ALLOWED_INTERVAL_HOURS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"interval_hours must be one of {list(ALLOWED_INTERVAL_HOURS)}",
            )
        row.interval_hours = payload.interval_hours
    if payload.keep is not None:
        if payload.keep not in ALLOWED_KEEP:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"keep must be one of {list(ALLOWED_KEEP)}"
            )
        row.keep = payload.keep
    session.commit()
    return _state(session, config)


@router.post("/run", response_model=BackupStateOut)
def run_backup(_admin: AdminUser, session: DbSession, config: AppConfig) -> BackupStateOut:
    """Take one now, whatever the schedule says.

    A person asking for a backup is reason enough, so this runs even when the
    schedule is switched off -- which is the case it is most useful in: about to
    do something risky, backups not otherwise on.

    A failure comes back as a 500 with the reason, *and* is recorded on the
    settings row, so it is visible on the page after a reload rather than only
    in the response nobody kept.
    """
    try:
        backup_service.run(session, config, force=True)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"The backup failed: {exc}"
        ) from exc
    return _state(session, config)
