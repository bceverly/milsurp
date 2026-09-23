"""Hot deals: what is cheap for what it is, and who hears about it.

One endpoint answers the whole page -- the deals, the tab counts, the reader's
own subscription, and for an administrator the settings behind it. A page that
had to make four requests to render once would spend most of its life in three
different half-loaded states, and the parts are cheap: the deals are a read of
a table a scheduled pass already computed.

**Signed-in, not admin-only.** It is a reader's page. The settings panel inside
it is the administrator's, and the response simply leaves ``settings`` null for
everybody else rather than making the page work out the role for itself.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..deps import AdminUser, AppConfig, CurrentUser, DbSession
from ..models import HotDealPreference, Site
from ..schemas import (
    HotDealOut,
    HotDealPreferenceOut,
    HotDealPreferenceUpdate,
    HotDealSettingsOut,
    HotDealSettingsUpdate,
    HotDealsOut,
)
from ..services import hotdeals

router = APIRouter(prefix="/hot-deals", tags=["hot-deals"])

#: Cadences the page offers. Free text invites "1", which is a full pass over
#: the catalog every hour to answer a question whose inputs move once a day.
ALLOWED_INTERVAL_HOURS = (4, 6, 8, 12, 24, 48)

#: The bounds the thresholds may be set within.
#:
#: Not taste -- each end is a measured cliff. Below 50 the "deal" is the
#: cheaper half of a group, which is not news. A floor under 5% admits listings
#: a rounding error below the median. And the ceiling exists at all because
#: past about 65% the listing stops being the same object as its peers -- a
#: magazine, a bolt, a bare frame, a replica -- so allowing 100 would be
#: offering to turn the guard off, which is a thing somebody would do once and
#: not understand the result of.
LIMITS = {
    "min_cheaper_than": (50, 99),
    "min_discount_percent": (5, 60),
    "max_discount_percent": (25, 90),
    "min_vendors": (1, 5),
}


def _preference_out(session: DbSession, user: CurrentUser) -> HotDealPreferenceOut:
    """This reader's subscription, with a missing row read as the default.

    No row means all three categories and switched on. Creating one here just
    to read it would throw that away -- the absence is what gives every
    existing account the feature without a backfill.
    """
    row = session.execute(
        select(HotDealPreference).where(HotDealPreference.user_id == user.id)
    ).scalar_one_or_none()
    saved = hotdeals.saved_search_count(session, user)
    if row is None:
        return HotDealPreferenceOut(
            enabled=True,
            include_rifles=True,
            include_handguns=True,
            include_police_surplus=True,
            saved_searches=saved,
        )
    out = HotDealPreferenceOut.model_validate(row, from_attributes=True)
    out.saved_searches = saved
    return out


def _state(
    session: DbSession,
    user: CurrentUser,
    bucket: str | None,
    limit: int,
    sort: str = hotdeals.DEFAULT_SORT,
) -> HotDealsOut:
    # The same serializer the browse list uses, imported where it is needed
    # rather than at the top: api.items imports plenty, and a module-level
    # import between two routers is how an import cycle starts. The watchlist
    # router reaches for it the same way.
    from .items import _to_out

    rows = hotdeals.deals(session, bucket, sort=sort, limit=limit)
    site_names = {
        site.id: site.name
        for site in session.execute(
            select(Site).where(Site.id.in_({deal.item.site_id for deal in rows}))
        )
        .scalars()
        .all()
    }
    return HotDealsOut(
        bucket=bucket,
        sort=sort,
        deals=[
            HotDealOut(
                item=_to_out(deal.item, site_names),
                bucket=deal.bucket,
                bucket_label=hotdeals.label(deal.bucket),
                price=deal.price,
                median_price=deal.median_price,
                discount_percent=deal.discount_percent,
                cheaper_than=deal.cheaper_than,
                peer_count=deal.peer_count,
                vendor_count=deal.vendor_count,
                duplicate_count=deal.duplicate_count,
                first_listed_at=deal.first_listed_at,
            )
            for deal in rows
        ],
        counts=hotdeals.counts(session),
        labels=dict(hotdeals.BUCKET_LABELS),
        buckets=list(hotdeals.BUCKETS),
        sorts=list(hotdeals.SORT_SEQUENCE),
        sort_labels=dict(hotdeals.SORT_LABELS),
        preference=_preference_out(session, user),
        settings=(
            HotDealSettingsOut.model_validate(hotdeals.settings(session), from_attributes=True)
            if user.is_admin
            else None
        ),
        interval_choices=list(ALLOWED_INTERVAL_HOURS) if user.is_admin else None,
    )


def _checked(bucket: str | None, sort: str | None) -> tuple[str | None, str]:
    """The view being asked for, refused loudly if it is not one that exists.

    A 422 rather than a silent fallback, for both of them and for the same
    reason: a page asking for a category or an order that does not exist has a
    bug, and answering it with the default hides that bug behind a result that
    looks perfectly plausible.
    """
    if bucket is not None and hotdeals.known_bucket(bucket) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown category. Valid: {', '.join(hotdeals.BUCKETS)}.",
        )
    if sort is not None and hotdeals.known_sort(sort) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown sort. Valid: {', '.join(hotdeals.SORT_SEQUENCE)}.",
        )
    return bucket, sort or hotdeals.DEFAULT_SORT


#: Why every write takes the reader's current view as query parameters.
#:
#: Each of them answers with the whole page, which is what lets the page never
#: reload -- the response *is* the new state. That only works if the response
#: describes the view the reader is actually looking at: answering a checkbox
#: on the Rifles tab with the whole catalog in the default order would reset
#: the list under them and leave the tab and the sort box describing something
#: that is no longer on screen.
_VIEW = "the category and order the reader is currently looking at"


@router.get("", response_model=HotDealsOut)
def read_hot_deals(
    user: CurrentUser,
    session: DbSession,
    bucket: str | None = Query(default=None),
    sort: str | None = Query(default=None, description=_VIEW),
    limit: int = Query(default=200, ge=1, le=500),
) -> HotDealsOut:
    """Every current deal, or one category's worth, deepest discount first.

    The order is applied in the database, before ``limit``, so asking for the
    cheapest returns the cheapest deals rather than the cheapest of the two
    hundred deepest discounts.
    """
    bucket, sort = _checked(bucket, sort)
    return _state(session, user, bucket, limit, sort)


@router.patch("/preference", response_model=HotDealsOut)
def update_preference(
    payload: HotDealPreferenceUpdate,
    user: CurrentUser,
    session: DbSession,
    bucket: str | None = Query(default=None, description=_VIEW),
    sort: str | None = Query(default=None, description=_VIEW),
) -> HotDealsOut:
    """Change this reader's subscription. Creates the row on first change."""
    bucket, sort = _checked(bucket, sort)
    row = hotdeals.preference(session, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, field, value)
    session.commit()
    return _state(session, user, bucket, 200, sort)


@router.patch("/settings", response_model=HotDealsOut)
def update_settings(
    payload: HotDealSettingsUpdate,
    admin: AdminUser,
    session: DbSession,
    bucket: str | None = Query(default=None, description=_VIEW),
    sort: str | None = Query(default=None, description=_VIEW),
) -> HotDealsOut:
    bucket, sort = _checked(bucket, sort)
    row = hotdeals.settings(session)
    data = payload.model_dump(exclude_unset=True)

    if data.get("interval_hours") is not None:
        if data["interval_hours"] not in ALLOWED_INTERVAL_HOURS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"interval_hours must be one of {list(ALLOWED_INTERVAL_HOURS)}",
            )
        row.interval_hours = data["interval_hours"]

    for field, (low, high) in LIMITS.items():
        value = data.get(field)
        if value is None:
            continue
        if not low <= value <= high:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{field} must be between {low} and {high}"
            )
        setattr(row, field, value)

    if data.get("enabled") is not None:
        row.enabled = data["enabled"]

    # Checked after the assignments rather than against the payload, because
    # the page sends only what changed: raising the floor above a ceiling that
    # is staying put is the same mistake and arrives as one field.
    if row.min_discount_percent >= row.max_discount_percent:
        session.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The smallest discount must be below the largest; as sent they would "
            "select nothing at all.",
        )

    session.commit()
    return _state(session, admin, bucket, 200, sort)


@router.post("/refresh", response_model=HotDealsOut)
def refresh_now(
    admin: AdminUser,
    session: DbSession,
    _config: AppConfig,
    bucket: str | None = Query(default=None, description=_VIEW),
    sort: str | None = Query(default=None, description=_VIEW),
) -> HotDealsOut:
    """Re-read the catalog now, whatever the schedule says.

    Runs even when the schedule is switched off, for the reason "Back up now"
    does: somebody asking for it is reason enough, and switched-off is the
    state it is most useful in -- thresholds just changed, and nobody wants to
    wait eight hours to see what they did.

    **It does not send any email.** A pass triggered by a person adjusting a
    slider is not a reason to mail everybody, and an administrator trying three
    settings in a minute would otherwise send three rounds of it.
    """
    bucket, sort = _checked(bucket, sort)
    try:
        hotdeals.refresh(session)
    except Exception as exc:
        hotdeals.record_failure(session, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"The hot deals pass failed: {exc}"
        ) from exc
    return _state(session, admin, bucket, 200, sort)
