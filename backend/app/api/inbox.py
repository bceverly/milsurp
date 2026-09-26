"""The vendor-mailing-list reader: its switch, its cadence, and "check now".

Administrator-only. The account and its password stay in config.yaml; this is
policy (whether, how often) and a view of what has arrived. See
``app/services/inbox.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import AdminUser, AppConfig, DbSession
from ..models import Site
from ..schemas import (
    EmailListingOut,
    InboxSettingsOut,
    InboxSettingsUpdate,
    InboxStateOut,
    ShopLinkStatusOut,
    VendorEmailOut,
)
from ..scrapers import get_scraper_class
from ..services import inbox

router = APIRouter(prefix="/admin/inbox", tags=["inbox"])


def _state(session: DbSession, config: AppConfig) -> InboxStateOut:
    mail = config.email
    return InboxStateOut(
        settings=InboxSettingsOut.model_validate(inbox.settings(session), from_attributes=True),
        configured=bool(mail.username and mail.password),
        checking=inbox.is_checking(),
        account=mail.username,
        interval_choices=list(inbox.ALLOWED_INTERVAL_HOURS),
        recent=[
            VendorEmailOut(
                site_id=row.site_id,
                site_name=row.site.name if row.site else None,
                from_address=row.from_address,
                subject=row.subject,
                asks_to_confirm=row.asks_to_confirm,
                received_at=row.received_at,
                links_followed=(
                    sum(1 for link in row.links if link.url) if row.links_read_at else None
                ),
                listings=[
                    EmailListingOut(
                        item_id=link.item.id, title=link.item.title, outcome=link.outcome
                    )
                    for link in row.links
                    if link.item is not None
                ][:5],
            )
            for row in inbox.recent(session)
        ],
        shops=_shops(session),
    )


def _shops(session: DbSession) -> list[ShopLinkStatusOut]:
    """Every shop with a mailing list, followed ones first, then by name."""
    status = inbox.link_status(session)
    order = {"unresolved": 0, "followed": 1, "waiting": 2}
    rows = []
    for site in session.execute(select(Site).order_by(Site.name)).scalars():
        scraper = get_scraper_class(site.slug)
        if scraper is None or not scraper.newsletter_url:
            continue
        found = status.get(site.id) or inbox.LinkStatus(state="waiting")
        rows.append(
            ShopLinkStatusOut(
                site_id=site.id,
                site_name=site.name,
                state=found.state,
                emails=found.emails,
                followed=found.followed,
                services=list(found.services),
            )
        )
    return sorted(rows, key=lambda row: order.get(row.state, 3))


@router.get("", response_model=InboxStateOut)
def read_inbox(_admin: AdminUser, session: DbSession, config: AppConfig) -> InboxStateOut:
    return _state(session, config)


@router.patch("", response_model=InboxStateOut)
def update_inbox(
    payload: InboxSettingsUpdate, _admin: AdminUser, session: DbSession, config: AppConfig
) -> InboxStateOut:
    row = inbox.settings(session)
    if payload.interval_hours is not None:
        if payload.interval_hours not in inbox.ALLOWED_INTERVAL_HOURS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"interval_hours must be one of {list(inbox.ALLOWED_INTERVAL_HOURS)}",
            )
        row.interval_hours = payload.interval_hours
    if payload.enabled is not None:
        row.enabled = payload.enabled
    session.commit()
    return _state(session, config)


@router.post("/check", response_model=InboxStateOut, status_code=status.HTTP_202_ACCEPTED)
def check_inbox(_admin: AdminUser, session: DbSession, config: AppConfig) -> InboxStateOut:
    """Start a check now, whatever the schedule says, and even with it off.

    Started, not run: following an inbox's links takes minutes and the proxy
    in front of the app times a request out long before that (see
    ``inbox.start_check``). The response says ``checking``; the page polls
    until it is done. The outcome is recorded on the settings row, so a wrong
    password reads as that rather than as a quiet week.
    """
    inbox.start_check(config)
    return _state(session, config)
