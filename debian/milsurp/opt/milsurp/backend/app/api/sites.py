"""Site listing, admin controls, and scan history."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, select

from ..deps import AdminUser, CurrentUser, DbSession
from ..models import HostCooldown, Item, ScanRun, Site, as_utc, utcnow
from ..schemas import (
    PlannedSiteOut,
    ScanRunOut,
    ScanStartResponse,
    SiteOut,
    SiteUpdate,
)
from ..scrapers.planned import PLANNED
from ..services import cooldown, scan_service

router = APIRouter(prefix="/sites", tags=["sites"])


def _resting_hosts() -> dict[str, HostCooldown]:
    """Every host currently being left alone, by hostname.

    Read once for a whole listing rather than per site: it is one query either
    way thanks to the register's own cache, but doing it here makes that
    obvious instead of accidental.
    """
    return {row.host: row for row in cooldown.active()}


def _site_out(
    session: DbSession, site: Site, resting: dict[str, HostCooldown] | None = None
) -> SiteOut:
    """One site plus the roll-ups the admin list shows at a glance."""
    total, active = session.execute(
        select(
            func.count(Item.id),
            func.sum(case((Item.is_active.is_(True), 1), else_=0)),
        ).where(Item.site_id == site.id)
    ).one()
    last_run = (
        session.execute(
            select(ScanRun)
            .where(ScanRun.site_id == site.id)
            .order_by(ScanRun.started_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    data = SiteOut.model_validate(site)
    data.item_count = int(total or 0)
    data.active_item_count = int(active or 0)
    data.is_scanning = scan_service.is_running(site.id)
    data.last_run = ScanRunOut.model_validate(last_run) if last_run else None

    paused = (resting if resting is not None else _resting_hosts()).get(
        cooldown.host_of(site.base_url)
    )
    if paused is not None:
        now = utcnow()
        remaining = ((as_utc(paused.until) or now) - now).total_seconds()
        if remaining > 0:
            data.resting_seconds = int(remaining)
            data.resting_reason = paused.reason
    return data


@router.get("", response_model=list[SiteOut])
def list_sites(_user: CurrentUser, session: DbSession) -> list[SiteOut]:
    """Every site with its current status. Readable by any signed-in user."""
    sites = session.execute(select(Site).order_by(Site.name)).scalars().all()
    resting = _resting_hosts()
    return [_site_out(session, site, resting) for site in sites]


#: Before ``/{site_id}``, or "planned" is parsed as a site id and 422s.
@router.get("/planned", response_model=list[PlannedSiteOut])
def list_planned(_user: CurrentUser) -> list[PlannedSiteOut]:
    """Vendors the roadmap intends to read, and what each is waiting on.

    From the registry rather than the database: nothing here has a row, and
    giving one to a site that cannot be scanned would put it in every count,
    every scheduler pass and every digest that asks the database what exists.
    """
    return [PlannedSiteOut(**vars(site)) for site in PLANNED]


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: int, _user: CurrentUser, session: DbSession) -> SiteOut:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")
    return _site_out(session, site)


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(
    site_id: int, payload: SiteUpdate, _admin: AdminUser, session: DbSession
) -> SiteOut:
    """Enable/disable a site or change how often it is scanned."""
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")

    if payload.enabled is not None:
        was_enabled = site.enabled
        site.enabled = payload.enabled
        if payload.enabled and not was_enabled:
            # Re-enabling schedules the site immediately rather than leaving it
            # to wait out an interval that elapsed while it was off.
            site.next_scan_at = utcnow()
        elif not payload.enabled:
            site.next_scan_at = None

    if payload.scan_interval_minutes is not None:
        site.scan_interval_minutes = payload.scan_interval_minutes
        if site.enabled:
            # Re-base the schedule on the last scan so shortening an interval
            # takes effect now instead of after the old one expires.
            scan_service.schedule_next(site, site.last_scan_at or utcnow())

    if payload.name is not None:
        site.name = payload.name
    if payload.description is not None:
        site.description = payload.description

    session.commit()
    return _site_out(session, site)


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------
@router.post(
    "/{site_id}/scan", response_model=ScanStartResponse, status_code=status.HTTP_202_ACCEPTED
)
def start_scan(site_id: int, _admin: AdminUser, session: DbSession) -> ScanStartResponse:
    """Kick off a scan now, regardless of the schedule."""
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")
    if not site.is_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No scraper is registered for '{site.slug}'.",
        )
    if scan_service.is_running(site.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scan for this site is already running.",
        )

    # Run off-request: a browser-driven scan takes minutes and must not hold an
    # HTTP connection open. Progress is polled from the scan_runs row.
    result: dict[str, int] = {}
    started = threading.Event()

    def _run() -> None:
        try:
            result["run_id"] = scan_service.run_scan(site_id, trigger="manual")
        except scan_service.ScanBusy:
            result["run_id"] = -1
        finally:
            started.set()

    thread = threading.Thread(target=_run, name=f"milsurp-manual-{site_id}", daemon=True)
    thread.start()
    # Wait briefly for the run row to exist so the client gets a real id to poll.
    started.wait(timeout=2.0)

    run_id = result.get("run_id")
    if run_id is None:
        latest = (
            session.execute(
                select(ScanRun)
                .where(ScanRun.site_id == site_id)
                .order_by(ScanRun.started_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        run_id = latest.id if latest else 0
    if run_id == -1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scan for this site is already running.",
        )

    return ScanStartResponse(
        scan_run_id=run_id, site_id=site_id, message=f"Scan of {site.name} started."
    )


@router.post("/{site_id}/resting/clear", status_code=status.HTTP_200_OK)
def clear_resting(site_id: int, _admin: AdminUser, session: DbSession) -> dict[str, str]:
    """Let this site's host be asked again before its pause is up.

    Admin-only, because it is an undertaking to the vendor rather than a local
    preference: the pause exists because their server refused us, and lifting
    it early means going back sooner than they asked. Worth doing once the
    cause is known and fixed, and worth a deliberate click rather than a
    default.
    """
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")

    host = cooldown.host_of(site.base_url)
    if not cooldown.clear(host):
        return {"message": f"{host or site.name} was not resting."}
    return {"message": f"{host} may be asked again."}


@router.post("/{site_id}/scan/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_scan(site_id: int, _admin: AdminUser) -> dict[str, str]:
    if not scan_service.request_cancel(site_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No scan is running for this site.",
        )
    return {"message": "Cancellation requested; the scan will stop at its next checkpoint."}


@router.get("/{site_id}/scans", response_model=list[ScanRunOut])
def site_scan_history(
    site_id: int,
    _user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ScanRunOut]:
    """Drill-down history for one site, newest first."""
    if session.get(Site, site_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")
    runs = (
        session.execute(
            select(ScanRun)
            .where(ScanRun.site_id == site_id)
            .order_by(ScanRun.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [ScanRunOut.model_validate(run) for run in runs]
