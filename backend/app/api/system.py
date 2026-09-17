"""Health and system status."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from .. import __version__
from ..deps import AdminUser, AppConfig, CurrentUser, DbSession
from ..models import EmailLog, Item, ScanRun, Site, User
from ..scheduler import get_scheduler
from ..schemas import AuditEventOut, HealthOut, PolicyOut, SystemStatusOut
from ..security import password_requirements
from ..services import armoryundo, audit
from ..services.image_store import ImageStore

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut)
def health(config: AppConfig) -> HealthOut:
    """Unauthenticated liveness probe, used by nginx and systemd."""
    return HealthOut(
        status="ok",
        version=__version__,
        mode=config.mode,
        server_time=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


@router.get("/policy", response_model=PolicyOut)
def policy(_user: CurrentUser, config: AppConfig) -> PolicyOut:
    """Policy the client needs in order to validate input up front.

    Read from the live configuration on every request, so raising
    `security.min_password_length` and restarting is reflected in the UI
    without a rebuild.
    """
    return PolicyOut(
        password_min_length=config.security.min_password_length,
        password_require_uppercase=config.security.require_uppercase,
        password_require_lowercase=config.security.require_lowercase,
        password_require_numeric=config.security.require_numeric,
        password_require_special=config.security.require_special,
        password_requirements=password_requirements(config),
    )


@router.get("/admin/status", response_model=SystemStatusOut)
def system_status(_admin: AdminUser, session: DbSession, config: AppConfig) -> SystemStatusOut:
    counts = {
        "users": session.execute(select(func.count(User.id))).scalar_one(),
        "sites": session.execute(select(func.count(Site.id))).scalar_one(),
        "sites_enabled": session.execute(
            select(func.count(Site.id)).where(Site.enabled.is_(True))
        ).scalar_one(),
        "items": session.execute(select(func.count(Item.id))).scalar_one(),
        "items_active": session.execute(
            select(func.count(Item.id)).where(Item.is_active.is_(True))
        ).scalar_one(),
        "scan_runs": session.execute(select(func.count(ScanRun.id))).scalar_one(),
        "emails_sent": session.execute(select(func.count(EmailLog.id))).scalar_one(),
    }
    return SystemStatusOut(
        version=__version__,
        mode=config.mode,
        config_path=str(config.source_path) if config.source_path else None,
        # Under PostgreSQL this is a DSN without the password, not a path.
        database_path=config.database.describe(),
        database_engine=config.database.engine,
        images_path=str(config.images_path),
        image_bytes=ImageStore(config).usage_bytes(),
        email_enabled=config.email.enabled,
        scheduler=get_scheduler().status(),
        counts={key: int(value) for key, value in counts.items()},
    )


@router.get("/audit", response_model=list[AuditEventOut])
def audit_log(
    _admin: AdminUser,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    action: str | None = Query(default=None),
) -> list[AuditEventOut]:
    """What administrators have done, newest first.

    Admin-only, which is a judgment rather than an obvious call: the log is
    mostly *about* administrators, and showing everyone who changed whose role
    would be a privacy decision made by accident. An account that cannot see
    the Users page has no use for it.
    """
    rows = []
    for event in audit.recent(session, limit=limit, action=action):
        out = AuditEventOut.model_validate(event, from_attributes=True)
        # Answered here rather than by the page guessing from the action name:
        # an event is revertible only if it also recorded what the row held,
        # and everything written before migration 0032 did not. A button that
        # answers with an error is worse than no button.
        out.revertible = (
            event.action in (audit.ARMORY_EDITED, audit.ARMORY_DELETED)
            and bool(event.before_state)
            and event.target_type in armoryundo.REVERTIBLE
        )
        rows.append(out)
    return rows


@router.get("/audit/actions", response_model=list[str])
def audit_actions(_admin: AdminUser, session: DbSession) -> list[str]:
    """The actions that actually appear, for the filter.

    Read from the data rather than from the constants: a filter offering
    actions nothing has ever done is a filter that mostly returns nothing.
    """
    return audit.actions(session)
