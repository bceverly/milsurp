"""Browsing the collected inventory."""

from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import selectinload

from ..deps import AdminUser, AppConfig, CurrentUser, DbSession
from ..logsafe import client_address
from ..models import FirearmModel, Item, ItemPhoto, PriceHistory, Site
from ..schemas import (
    FacetValue,
    ItemDetail,
    ItemFacets,
    ItemOut,
    ItemOverrideIn,
    ItemOverrideOut,
    ItemPage,
    PhotoOut,
    PriceBucketOut,
    PriceDistributionOut,
    PricePointOut,
    PricePositionOut,
    SimilarListingOut,
)
from ..services import audit, curio, overrides, pricing, provenance, similar, watchlist
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


def _checked_curio(wanted: list[str] | None) -> list[str] | None:
    """Refuse a curio state nothing knows, rather than ignoring it.

    Deliberately stricter than the ``kind`` filter beside it, which drops a
    value it does not recognise. The failure modes are not comparable: a
    mistyped kind returns more guns than were asked for, and a mistyped
    ``curio=eligble`` returns **every** listing -- including the ones that are
    not eligible -- to somebody filtering on exactly that because of what they
    are allowed to buy. Silence is the wrong answer to that question.
    """
    unknown = [state for state in wanted or [] if state not in curio.STATES]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Unknown curio state {unknown[0]!r}. " f"Valid: {', '.join(curio.STATES)}."),
        )
    return wanted


def _to_out(item: Item, site_names: dict[int, str]) -> ItemOut:
    data = ItemOut.model_validate(item)
    # The name only. `firearm_model` on the row is a relationship and the
    # field here is a string -- the same word for two shapes, which is exactly
    # what ManufacturerOut.models got wrong before it was taken out.
    data.model = item.firearm_model.name if item.firearm_model else None
    data.site_name = site_names.get(item.site_id)
    data.thumbnail_url = _thumbnail_url(item)
    data.price_drop = item.price_drop_amount
    # Derived here rather than read off the row: the boundary moves, and the
    # browse filter derives it the same way from curio.clause(). Left empty
    # for anything that is not a firearm -- a bayonet has no C&R status, and
    # the item page shows no C&R line when this is None.
    if curio.applies(item.is_rifle, item.is_pistol, item.is_parts_kit):
        data.curio = curio.status(item.cr_stated, item.manufacture_year)
        data.curio_label = CURIO_LABELS.get(data.curio)
        data.curio_evidence = item.cr_evidence
    data.manufacture_year = item.manufacture_year
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


#: What each curio state is called where somebody reads it.
#:
#: Named server-side for the same reason the finer kinds are: the browse rail,
#: the item page and anything else that shows one must not drift on the wording
#: -- and the wording is doing work here. "Not eligible by age" rather than
#: "Not C&R", because the other two limbs of the definition are invisible to
#: this application and a gun under fifty may still be a curio.
CURIO_LABELS = {
    curio.ELIGIBLE: "C&R eligible",
    curio.NOT_ELIGIBLE: "Not eligible by age",
    curio.UNKNOWN: "Not known",
}


def _curio_counts(session: DbSession, base: Select) -> list[FacetValue]:
    """How many listings each curio state would show, over everything else.

    One pass rather than three, and against a base that does not filter by
    curio -- the same reasoning as :func:`_kind_counts`: with the filter
    applied, picking "eligible" would report zero of everything else and the
    numbers would only describe the choice already made.
    """
    states = curio.STATES
    columns = [func.count(case((curio.clause(state), 1))) for state in states]
    row = session.execute(base.with_only_columns(*columns)).one()
    return [
        FacetValue(value=state, label=CURIO_LABELS[state], count=int(n))
        for state, n in zip(states, row, strict=True)
    ]


def _labelled(values: list[FacetValue]) -> list[FacetValue]:
    """Put a readable name on the finer-kind facet.

    The column stores FirearmKind's own values -- "percussion_revolver" -- and
    the armory page already has the words for them. Labelled here rather than
    in the browser so the two pages cannot drift apart.
    """
    from .armory import KIND_LABELS

    words = {kind.value: label for kind, label in KIND_LABELS.items()}
    for entry in values:
        entry.label = words.get(entry.value, entry.value.replace("_", " ").capitalize())
    return values


#: Columns in the price histogram. Enough to show a shape, few enough that each
#: is a touch target on a phone rail.
PRICE_BUCKETS = 24

#: The slider opens on this share of the listings rather than on the full
#: range: one $750,000 Gatling gun should not decide where the handles start.
#: The extremes are still reachable -- they are the ends of the track.
TYPICAL_SPAN = (0.02, 0.98)


def _percentile(ordered: list[float], fraction: float) -> float:
    """Nearest-rank percentile of a sorted list. See services/market.py for
    why nearest-rank rather than interpolated: these are prices somebody has
    actually written down."""
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _price_distribution(session: DbSession, base: Select) -> PriceDistributionOut | None:
    """The shape of what the current results cost.

    Read as a list of prices and bucketed in Python rather than with a SQL
    ``width_bucket``, which is PostgreSQL-only and this schema answers on
    SQLite too. The cost is one float per matching row, which is the same order
    as the page of items already being sent.

    **Log-spaced**, because the catalog spans a $20 magazine and a $750,000
    Gatling gun and a linear axis puts all but a handful of listings in the
    first column. A histogram nobody can read is worse than none.
    """
    prices = sorted(
        float(value)
        for (value,) in session.execute(
            base.with_only_columns(Item.current_price).where(
                Item.current_price.is_not(None), Item.current_price > 0
            )
        ).all()
        if value is not None  # excluded by the query; this tells the type checker
    )
    unpriced = session.execute(
        base.with_only_columns(func.count(Item.id)).where(
            or_(Item.current_price.is_(None), Item.current_price <= 0)
        )
    ).scalar_one()

    if not prices:
        return None

    low, high = prices[0], prices[-1]
    edges = (
        [
            math.exp(math.log(low) + (math.log(high) - math.log(low)) * index / PRICE_BUCKETS)
            for index in range(PRICE_BUCKETS + 1)
        ]
        if high > low
        else [low, high]
    )

    buckets: list[PriceBucketOut] = []
    cursor = 0
    for index in range(len(edges) - 1):
        start, end = edges[index], edges[index + 1]
        # The last bucket is closed at the top so the dearest listing is in it
        # rather than falling off the end of its own histogram.
        last = index == len(edges) - 2
        count = 0
        while cursor < len(prices) and (prices[cursor] <= end if last else prices[cursor] < end):
            cursor += 1
            count += 1
        buckets.append(PriceBucketOut(low=round(start, 2), high=round(end, 2), count=count))

    return PriceDistributionOut(
        low=low,
        high=high,
        typical_low=_percentile(prices, TYPICAL_SPAN[0]),
        typical_high=_percentile(prices, TYPICAL_SPAN[1]),
        buckets=buckets,
        unpriced=int(unpriced),
    )


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
        forms=_labelled(tally(Item.kind)),
        total=int(total),
    )


def _with_kinds(
    session: DbSession,
    base: Select,
    without_kind: Select,
    without_price: Select,
    without_curio: Select,
) -> ItemFacets:
    facets = _facets(session, base)
    facets.kinds = _kind_counts(session, without_kind)
    facets.curio = _curio_counts(session, without_curio)
    facets.prices = _price_distribution(session, without_price)
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
    form: list[str] | None = Query(
        default=None,
        description="The finer kind: revolver | carbine | shotgun | percussion_pistol | …",
    ),
    curio: list[str] | None = Query(
        default=None, description="Curio and relic: eligible | not_eligible | unknown"
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

    # Spelled out twice rather than shared through a dict: mypy cannot check a
    # heterogeneous **kwargs against this signature, and losing the check on
    # fifteen filter arguments is a worse trade than repeating them.
    #
    # The kind facet is counted against a query that does *not* filter by kind,
    # so it can show what the other kinds would return.
    without_kind = apply_filters(
        select(Item),
        kinds=None,
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        models=model,
        forms=form,
        curio_states=_checked_curio(curio),
        availability=availability,
        search=search,
        min_price=min_price,
        max_price=max_price,
        new_since_hours=new_since_hours,
        price_drops_only=price_drops_only,
    )
    base = apply_filters(
        select(Item),
        kinds=kind,
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        models=model,
        forms=form,
        curio_states=_checked_curio(curio),
        availability=availability,
        search=search,
        min_price=min_price,
        max_price=max_price,
        new_since_hours=new_since_hours,
        price_drops_only=price_drops_only,
    )
    # And the price histogram against a query that does not filter by price,
    # for the same reason the kind facet does not filter by kind -- and more
    # sharply, because the price control is a *slider*. Shaped by its own
    # setting, narrowing to $500-$1,000 would redraw the histogram as only that
    # slice, and there would be nothing on screen to widen back towards.
    without_price = apply_filters(
        select(Item),
        kinds=kind,
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        models=model,
        forms=form,
        curio_states=_checked_curio(curio),
        availability=availability,
        search=search,
        min_price=None,
        max_price=None,
        new_since_hours=new_since_hours,
        price_drops_only=price_drops_only,
    )

    # And the curio facet against a query that does not filter by curio, so
    # each of the three states says what picking it would show rather than
    # what the current pick already did.
    without_curio = apply_filters(
        select(Item),
        kinds=kind,
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        models=model,
        forms=form,
        curio_states=None,
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
        facets=(
            _with_kinds(session, base, without_kind, without_price, without_curio)
            if include_facets
            else None
        ),
    )


#: Columns an export carries, in the order a reader wants them.
#:
#: Chosen rather than "every column": `id` and `external_key` are this
#: application's bookkeeping and mean nothing in a spreadsheet, while the
#: derived fields are the interesting part -- a caliber this application worked
#: out is exactly what somebody would want to sort by.
EXPORT_COLUMNS: tuple[str, ...] = (
    "title",
    "price",
    "currency",
    "caliber",
    "country",
    "manufacturer",
    "kind",
    "condition",
    "site",
    "url",
    "is_sold",
    "first_seen_at",
    "last_seen_at",
)

#: The most rows one export may carry.
#:
#: Generous -- it is above the whole active catalog -- and present so that a
#: filter nobody meant to be that wide cannot ask the database to stream
#: everything it has into a browser. Hitting it is reported rather than
#: silently truncating, because an export that quietly stops is worse than one
#: that refuses.
EXPORT_LIMIT = 25_000


def _export_row(item: Item, site_names: dict[int, str]) -> dict[str, object]:
    return {
        "title": item.title,
        "price": item.current_price,
        "currency": item.currency,
        "caliber": item.caliber,
        "country": item.country,
        "manufacturer": item.manufacturer,
        "kind": item.kind,
        "condition": item.condition,
        "site": site_names.get(item.site_id, ""),
        "url": item.url,
        "is_sold": item.is_sold,
        "first_seen_at": item.first_seen_at.isoformat() if item.first_seen_at else None,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
    }


@router.get("/export")
def export_items(
    _user: CurrentUser,
    session: DbSession,
    fmt: str = Query(default="csv", pattern="^(csv|json)$", alias="format"),
    site_id: list[int] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    caliber: list[str] | None = Query(default=None),
    country: list[str] | None = Query(default=None),
    manufacturer: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None, description="Armory model ids."),
    kind: list[str] | None = Query(default=None),
    form: list[str] | None = Query(default=None),
    curio: list[str] | None = Query(default=None),
    availability: str = Query(default="available"),
    search: str | None = Query(default=None, max_length=200),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    new_since_hours: int | None = Query(default=None, ge=1, le=8760),
    price_drops_only: bool = Query(default=False),
) -> Response:
    """The listings a browse page is showing, as a file.

    **The same query parameters as the list endpoint**, so a browse URL becomes
    an export by changing the path -- which is the only way the promise "what
    you are looking at" can be kept. They are declared twice because FastAPI
    reads them off the signature; what matters is that both hand the same
    dictionary to the same `apply_filters`.

    No pagination: an export is the whole answer or it is not an export. It is
    bounded by EXPORT_LIMIT instead, and says so rather than truncating.
    """
    query = apply_filters(
        select(Item),
        site_ids=site_id,
        categories=category,
        calibers=caliber,
        countries=country,
        manufacturers=manufacturer,
        models=model,
        forms=form,
        curio_states=_checked_curio(curio),
        kinds=kind,
        availability=availability,
        search=search,
        min_price=min_price,
        max_price=max_price,
        new_since_hours=new_since_hours,
        price_drops_only=price_drops_only,
    )

    total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    if total > EXPORT_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"That is {int(total):,} listings and the limit is {EXPORT_LIMIT:,}. "
                "Narrow the filters and try again."
            ),
        )

    items = session.execute(query.order_by(Item.first_seen_at.desc())).scalars().all()
    site_names = {row[0]: row[1] for row in session.execute(select(Site.id, Site.name)).all()}
    rows = [_export_row(item, site_names) for item in items]

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    if fmt == "json":
        return JSONResponse(
            content=rows,
            headers={"Content-Disposition": f'attachment; filename="milsurp-{stamp}.json"'},
        )

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(EXPORT_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="milsurp-{stamp}.csv"'},
    )


@router.get("/{item_id}", response_model=ItemDetail)
def get_item(item_id: int, user: CurrentUser, session: DbSession) -> ItemDetail:
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
    # Only the fields that have one: an absent key and a null read the same on
    # the page, and sending four nulls for a listing nothing is known about
    # says less than sending nothing.
    detail.sources = {
        field: source
        for field, column in provenance.SOURCE_COLUMNS.items()
        if (source := getattr(item, column, None))
    }
    watch = watchlist.watching(session, user, item.id)
    if watch is not None:
        detail.watched = True
        detail.watch_target_price = watch.target_price
        detail.watch_note = watch.note
        detail.watch_alert_immediately = watch.alert_immediately
    if item.firearm_model is not None:
        found = item.firearm_model
        detail.model_kind = found.kind.value if found.kind else None
        detail.model_makers = found.manufacturer_names
        detail.model_calibers = found.caliber_names
        detail.model_reference_url = found.wikipedia_url
        detail.model_country = found.country
        detail.model_status = found.status.value
        detail.model_notes = found.notes
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


@router.get("/{item_id}/similar", response_model=list[SimilarListingOut])
def similar_listings(
    item_id: int, _user: CurrentUser, session: DbSession
) -> list[SimilarListingOut]:
    """Other listings worth looking at beside this one.

    Its own endpoint for the same reason price-position is: it answers nothing
    for a listing with neither a model nor a cartridge, and the detail page
    should not wait on a query to find that out.

    Empty rather than absent when there is nothing to say. A list the page can
    render as zero rows is easier to hold than a null it has to special-case.
    """
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such item.")
    found = similar.find(session, item)
    # One query for the vendor names rather than one per row: eight listings
    # from eight shops is the good case for this feature, not the rare one.
    site_names = {
        site.id: site.name
        for site in session.execute(
            select(Site).where(Site.id.in_({entry.item.site_id for entry in found}))
        ).scalars()
    }
    return [
        SimilarListingOut(
            item=_to_out(entry.item, site_names),
            rung=entry.rung.key,
            label=entry.rung.label,
        )
        for entry in found
    ]


@router.get("/{item_id}/price-position", response_model=PricePositionOut | None)
def price_position(item_id: int, _user: CurrentUser, session: DbSession) -> PricePositionOut | None:
    """Where this listing sits among the others of the same gun.

    Null when it has too few peers to sit among, which is most listings: it
    needs a matched model, a maker, a cartridge and a price, and at least two
    others with all four the same. Its own endpoint rather than a field on the
    item, so the detail page renders without waiting for a query that answers
    "nothing to say" for the majority of listings.
    """
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such item.")
    found = pricing.position(session, item)
    if found is None:
        return None
    return PricePositionOut(
        count=found.count,
        vendors=found.vendors,
        low=found.low,
        high=found.high,
        q1=found.q1,
        median=found.median,
        q3=found.q3,
        price=found.price,
        cheaper_than=found.cheaper_than,
        position=found.position,
        model=found.model,
        manufacturer=found.manufacturer,
        caliber=found.caliber,
    )


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

    # **The connection goes back to the pool before a single byte is sent.**
    #
    # Everything this endpoint wants from the database is now in the three
    # locals above; the rest of the request is a file read and a socket. But
    # the dependency holds the session until the response has been *streamed*,
    # so without this each in-flight photo pins one of the pool's connections
    # for as long as the transfer takes -- and a page of thumbnails is not one
    # request, it is one per thumbnail.
    #
    # That is not hypothetical. A hot deals page of 159 rows asked for 159
    # photos at once against a pool of 15: every connection was held by a
    # transfer, the rest queued on a 30-second pool timeout, and the whole
    # worker threadpool filled up behind them. Sessions could not be checked,
    # so readers were bounced to the login page, and the login could not reach
    # the database either, so the proxy answered that with a 504. The page that
    # caused it now defers its images, but any page that asks for a lot of them
    # should not be able to do this, so the hold is made short rather than the
    # storm made unlikely.
    #
    # `close()` is idempotent and hands the connection back; the dependency's
    # own close in its `finally` then has nothing left to do.
    session.close()

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
        # The local rather than `photo.content_type`: the row is detached now,
        # and this is the value the thumb branch above may have corrected.
        media_type=media_type,
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


# ---------------------------------------------------------------------------
# Corrections by hand
# ---------------------------------------------------------------------------
@router.get("/{item_id}/override", response_model=ItemOverrideOut | None)
def read_override(item_id: int, _user: CurrentUser, session: DbSession) -> ItemOverrideOut | None:
    """This listing's correction, if somebody has made one."""
    override = overrides.for_item(session, item_id)
    return (
        None if override is None else ItemOverrideOut.model_validate(override, from_attributes=True)
    )


@router.put("/{item_id}/override", response_model=ItemOverrideOut)
def set_override(
    item_id: int,
    payload: ItemOverrideIn,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> ItemOverrideOut:
    """Correct what the rules concluded about this listing.

    Admin-only: an override outranks every rule in the application, and one
    set by mistake is invisible afterwards -- the listing simply reads wrong
    and nothing says why.
    """
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such listing.")

    # exclude_unset so an omitted field keeps whatever it had. A field sent
    # empty clears the override for it; the two are different requests and
    # mean different things.
    values = payload.model_dump(exclude_unset=True)
    note = values.pop("note", None)
    override = overrides.save(session, item, values, actor=admin, note=note)
    audit.record(
        session,
        actor=admin,
        action=audit.ITEM_OVERRIDDEN,
        target_type="item",
        target_id=item.id,
        target_label=item.title,
        detail="; ".join(f"{k}={v}" for k, v in values.items() if v) or "cleared",
        ip_address=client_address(request),
    )
    session.commit()
    return ItemOverrideOut.model_validate(override, from_attributes=True)


@router.delete("/{item_id}/override", status_code=status.HTTP_204_NO_CONTENT)
def clear_override(item_id: int, admin: AdminUser, request: Request, session: DbSession) -> None:
    """Drop the correction and let the rules answer again.

    The derived values are not restored here -- the next scan, or `reclassify
    --recompute`, puts back whatever the rules now say. Guessing at them from
    this side would mean a second implementation of the pipeline.
    """
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such listing.")
    if not overrides.clear(session, item):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This listing has no override."
        )
    audit.record(
        session,
        actor=admin,
        action=audit.ITEM_OVERRIDE_CLEARED,
        target_type="item",
        target_id=item.id,
        target_label=item.title,
        ip_address=client_address(request),
    )
    session.commit()
