"""Turning a set of filters into a query over the listings.

Extracted from :mod:`app.api.items`, which owned all of this and was the only
caller until saved searches arrived. It has two callers now -- the browse
endpoint and the digest that mails a saved search's results -- and they have to
agree exactly: a saved search that returned one set of listings in the browser
and a different set in the email would be worse than no saved search at all.

So the filters, the sort orders and the parsing of a stored query string all
live here, and both callers go through them.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode

from sqlalchemy import Select, or_, select, true
from sqlalchemy.orm import Session

from ..models import Item, utcnow

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


KINDS: dict[str, Any] = {
    "rifle": Item.is_rifle.is_(True),
    "pistol": Item.is_pistol.is_(True),
    "bayonet": Item.is_bayonet.is_(True),
    "parts_kit": Item.is_parts_kit.is_(True),
    "other": (
        Item.is_rifle.is_(False)
        & Item.is_pistol.is_(False)
        & Item.is_bayonet.is_(False)
        & Item.is_parts_kit.is_(False)
    ),
}


def _kind_clause(kind: str) -> Any:
    return KINDS[kind]


def apply_filters(  # noqa: PLR0912 - one branch per filter; splitting it
    #                                      would only scatter the same logic
    stmt: Select,
    *,
    site_ids: list[int] | None,
    categories: list[str] | None,
    calibers: list[str] | None,
    countries: list[str] | None,
    manufacturers: list[str] | None,
    models: list[str] | None,
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
    if models:
        # By id, not by name. This one is a foreign key to a row somebody
        # vouched for, so there is an id to filter on and no reason to match
        # text -- and a model renamed in the armory keeps its listings.
        stmt = stmt.where(Item.firearm_model_id.in_([int(value) for value in models]))

    if kinds:
        clauses = [_kind_clause(k) for k in kinds if k in KINDS]
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


#: Every filter the browse page can set, and how a saved query names it.
#:
#: ``True`` means the parameter repeats -- ``?caliber=8mm&caliber=7.62x54R`` --
#: which is how the multi-select facets arrive. The rest take one value.
QUERY_PARAMS: dict[str, bool] = {
    "site_id": True,
    "category": True,
    "caliber": True,
    "country": True,
    "manufacturer": True,
    "model": True,
    "kind": True,
    "availability": False,
    "search": False,
    "min_price": False,
    "max_price": False,
    "new_since_hours": False,
    "price_drops_only": False,
    "sort": False,
}

#: Parameters a saved search stores but which say nothing about *which*
#: listings match -- only how many are shown at a time. They are dropped on the
#: way in, so two saved searches that differ only in paging are the same
#: search, and so the email is never silently capped at a page size.
_NOT_A_FILTER = ("page", "per_page", "include_facets", "view")

DEFAULT_AVAILABILITY = "available"
DEFAULT_SORT = "newest"


class BadQuery(ValueError):
    """A stored query names something this application cannot answer."""


class SearchQuery:
    """One saved set of filters, ready to run.

    Built only by :func:`parse_query`, so an instance is always something the
    database can actually be asked -- an unknown sort or a non-numeric price is
    refused at the door rather than at send time, when there is nobody to tell.
    """

    def __init__(self, filters: dict[str, Any], sort: str) -> None:
        self.filters = filters
        self.sort = sort

    def as_query_string(self) -> str:
        """The canonical form: sorted, paging dropped, defaults kept.

        Canonical because it is what gets stored and what the browse page is
        handed back, and two saved searches built by the same clicks in a
        different order should not read as different searches.
        """
        pairs: list[tuple[str, str]] = []
        for name in sorted(QUERY_PARAMS):
            value = self.filters.get(_FILTER_NAMES.get(name, name))
            if name == "sort":
                value = self.sort
            if value in (None, "", [], False):
                continue
            if isinstance(value, list):
                pairs.extend((name, str(one)) for one in value)
            elif isinstance(value, bool):
                pairs.append((name, "true"))
            else:
                pairs.append((name, str(value)))
        return urlencode(pairs)


#: The browse page's parameter names, mapped to what apply_filters calls them.
_FILTER_NAMES = {
    "site_id": "site_ids",
    "category": "categories",
    "caliber": "calibers",
    "country": "countries",
    "manufacturer": "manufacturers",
    "model": "models",
    "kind": "kinds",
}


def parse_query(query_string: str) -> SearchQuery:  # noqa: PLR0912 - one branch
    #                     per parameter shape; splitting it only scatters the same checks
    """Read a stored query string into something runnable, or refuse it.

    Refusing matters more here than on the browse endpoint. There, a bad
    parameter is a 400 in front of somebody who can fix it; here it is a saved
    row that will be run unattended every morning, so it is validated when it
    is saved and cannot rot into a silent empty email.
    """
    raw: dict[str, list[str]] = {}
    for name, value in parse_qsl(query_string or "", keep_blank_values=False):
        if name in _NOT_A_FILTER:
            continue
        if name not in QUERY_PARAMS:
            raise BadQuery(f"Unknown search parameter {name!r}.")
        raw.setdefault(name, []).append(value)

    sort = raw.pop("sort", [DEFAULT_SORT])[-1]
    if sort not in SORTS:
        raise BadQuery(f"Unknown sort {sort!r}. Valid: {', '.join(sorted(SORTS))}.")

    filters: dict[str, Any] = {
        "site_ids": None,
        "categories": None,
        "calibers": None,
        "countries": None,
        "manufacturers": None,
        "models": None,
        "kinds": None,
        "availability": DEFAULT_AVAILABILITY,
        "search": None,
        "min_price": None,
        "max_price": None,
        "new_since_hours": None,
        "price_drops_only": False,
    }

    for name, values in raw.items():
        target = _FILTER_NAMES.get(name, name)
        if QUERY_PARAMS[name]:
            filters[target] = values
        else:
            filters[target] = values[-1]

    if filters["site_ids"]:
        filters["site_ids"] = [_int(name="site_id", value=v) for v in filters["site_ids"]]
    if filters["models"]:
        # Kept as strings: apply_filters casts them, and it is the one place
        # that knows they are armory ids rather than names.
        for value in filters["models"]:
            _int(name="model", value=value)
    for name in ("min_price", "max_price"):
        if filters[name] is not None:
            filters[name] = _float(name=name, value=filters[name])
    if filters["new_since_hours"] is not None:
        filters["new_since_hours"] = _int(name="new_since_hours", value=filters["new_since_hours"])
    filters["price_drops_only"] = str(filters["price_drops_only"]).lower() in ("1", "true", "yes")

    if filters["kinds"]:
        unknown = [k for k in filters["kinds"] if k not in KINDS]
        if unknown:
            raise BadQuery(f"Unknown type {unknown[0]!r}. Valid: {', '.join(sorted(KINDS))}.")

    return SearchQuery(filters, sort)


def _int(*, name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise BadQuery(f"{name} must be a whole number, not {value!r}.") from exc


def _float(*, name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise BadQuery(f"{name} must be a number, not {value!r}.") from exc


def run(session: Session, query: SearchQuery, *, limit: int | None = None) -> list[Item]:
    """The listings a saved search matches, in the order it was saved with.

    ``limit`` is the email's cap and nothing else: the browse page pages
    through the whole result set, and a saved search run from its own list page
    returns everything. The cap exists because an email is a fixed thing that
    arrives whether or not anybody wants to read four hundred rows.
    """
    stmt = apply_filters(select(Item), **query.filters).order_by(*SORTS[query.sort])
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().unique().all())
