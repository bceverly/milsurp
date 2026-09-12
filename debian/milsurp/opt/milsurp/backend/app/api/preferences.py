"""Per-user email digest settings, plus admin delivery history."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..deps import AdminUser, AppConfig, CurrentUser, DbSession
from ..models import EmailLog, EmailPreference, EmailPreferenceSite, Site, User
from ..schemas import EmailBodyOut, EmailLogOut, EmailPreferenceOut, EmailPreferenceUpdate
from ..services import digest, mailer

router = APIRouter(tags=["preferences"])


def _get_or_create(session: DbSession, user: User) -> EmailPreference:
    preference = (
        session.execute(select(EmailPreference).where(EmailPreference.user_id == user.id))
        .scalars()
        .first()
    )
    if preference is None:
        preference = EmailPreference(user_id=user.id)
        session.add(preference)
        session.commit()
    return preference


def _to_out(preference: EmailPreference) -> EmailPreferenceOut:
    data = EmailPreferenceOut.model_validate(preference)
    data.site_ids = preference.site_ids
    return data


@router.get("/preferences/email", response_model=EmailPreferenceOut)
def get_preferences(user: CurrentUser, session: DbSession) -> EmailPreferenceOut:
    return _to_out(_get_or_create(session, user))


@router.put("/preferences/email", response_model=EmailPreferenceOut)
def update_preferences(
    payload: EmailPreferenceUpdate, user: CurrentUser, session: DbSession
) -> EmailPreferenceOut:
    preference = _get_or_create(session, user)

    if payload.display_timezone is not None:
        try:
            ZoneInfo(payload.display_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown timezone {payload.display_timezone!r}.",
            ) from exc
        preference.display_timezone = payload.display_timezone

    was_enabled = preference.enabled

    for field in (
        "enabled",
        "frequency_hours",
        "include_new_items",
        "new_items_per_site_limit",
        "include_price_drops",
        "price_drops_per_site_limit",
        "minimum_price_drop",
        "skip_when_empty",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(preference, field, value)

    if payload.site_ids is not None:
        valid = set(session.execute(select(Site.id)).scalars().all())
        unknown = [sid for sid in payload.site_ids if sid not in valid]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown site id(s): {', '.join(map(str, unknown))}.",
            )
        # Replace the selection wholesale. An empty list is meaningful: it
        # means "every enabled site", including ones added later.
        for link in list(preference.sites):
            session.delete(link)
        session.flush()
        for site_id in dict.fromkeys(payload.site_ids):
            session.add(EmailPreferenceSite(preference_id=preference.id, site_id=site_id))

    if preference.enabled:
        # Turning digests on, or changing the cadence, re-bases the schedule
        # from now rather than from a stale timestamp.
        if not was_enabled or payload.frequency_hours is not None:
            preference.next_send_at = digest.next_send_time(preference)
    else:
        preference.next_send_at = None

    session.commit()
    # The session is created with expire_on_commit=False, so the `sites`
    # relationship still holds the pre-commit rows; refresh before reading it
    # back or a just-saved selection reads as empty.
    session.refresh(preference)
    return _to_out(preference)


@router.post("/preferences/email/test", status_code=status.HTTP_202_ACCEPTED)
def send_test_digest(user: CurrentUser, session: DbSession, config: AppConfig) -> dict[str, str]:
    """Send the user their digest right now, even if it would be empty."""
    if not config.email.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is disabled in the server configuration (email.enabled).",
        )
    _get_or_create(session, user)
    session.refresh(user)
    result = digest.send_digest_for_user(session, user, config, force=True)
    if result.status.value == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.error_message or "Delivery failed.",
        )
    return {
        "message": f"Digest sent to {user.email}.",
        "new_items": str(result.new_item_count),
        "price_drops": str(result.price_drop_count),
    }


def _log_out(entry: EmailLog) -> EmailLogOut:
    """One row for the history table, without the message it carries."""
    item = EmailLogOut.model_validate(entry)
    item.has_body = bool(entry.body_html or entry.body_text)
    return item


@router.get("/preferences/email/history", response_model=list[EmailLogOut])
def my_email_history(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=25, ge=1, le=200),
) -> list[EmailLogOut]:
    logs = (
        session.execute(
            select(EmailLog)
            .where(EmailLog.user_id == user.id)
            .order_by(EmailLog.sent_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_log_out(entry) for entry in logs]


@router.get("/preferences/email/history/{log_id}", response_model=EmailBodyOut)
def my_email_body(
    log_id: int,
    user: CurrentUser,
    session: DbSession,
) -> EmailBodyOut:
    """The message itself, fetched only when somebody asks to read one.

    Scoped to the signed-in user's own messages. A digest names the sites
    somebody follows and what they are watching for, so another account's copy
    is not theirs to read — an admin reads it through the admin route, which
    says so in its path.
    """
    entry = session.get(EmailLog, log_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such message.")
    return EmailBodyOut.model_validate(entry)


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------
@router.get("/admin/email/history", response_model=list[EmailLogOut])
def all_email_history(
    _admin: AdminUser,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[EmailLogOut]:
    rows = session.execute(
        select(EmailLog, User.username)
        .join(User, User.id == EmailLog.user_id)
        .order_by(EmailLog.sent_at.desc())
        .limit(limit)
    ).all()
    out = []
    for entry, username in rows:
        item = _log_out(entry)
        item.username = username
        out.append(item)
    return out


@router.get("/admin/email/history/{log_id}", response_model=EmailBodyOut)
def any_email_body(log_id: int, _admin: AdminUser, session: DbSession) -> EmailBodyOut:
    """Any user's message, for an admin working out a delivery problem."""
    entry = session.get(EmailLog, log_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such message.")
    return EmailBodyOut.model_validate(entry)


@router.post("/admin/email/test-connection")
def check_smtp_connection(_admin: AdminUser, config: AppConfig) -> dict[str, str]:
    """Verify the SMTP settings without sending anything."""
    try:
        message = mailer.verify_connection(config)
    except mailer.MailError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"message": message}
