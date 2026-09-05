"""Cross-site scan views."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession
from ..models import ScanRun, ScanStatus, Site
from ..schemas import ScanRunDetail, ScanRunOut

router = APIRouter(prefix="/scans", tags=["scans"])


@router.get("", response_model=list[ScanRunOut])
def list_scans(
    _user: CurrentUser,
    session: DbSession,
    site_id: int | None = Query(default=None),
    scan_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ScanRunOut]:
    """Recent scan runs across every site, newest first."""
    stmt = select(ScanRun).order_by(ScanRun.started_at.desc())
    if site_id is not None:
        stmt = stmt.where(ScanRun.site_id == site_id)
    if scan_status:
        try:
            stmt = stmt.where(ScanRun.status == ScanStatus(scan_status))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown scan status {scan_status!r}.",
            ) from exc
    runs = session.execute(stmt.offset(offset).limit(limit)).scalars().all()
    return [ScanRunOut.model_validate(run) for run in runs]


@router.get("/{run_id}", response_model=ScanRunDetail)
def get_scan(run_id: int, _user: CurrentUser, session: DbSession) -> ScanRunDetail:
    """One run with its full progress log; polled while a scan is in flight."""
    run = session.get(ScanRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scan run.")
    detail = ScanRunDetail.model_validate(run)
    site = session.get(Site, run.site_id)
    detail.site_name = site.name if site else None
    return detail
