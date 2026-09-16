"""A week in review of the catalog, for everybody.

Distinct from the per-user digest in the way that matters: no preferences are
applied, nothing is filtered to somebody's sites or price floor, and every
signed-in user gets the same answer. See :mod:`app.services.changes` for what
it carries and why.

Signed-in rather than admin-only. The parts an operator reads it for -- a shop
that went quiet, a scan that failed -- are also the parts that explain to
everybody else why a favorite shop has had nothing new for a fortnight.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..deps import CurrentUser, DbSession
from ..schemas import ChangeHighlightOut, ChangeSiteOut, ChangesOut
from ..services import changes

router = APIRouter(prefix="/changes", tags=["changes"])


def _highlight(entry: changes.Highlight) -> ChangeHighlightOut:
    return ChangeHighlightOut(
        item_id=entry.item_id,
        title=entry.title,
        site_name=entry.site_name,
        url=entry.url,
        currency=entry.currency,
        price=entry.price,
        was=entry.was,
        drop=entry.drop,
        drop_percent=entry.drop_percent,
    )


@router.get("", response_model=ChangesOut)
def week_in_review(
    _user: CurrentUser,
    session: DbSession,
    days: int = Query(default=changes.DEFAULT_DAYS, ge=1, le=changes.MAX_DAYS),
) -> ChangesOut:
    """What changed across every site in the last *days* days."""
    week = changes.summarize(session, days=days)
    return ChangesOut(
        since=week.since,
        until=week.until,
        days=week.days,
        added=week.added,
        sold=week.sold,
        delisted=week.delisted,
        reduced=week.reduced,
        active_now=week.active_now,
        total_reduction=week.total_reduction,
        sites=[
            ChangeSiteOut(
                site_id=site.site_id,
                slug=site.slug,
                name=site.name,
                enabled=site.enabled,
                added=site.added,
                sold=site.sold,
                delisted=site.delisted,
                reduced=site.reduced,
                active=site.active,
                failed_scans=site.failed_scans,
                last_success_at=site.last_success_at,
                silent=site.silent,
            )
            for site in week.sites
        ],
        biggest_drops=[_highlight(entry) for entry in week.biggest_drops],
        arrivals=[_highlight(entry) for entry in week.arrivals],
        new_calibers=week.new_calibers,
        new_countries=week.new_countries,
        new_manufacturers=week.new_manufacturers,
    )
