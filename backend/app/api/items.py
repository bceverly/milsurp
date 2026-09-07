"""Browsing the collected inventory."""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import Select, func, or_, select, true
from sqlalchemy.orm import selectinload

from ..deps import AppConfig, CurrentUser, DbSession
from ..models import Item, ItemPhoto, PriceHistory, Site, utcnow
from ..schemas import (
    FacetValue,
    ItemDetail,
    ItemFacets,
    ItemOut,
    ItemPage,
    PhotoOut,
    PricePointOut,
)
from ..services.image_store import ImageStore, ImageStoreError

router = APIRouter(prefix="/items", tags=["items"])

SORTS: dict[str, tuple[Any, ...]] = {
    "newest": (Item.first_seen_at.desc(), Item.id.desc()),
    "oldest": (Item.first_seen_at.asc(), Item.id.asc()),
    "price_asc": (Item.current_price.is_(None).asc(), Item.current_price.asc()),
    "price_desc": (Item.current_price.is_(None).asc(), Item.current_price.desc()),
    "title": (Item.title.asc(),),
    "price_drop": (Item.price_changed_at.desc(),),
}


#: Terms shorter than this match too much to be useful.
MIN_SEARCH_TERM = 2
#: Cap the term count so a pathological query cannot build a huge WHERE clause.
MAX_SEARCH_TERMS = 8

_PHRASE_RE = re.compile(r'"([^"]+)"')


def _search_terms(search: str) -> list[str]:
    """Split a query into terms, honoring double-quoted phrases."""
    remainder = search.strip()
    terms: list[str] = []
    for phrase in _PHRASE_RE.findall(remainder):
        cleaned = phrase.strip()
        if cleaned:
            terms.append(cleaned)
    remainder = _PHRASE_RE.sub(" ", remainder)
    terms.extend(word for word in remainder.split() if len(word) >= MIN_SEARCH_TERM)
    return terms[:MAX_SEARCH_TERMS]


def _photo_version(photo: ItemPhoto) -> str:
    """A short token that changes whenever a photo's bytes change.

    Photo URLs are built from two database ids, and neither is a stable name
    for its content: SQLite reuses a rowid after a delete, so clearing a site
    and re-scanning it hands the very same URL to a different picture. Every
    browser that had seen the old one then kept showing it — listings appearing
    under each other's photographs, and no amount of reloading fixed it,
    because the URL genuinely had not changed.

    The stored filename is not enough on its own: it hashes the image's
    *source*, and a scraper that generates its own images keeps the source key
    deliberately stable while the bytes change. The size and the time it was
    stored move whenever the file is rewritten, so they are included.
    """
    material = f"{photo.filename}|{photo.bytes}|{photo.downloaded_at}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _photo_urls(item_id: int, photo: ItemPhoto) -> tuple[str, str]:
    """The full and thumbnail URLs for one photo, both content-versioned."""
    base = f"/api/items/{item_id}/photos/{photo.id}"
    version = _photo_version(photo)
    return f"{base}?v={version}", f"{base}?size=thumb&v={version}"


def _thumbnail_url(item: Item) -> str | None:
    """Point at the authenticated photo endpoint, never at a vendor URL.

    The list view always asks for the ``thumb`` variant; the endpoint falls
    back to the full image when a thumbnail was never generated.
    """
    for photo in item.photos:
        if photo.filename:
            return _photo_urls(item.id, photo)[1]
    return None


#: How much description the list view is given. Generous enough to tell two
#: near-identical Mosin-Nagants apart, which is the whole point of that view.
BLURB_CHARS = 280


def _blurb(description: str | None) -> str | None:
    """The opening of a description, on a word boundary, or None."""
    text = " ".join((description or "").split())
    if not text:
        return None
    if len(text) <= BLURB_CHARS:
        return text
    cut = text[:BLURB_CHARS]
    # Back up to the last space so the blurb never ends mid-word; if there is
    # no space at all, the hard cut is the only option.
    space = cut.rfind(" ")
    return f"{cut[:space] if space > 0 else cut}…"


def _to_out(item: Item, site_names: dict[int, str]) -> ItemOut:
    data = ItemOut.model_validate(item)
    data.site_name = site_names.get(item.site_id)
    data.thumbnail_url = _thumbnail_url(item)
    data.price_drop = item.price_drop_amount
    data.blurb = _blurb(item.description)
    return data


def _apply_filters(  # noqa: PLR0912 - one branch per filter; splitting it
    #                                      would only scatter the same logic
    stmt: Select,
    *,
    site_ids: list[int] | None,
    categories: list[str] | None,
    calibers: list[str] | None,
    countries: list[str] | None,
    manufacturers: list[str] | None,
    kinds: list[str] | None,
    availability: str,
    search: str | None,
    min_price: float | None,
    max_price: float | None,
    new_since_hours: int | None,
    price_drops_only: bool,
) -> Select:
    if site_ids:
        stmt = stmt.where(Item.site_id.in_(site_ids))
    if categories:
        stmt = stmt.where(Item.category.in_(categories))
    if calibers:
        stmt = stmt.where(_matching(Item.caliber, calibers))
    if countries:
        stmt = stmt.where(_matching(Item.country, countries))
    if manufacturers:
        stmt = stmt.where(_matching(Item.manufacturer, manufacturers))

    if kinds:
        # "rifle"/"pistol" are independent booleans, not one column, because a
        # listing can be neither (an accessory) and occasionally reads as both.
        clauses: list[Any] = []
        if "rifle" in kinds:
            clauses.append(Item.is_rifle.is_(True))
        if "pistol" in kinds:
            clauses.append(Item.is_pistol.is_(True))
        if "bayonet" in kinds:
            clauses.append(Item.is_bayonet.is_(True))
        if "parts_kit" in kinds:
            clauses.append(Item.is_parts_kit.is_(True))
        if "other" in kinds:
            # Everything the named kinds do not claim, so "Parts & accessories"
            # stops meaning "including the bayonets and kits listed above it".
            clauses.append(
                (Item.is_rifle.is_(False))
                & (Item.is_pistol.is_(False))
                & (Item.is_bayonet.is_(False))
                & (Item.is_parts_kit.is_(False))
            )
        if clauses:
            stmt = stmt.where(or_(*clauses))

    if availability == "available":
        stmt = stmt.where(Item.is_active.is_(True), Item.is_sold.is_(False))
    elif availability == "sold":
        stmt = stmt.where(Item.is_sold.is_(True))
    elif availability == "delisted":
        stmt = stmt.where(Item.is_active.is_(False))
    elif availability == "active":
        stmt = stmt.where(Item.is_active.is_(True))
    # "all" applies no availability filter at all.

    if search:
        # Every term must appear somewhere in the listing, but they may land in
        # different fields -- so "enfield 303" matches a rifle whose title says
        # Enfield and whose caliber says .303 British. A phrase in double
        # quotes is kept together.
        for term in _search_terms(search):
            escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            pattern = f"%{escaped}%"
            stmt = stmt.where(
                or_(
                    Item.title.like(pattern, escape="!"),
                    Item.description.like(pattern, escape="!"),
                    Item.caliber.like(pattern, escape="!"),
                    Item.manufacturer.like(pattern, escape="!"),
                    Item.country.like(pattern, escape="!"),
                    Item.category.like(pattern, escape="!"),
                )
            )

    if min_price is not None:
        stmt = stmt.where(Item.current_price.is_not(None), Item.current_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Item.current_price.is_not(None), Item.current_price <= max_price)

    if new_since_hours:
        stmt = stmt.where(Item.first_seen_at >= utcnow() - timedelta(hours=new_since_hours))

    if price_drops_only:
        stmt = stmt.where(
            Item.previous_price.is_not(None),
            Item.current_price.is_not(None),
            Item.current_price < Item.previous_price,
        )
    return stmt


#: What the filter calls a field nothing could be worked out for. Chosen to be
#: a word no vendor would use as a name; if one ever does, it will share the
#: bucket, which is a smaller problem than storing this in the column.
UNKNOWN = "Unknown"


def _matching(column, wanted: list[str]):
    """A filter clause where "Unknown" means "this field is empty"."""
    chosen = [value for value in wanted if value != UNKNOWN]
    clauses = []
    if chosen:
        clauses.append(column.in_(chosen))
    if UNKNOWN in wanted:
        clauses.append(or_(column.is_(None), column == ""))
    return or_(*clauses) if clauses else true()


def _facets(session: DbSession, base: Select) -> ItemFacets:
    """Counts for the filter sidebar, computed over the current result set."""

    def tally(column, limit: int = 40) -> list[FacetValue]:
        stmt = (
            base.with_only_columns(column, func.count(Item.id))
            .where(column.is_not(None), column != "")
            .group_by(column)
            .order_by(func.count(Item.id).desc())
            .limit(limit)
        )
        found = [
            FacetValue(value=str(value), count=int(count))
            for value, count in session.execute(stmt).all()
        ]

        # And a bucket for the ones nothing could be worked out for. Listed
        # last however many there are, because it is not an answer and should
        # not sit at the top of the list looking like one.
        #
        # The column stays NULL in the database: "Unknown" is this view's word
        # for it, not a value. Writing the string into the row would make it
        # indistinguishable from a vendor of that name, and would quietly stop
        # every "fill in the blanks" rule in the application, all of which key
        # on the field being empty.
        missing = session.execute(
            base.with_only_columns(func.count(Item.id)).where(or_(column.is_(None), column == ""))
        ).scalar_one()
        if missing:
            found.append(FacetValue(value=UNKNOWN, count=int(missing)))
        return found

    site_rows = session.execute(
        base.with_only_columns(Site.id, Site.name, func.count(Item.id))
        .join(Site, Site.id == Item.site_id)
        .group_by(Site.id, Site.name)
        .order_by(Site.name)
    ).all()
    total = session.execute(base.with_only_columns(func.count(Item.id))).scalar_one()

    return ItemFacets(
        sites=[
            FacetValue(value=str(sid), label=name, count=int(count))
            for sid, name, count in site_rows
        ],
        categories=tally(Item.category),
        calibers=tally(Item.caliber),
        countries=tally(Item.country),
        manufacturers=tally(Item.manufacturer),
        total=int(total),
    )


@router.get("", response_model=ItemPage)
def list_items(
    _user: CurrentUser,
    session: DbSession,
    site_id: list[int] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    caliber: list[str] | None = Query(default=None),
    country: list[str] | None = Query(default=None),
    manufacturer: list[str] | None = Query(default=None),
    kind: list[str] | None = Query(
        default=None, description="rifle | pistol | bayonet | parts_kit | other"
    ),
    availability: str = Query(default="available"),
    search: str | None = Query(default=None, max_length=200),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    new_since_hours: int | None = Query(default=None, ge=1, le=8760),
    price_drops_only: bool = Query(default=False),
    sort: str = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=48, ge=1, le=200),
    include_facets: bool = Query(default=True),
) -> ItemPage:
    if sort not in SORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown sort {sort!r}. Valid: {', '.join(SORTS)}.",
        )

    base = _apply_filters(
        select(Item),
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        kinds=kind,
        availability=availability,
        search=search,
        min_price=min_price,
        max_price=max_price,
        new_since_hours=new_since_hours,
        price_drops_only=price_drops_only,
    )

    total = session.execute(base.with_only_columns(func.count(Item.id))).scalar_one()
    stmt = (
        base.options(selectinload(Item.photos))
        .order_by(*SORTS[sort])
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = session.execute(stmt).scalars().unique().all()

    site_names: dict[int, str] = {
        row[0]: row[1] for row in session.execute(select(Site.id, Site.name)).all()
    }
    pages = max(1, -(-int(total) // per_page))  # ceiling division

    return ItemPage(
        items=[_to_out(item, site_names) for item in items],
        total=int(total),
        page=page,
        per_page=per_page,
        pages=pages,
        facets=_facets(session, base) if include_facets else None,
    )


@router.get("/{item_id}", response_model=ItemDetail)
def get_item(item_id: int, _user: CurrentUser, session: DbSession) -> ItemDetail:
    item = (
        session.execute(
            select(Item)
            .options(selectinload(Item.photos), selectinload(Item.prices))
            .where(Item.id == item_id)
        )
        .scalars()
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such item.")

    site = session.get(Site, item.site_id)
    site_names = {item.site_id: site.name} if site else {}
    # Built from the list shape rather than validated straight off the ORM
    # object: `photos` and `price_history` are computed API views (they carry
    # endpoint URLs, not columns), so letting Pydantic read the relationships
    # would try to coerce ItemPhoto rows into PhotoOut and fail.
    detail = ItemDetail(
        **_to_out(item, site_names).model_dump(),
        description=item.description,
    )
    detail.photos = [
        PhotoOut(
            id=photo.id,
            position=photo.position,
            url=_photo_urls(item.id, photo)[0],
            thumbnail_url=_photo_urls(item.id, photo)[1],
            width=photo.width,
            height=photo.height,
        )
        for photo in item.photos
        if photo.filename
    ]
    detail.price_history = [PricePointOut.model_validate(point) for point in item.prices]
    return detail


@router.get("/{item_id}/prices", response_model=list[PricePointOut])
def price_history(item_id: int, _user: CurrentUser, session: DbSession) -> list[PricePointOut]:
    """Full price-over-time series for one listing, oldest first."""
    if session.get(Item, item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such item.")
    points = (
        session.execute(
            select(PriceHistory)
            .where(PriceHistory.item_id == item_id)
            .order_by(PriceHistory.observed_at.asc())
        )
        .scalars()
        .all()
    )
    return [PricePointOut.model_validate(point) for point in points]


@router.get("/{item_id}/photos/{photo_id}")
def get_photo(
    item_id: int,
    photo_id: int,
    _user: CurrentUser,
    session: DbSession,
    config: AppConfig,
    size: str = Query(default="full", pattern="^(full|thumb)$"),
) -> Response:
    """Stream a stored photo at the requested resolution.

    Images live in a 0700 directory outside the web root and are never served as
    static files, so this endpoint is the only way to reach one -- and it
    requires a valid session.
    """
    photo = session.get(ItemPhoto, photo_id)
    if photo is None or photo.item_id != item_id or not photo.filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such photo.")

    # Fall back to the full image for photos stored before thumbnails existed,
    # and for images that were already small enough not to need one.
    relative = photo.filename
    media_type = photo.content_type or "image/jpeg"
    if size == "thumb" and photo.thumb_filename:
        relative = photo.thumb_filename
        media_type = "image/jpeg" if relative.endswith(".jpg") else media_type

    store = ImageStore(config)
    try:
        path = store.absolute_path(relative)
    except ImageStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo is unavailable."
        ) from exc
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo has not been downloaded yet.",
        )

    return FileResponse(
        path,
        media_type=photo.content_type or "image/jpeg",
        headers={
            # Revalidated every time, and belt-and-braces at that: the URL now
            # carries a token derived from the file, so a changed image is a
            # changed URL and a stale copy can never be matched to it. The
            # revalidation stays because a cache that already holds one of the
            # old, unversioned URLs has no other way to find out.
            #
            # This used to be `max-age=86400` on the reasoning that the content
            # was immutable because the stored filename is a hash. The filename
            # is a hash of the image's *source*, not of its bytes, and this URL
            # is neither: it is /items/<id>/photos/<id>, and both of those ids
            # are reused by SQLite after a delete. So a site that is cleared and
            # re-scanned hands the same URL to different content, and every
            # browser that had looked at the old one showed it for another
            # day — listings appearing under each other's photographs.
            #
            # FileResponse already sends an ETag and Last-Modified derived from
            # the file, so revalidating costs a 304 and no image bytes.
            "Cache-Control": "private, no-cache",
        },
    )
