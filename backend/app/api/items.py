"""Browsing the collected inventory."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import selectinload

from ..deps import AppConfig, CurrentUser, DbSession
from ..models import FirearmModel, Item, ItemPhoto, PriceHistory, Site
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
from ..services.search import (
    KINDS,
    SORTS,
    UNKNOWN,
    apply_filters,
)

router = APIRouter(prefix="/items", tags=["items"])


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
    # The name only. `firearm_model` on the row is a relationship and the
    # field here is a string -- the same word for two shapes, which is exactly
    # what ManufacturerOut.models got wrong before it was taken out.
    data.model = item.firearm_model.name if item.firearm_model else None
    data.site_name = site_names.get(item.site_id)
    data.thumbnail_url = _thumbnail_url(item)
    data.price_drop = item.price_drop_amount
    data.blurb = _blurb(item.description)
    return data


#: What each value of the "kind" filter selects.
#:
#: "rifle" and "pistol" are independent booleans rather than one column,
#: because a listing can be neither -- an accessory -- and occasionally reads
#: as both. "other" is defined as the absence of all four, so "Other parts &
#: accessories" stops meaning "including the bayonets and kits listed above
#: it", and so that the five counts add up to the whole.
def _kind_counts(session: DbSession, base: Select) -> list[FacetValue]:
    """How many listings each Type would show, over everything else chosen.

    Deliberately not over the current result set like the other facets: with
    the kind filter applied, picking "Rifles" would report zero handguns and
    the numbers would only ever describe the choice already made. Every other
    filter still applies, so the counts say what picking each one would give.

    Read in one pass rather than five, and "Anything" is the sum of the five
    rather than a sixth count -- they partition the set by construction, and
    computing it separately would let the two disagree on screen.
    """
    columns = [func.count(case((clause, 1))) for clause in KINDS.values()]
    row = session.execute(base.with_only_columns(*columns)).one()
    counts = [FacetValue(value=name, count=int(n)) for name, n in zip(KINDS, row, strict=True)]
    return [FacetValue(value="", count=sum(c.count for c in counts)), *counts]


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

    model_rows = session.execute(
        base.with_only_columns(FirearmModel.id, FirearmModel.name, func.count(Item.id))
        .join(FirearmModel, FirearmModel.id == Item.firearm_model_id)
        .group_by(FirearmModel.id, FirearmModel.name)
        .order_by(func.count(Item.id).desc())
        .limit(40)
    ).all()

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
        models=[
            FacetValue(value=str(model_id), label=name, count=int(count))
            for model_id, name, count in model_rows
        ],
        categories=tally(Item.category),
        calibers=tally(Item.caliber),
        countries=tally(Item.country),
        manufacturers=tally(Item.manufacturer),
        total=int(total),
    )


def _with_kinds(session: DbSession, base: Select, without_kind: Select) -> ItemFacets:
    facets = _facets(session, base)
    facets.kinds = _kind_counts(session, without_kind)
    return facets


@router.get("", response_model=ItemPage)
def list_items(
    _user: CurrentUser,
    session: DbSession,
    site_id: list[int] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    caliber: list[str] | None = Query(default=None),
    country: list[str] | None = Query(default=None),
    manufacturer: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None, description="Armory model ids."),
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

    without_kind = apply_filters(
        select(Item),
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        models=model,
        kinds=None,
        availability=availability,
        search=search,
        min_price=min_price,
        max_price=max_price,
        new_since_hours=new_since_hours,
        price_drops_only=price_drops_only,
    )
    base = apply_filters(
        select(Item),
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        models=model,
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
        facets=_with_kinds(session, base, without_kind) if include_facets else None,
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
    # What the armory knows about the match, so the facts panel can show it
    # and link out. Read here rather than on the list endpoint: it is three
    # relationship loads per listing and the grid shows none of it.
    if item.firearm_model is not None:
        found = item.firearm_model
        detail.model_kind = found.kind.value if found.kind else None
        detail.model_makers = found.manufacturer_names
        detail.model_calibers = found.caliber_names
        detail.model_reference_url = found.wikipedia_url
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
