"""Site listing, admin controls, and scan history."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import case, func, select

from ..deps import AdminUser, CurrentUser, DbSession
from ..logsafe import client_address
from ..models import HostCooldown, Item, ScanRun, Site, as_utc, utcnow
from ..schemas import (
    DetailRefetchMarked,
    PhotoRunStarted,
    PlannedSiteOut,
    ScanRunOut,
    ScanStartResponse,
    SiteOut,
    SiteUpdate,
)
from ..scrapers import get_scraper_class
from ..scrapers.planned import PLANNED
from ..services import audit, cooldown, inbox, scan_service

log = logging.getLogger("milsurp.sites")

router = APIRouter(prefix="/sites", tags=["sites"])


def _resting_hosts() -> dict[str, HostCooldown]:
    """Every host currently being left alone, by hostname.

    Read once for a whole listing rather than per site: it is one query either
    way thanks to the register's own cache, but doing it here makes that
    obvious instead of accidental.
    """
    return {row.host: row for row in cooldown.active()}


def _site_out(
    session: DbSession,
    site: Site,
    resting: dict[str, HostCooldown] | None = None,
    photos: dict[int, tuple[int, int]] | None = None,
    details: dict[int, int] | None = None,
    confirming: dict[int, datetime] | None = None,
) -> SiteOut:
    """One site plus the roll-ups the admin list shows at a glance.

    ``resting`` and ``photos`` are passed in by the list view, which computes
    each once for every site rather than once per site -- the same reason
    ``resting`` was already threaded through here.
    """
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

    counts = photos if photos is not None else scan_service.pending_photo_counts(session)
    data.photos_pending, data.photos_failed = counts.get(site.id, (0, 0))
    read = details if details is not None else scan_service.detail_counts(session)
    data.details_fetched = read.get(site.id, 0)

    scraper = get_scraper_class(site.slug)
    if scraper is not None:
        data.newsletter_url = scraper.newsletter_url
        data.newsletter_note = scraper.newsletter_note
    asked = (confirming if confirming is not None else inbox.awaiting_confirmation(session)).get(
        site.id
    )
    data.confirmation_requested_at = asked

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
    photos = scan_service.pending_photo_counts(session)
    details = scan_service.detail_counts(session)
    confirming = inbox.awaiting_confirmation(session)
    return [_site_out(session, site, resting, photos, details, confirming) for site in sites]


#: Before ``/{site_id}``, or "planned" is parsed as a site id and 422s.
@router.get("/planned", response_model=list[PlannedSiteOut])
def list_planned(_user: CurrentUser) -> list[PlannedSiteOut]:
    """Vendors the roadmap intends to read, and what each is waiting on.

    From the registry rather than the database: nothing here has a row, and
    giving one to a site that cannot be scanned would put it in every count,
    every scheduler pass and every digest that asks the database what exists.
    """
    return [PlannedSiteOut(**vars(site)) for site in PLANNED]


#: Before ``/{site_id}``, for the same reason ``/planned`` is.
@router.post("/photos", response_model=PhotoRunStarted, status_code=status.HTTP_202_ACCEPTED)
def update_all_photos(_admin: AdminUser, session: DbSession) -> PhotoRunStarted:
    """Fetch every photograph any site is still missing."""
    return _start_photo_run(session, None)


@router.post(
    "/{site_id}/photos", response_model=PhotoRunStarted, status_code=status.HTTP_202_ACCEPTED
)
def update_site_photos(site_id: int, _admin: AdminUser, session: DbSession) -> PhotoRunStarted:
    """Fetch the photographs this one site is still missing."""
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")
    return _start_photo_run(session, site)


def _start_photo_run(session: DbSession, site: Site | None) -> PhotoRunStarted:
    """Drain the photo queue off-request, for one site or for all of them.

    **This re-scrapes nothing.** Every URL involved is already stored; what is
    missing is the bytes behind it, which a scan fetches under a per-run budget
    and carries the remainder to the next run. On a catalog that gained eight
    hundred listings at once that is a backlog measured in days of scans, and
    this is the same download step on its own.

    Photographs already given up on are tried again, which a scheduled run
    deliberately does not do. The difference is that somebody pressed this:
    the attempt cap exists so a dead URL cannot eat the budget forever, and a
    person asking for the photographs now is exactly the case it should not
    stand in the way of.
    """
    site_id = site.id if site else None
    counts = scan_service.pending_photo_counts(session)
    if site is not None:
        waiting, retrying = counts.get(site.id, (0, 0))
    else:
        waiting = sum(one for one, _ in counts.values())
        retrying = sum(other for _, other in counts.values())

    if not waiting and not retrying:
        where = f"for {site.name}" if site else "anywhere"
        return PhotoRunStarted(
            site_id=site_id,
            waiting=0,
            retrying=0,
            message=f"Every photograph {where} is already stored.",
        )

    # One at a time, whatever the scope: two drains would work the same rows
    # and earn each other's host pauses.
    if not scan_service.begin_photo_run(site_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Photographs are already being fetched. Wait for that to finish.",
        )

    slug = site.slug if site else None
    name = site.name if site else "every site"

    def _run() -> None:
        try:
            scan_service.download_pending_photos(site_slug=slug, retry_failed=True)
        except Exception:
            # A background thread that dies quietly is a button that appears
            # to work and never does.
            log.exception("Fetching photographs for %s failed.", name)
        finally:
            scan_service.end_photo_run(site_id)

    threading.Thread(target=_run, name=f"milsurp-photos-{slug or 'all'}", daemon=True).start()
    return PhotoRunStarted(
        site_id=site_id,
        waiting=waiting,
        retrying=retrying,
        message=f"Fetching {waiting + retrying} photograph(s) for {name}.",
    )


@router.post(
    "/{site_id}/refetch-details",
    response_model=DetailRefetchMarked,
    status_code=status.HTTP_200_OK,
)
def refetch_details(
    site_id: int,
    _admin: AdminUser,
    session: DbSession,
    limit: int | None = Query(default=None, ge=1, le=100_000),
) -> DetailRefetchMarked:
    """Queue this site's product pages to be read again on the next scan.

    **Nothing is fetched here.** A scan skips the product page of any listing
    it has already read one for, which is what keeps a re-scan cheap -- and
    what means a fix to how a page is *parsed* never reaches the listings that
    were parsed wrongly. This clears that mark; the reading happens when the
    site is next scanned.

    ``limit`` takes the stalest first, so pressing this twice makes progress
    rather than re-marking the same listings. It is worth having because a
    whole site is not always the right bite: one shop here is 976 listings of
    a dozen photographs each, and re-reading all of it at once queues five
    figures of downloads behind it.
    """
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")

    marked, _by_site = scan_service.mark_for_refetch(session, site_id=site.id, limit=limit)
    remaining = scan_service.detail_counts(session).get(site.id, 0)

    if not marked:
        message = f"No listing of {site.name} has a product page to re-read."
    elif remaining:
        message = (
            f"{marked} listing(s) of {site.name} will be read again on the next scan. "
            f"{remaining} still to go — press again to queue more."
        )
    else:
        message = f"All {marked} listing(s) of {site.name} will be read again on the next scan."
    return DetailRefetchMarked(site_id=site.id, marked=marked, remaining=remaining, message=message)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: int, _user: CurrentUser, session: DbSession) -> SiteOut:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")
    return _site_out(session, site)


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(
    site_id: int,
    payload: SiteUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> SiteOut:
    """Enable/disable a site or change how often it is scanned."""
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")

    turned = None
    if payload.enabled is not None:
        was_enabled = site.enabled
        site.enabled = payload.enabled
        # Only a change is worth a row. Saving the page with the switch already
        # where it was is not a decision anybody made.
        if payload.enabled != was_enabled:
            turned = payload.enabled
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

    if turned is not None:
        audit.record(
            session,
            actor=admin,
            action=audit.SITE_ENABLED if turned else audit.SITE_DISABLED,
            target_type="site",
            target_id=site.id,
            target_label=site.name,
            ip_address=client_address(request),
        )

    session.commit()
    return _site_out(session, site)


@router.post("/{site_id}/newsletter/confirmed", response_model=SiteOut)
def confirm_newsletter(
    site_id: int, admin: AdminUser, request: Request, session: DbSession
) -> SiteOut:
    """Say the mailing-list subscription is confirmed, for a list that asked
    for confirmation and has sent nothing since.

    Mailchimp sends a "you're confirmed" message only if the list owner turned
    it on (J&G has not), so a confirmed list can sit amber until its next
    newsletter. This clears that. Real mail still arriving is what turns the
    chip green on its own.
    """
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such site.")
    site.newsletter_confirmed_at = utcnow()
    audit.record(
        session,
        actor=admin,
        action=audit.SITE_NEWSLETTER_CONFIRMED,
        target_type="site",
        target_id=site.id,
        target_label=site.name,
        ip_address=client_address(request),
    )
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
