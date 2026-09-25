"""Editing the country rules from the admin pages.

The list lived in :mod:`app.services.classify` as 38 regular expressions, so
teaching it that "Ishapore" means India was a code change for a fact the
operator knows and the programmer does not. See
:mod:`app.services.countries` for why the rules are a process-wide registry
rather than a per-request read.

Every write here invalidates that registry. Forgetting to is the failure mode
this kind of cache has: the edit saves, the page shows it, and nothing
classifies differently until the process restarts -- with nothing on screen to
explain why.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from ..deps import AdminUser, DbSession
from ..logsafe import client_address
from ..models import Country, Item
from ..schemas import CountryIn, CountryOut, CountryUpdate
from ..services import audit, countries

router = APIRouter(prefix="/countries", tags=["countries"])


def _out(row: Country, counts: dict[str, int]) -> CountryOut:
    return CountryOut(
        id=row.id,
        name=row.name,
        aliases=row.aliases,
        position=row.position,
        enabled=row.enabled,
        notes=row.notes,
        listing_count=counts.get(row.name, 0),
    )


def _counts(session: DbSession) -> dict[str, int]:
    rows = session.execute(
        select(Item.country, func.count(Item.id))
        .where(Item.is_active.is_(True), Item.country.is_not(None))
        .group_by(Item.country)
    ).all()
    return {name: int(n) for name, n in rows if name is not None}


@router.get("", response_model=list[CountryOut])
def list_countries(
    _admin: AdminUser,
    session: DbSession,
    search: str | None = Query(default=None, max_length=100),
) -> list[CountryOut]:
    """The rules, in the order they are tried."""
    stmt = select(Country).order_by(Country.position, Country.name)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(Country.name).like(like) | func.lower(Country.aliases).like(like)
        )
    counts = _counts(session)
    return [_out(row, counts) for row in session.execute(stmt).scalars().all()]


@router.post("", response_model=CountryOut, status_code=status.HTTP_201_CREATED)
def create_country(
    payload: CountryIn, admin: AdminUser, request: Request, session: DbSession
) -> CountryOut:
    existing = session.execute(
        select(Country).where(func.lower(Country.name) == payload.name.strip().lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That country is already listed."
        )
    row = Country(
        name=payload.name.strip(),
        aliases=payload.aliases,
        position=payload.position,
        enabled=payload.enabled,
        notes=payload.notes,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        actor=admin,
        action=audit.COUNTRY_CHANGED,
        target_type="country",
        target_id=row.id,
        target_label=row.name,
        detail="created",
        ip_address=client_address(request),
    )
    session.commit()
    countries.invalidate()
    return _out(row, _counts(session))


@router.patch("/{country_id}", response_model=CountryOut)
def update_country(
    country_id: int,
    payload: CountryUpdate,
    admin: AdminUser,
    request: Request,
    session: DbSession,
) -> CountryOut:
    row = session.get(Country, country_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such country.")

    changes = []
    for field in ("name", "aliases", "position", "enabled", "notes"):
        value = getattr(payload, field)
        if value is None:
            continue
        if getattr(row, field) != value:
            changes.append(field)
            setattr(row, field, value.strip() if isinstance(value, str) else value)

    if changes:
        audit.record(
            session,
            actor=admin,
            action=audit.COUNTRY_CHANGED,
            target_type="country",
            target_id=row.id,
            target_label=row.name,
            detail=", ".join(changes),
            ip_address=client_address(request),
        )
    session.commit()
    countries.invalidate()
    return _out(row, _counts(session))


@router.delete("/{country_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_country(country_id: int, admin: AdminUser, request: Request, session: DbSession) -> None:
    """Remove a rule.

    Listings already filed under it keep their country: this deletes the rule
    that *assigns* one, not the answer it gave. Disabling is usually what
    somebody means, which is why that is a switch rather than this.
    """
    row = session.get(Country, country_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such country.")
    audit.record(
        session,
        actor=admin,
        action=audit.COUNTRY_CHANGED,
        target_type="country",
        target_id=row.id,
        target_label=row.name,
        detail="deleted",
        ip_address=client_address(request),
    )
    session.delete(row)
    session.commit()
    countries.invalidate()
