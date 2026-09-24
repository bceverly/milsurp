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

import logging
import re
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode

from sqlalchemy import Select, column, or_, select, table, true
from sqlalchemy.orm import Session

from ..models import Item, utcnow
from . import curio

log = logging.getLogger("milsurp.search")

#: Below three characters a trigram index cannot help, and on SQLite it is
#: worse than that: FTS5's trigram tokenizer indexes nothing shorter, so a MATCH
#: for a two-character term returns *nothing at all* rather than a slow answer.
#: Those terms take the plain scan, which is correct and no slower than the
#: whole search used to be.
TRIGRAM_MIN = 3

#: The FTS5 table, as a bare table rather than a mapped class: it has no
#: columns worth naming, and `items_fts MATCH ?` is a predicate on the table
#: itself, which is how FTS5 spells a whole-row match.
_FTS = table("items_fts", column("rowid"), column("items_fts"))

#: How the search box is served on this deployment, worked out once.
#:
#: ``postgres`` -- a GIN pg_trgm index over `items.search_document`, which
#: serves ``ILIKE '%x%'`` directly, so the query is the obvious one.
#: ``sqlite``   -- an FTS5 trigram table, which needs a MATCH subquery.
#: ``columns``  -- neither: the six original ILIKEs. This is what a database
#: sees between installing a release and running its migration, and what a
#: PostgreSQL whose role could not create the pg_trgm extension keeps using.
#: It is the old behavior, exactly, which is why it is a safe thing to fall
#: back to rather than an error to raise.
_index_kind: str | None = None


def _search_index() -> str:
    """Which search index this database has, cached after the first look."""
    global _index_kind
    if _index_kind is not None:
        return _index_kind
    try:
        from sqlalchemy import inspect

        from ..database import get_engine

        engine = get_engine()
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("items")}
        if "search_document" not in columns:
            _index_kind = "columns"
        elif engine.dialect.name == "postgresql":
            indexes = {index["name"] for index in inspector.get_indexes("items")}
            _index_kind = "postgres" if "ix_items_search_trgm" in indexes else "columns"
        elif "items_fts" in set(inspector.get_table_names()):
            _index_kind = "sqlite"
        else:
            _index_kind = "columns"
    except Exception:
        log.warning(
            "Could not determine the search index; using the unindexed scan.", exc_info=True
        )
        _index_kind = "columns"
    return _index_kind


def forget_search_index() -> None:
    """Drop the cached answer. For the tests, which build several databases in
    one process, and for a migration applied while the app is running."""
    global _index_kind
    _index_kind = None


def _escaped(term: str) -> str:
    return term.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _columns_clause(pattern: str) -> Any:
    """The original six-way OR, which every other form has to agree with.

    ilike, not like. SQLite's LIKE ignores case for ASCII and PostgreSQL's does
    not, so plain `like` would quietly make the search case-sensitive --
    "enfield" would stop matching "ENFIELD SMLE", which is how most of these
    vendors write a title.
    """
    return or_(
        Item.title.ilike(pattern, escape="!"),
        Item.description.ilike(pattern, escape="!"),
        Item.caliber.ilike(pattern, escape="!"),
        Item.manufacturer.ilike(pattern, escape="!"),
        Item.country.ilike(pattern, escape="!"),
        Item.category.ilike(pattern, escape="!"),
    )


def _term_clause(term: str) -> Any:
    """One term's predicate: it must appear somewhere in the listing.

    The three forms answer identically -- that is the whole contract, and it is
    tested against the real catalog rather than asserted. What differs is only
    how much of the table has to be read to find out.
    """
    kind = _search_index()
    pattern = f"%{_escaped(term)}%"

    # Too short for a trigram, on either engine, so the original columns are
    # the fastest correct answer -- and asking for the indexed form is worse
    # than not having the index. PostgreSQL will *try* the GIN index for a
    # two-character pattern, fail to narrow anything, and recheck every row it
    # visited: measured at 91ms against 47ms for the plain scan, a regression
    # this branch exists to prevent. On SQLite the same term matches nothing
    # at all through FTS5.
    if len(term) < TRIGRAM_MIN:
        return _columns_clause(pattern)

    if kind == "postgres":
        return Item.search_document.ilike(pattern, escape="!")

    if kind == "sqlite" and len(term) >= TRIGRAM_MIN:
        # FTS5 takes the term as a quoted string, where the only character
        # needing care is the quote itself. The LIKE wildcards are ordinary
        # characters to it, so the escaping above is deliberately not applied.
        #
        # Built as a real select rather than a `text()` carrying a named bind.
        # Two terms meant two clauses with the *same* parameter name and the
        # second quietly overwrote the first, so "mosin german" was executed as
        # "german AND german" -- two results where the right answer is none.
        # SQLAlchemy names an anonymous bind per clause, which is the whole
        # reason to let it build the statement.
        quoted = '"' + term.replace('"', '""') + '"'
        return Item.id.in_(select(_FTS.c.rowid).where(_FTS.c.items_fts.op("MATCH")(quoted)))

    return _columns_clause(pattern)


SORTS: dict[str, tuple[Any, ...]] = {
    "newest": (Item.first_seen_at.desc(), Item.id.desc()),
    "oldest": (Item.first_seen_at.asc(), Item.id.asc()),
    "price_asc": (Item.current_price.is_(None).asc(), Item.current_price.asc()),
    "price_desc": (Item.current_price.is_(None).asc(), Item.current_price.desc()),
    "title": (Item.title.asc(),),
    # nulls_last, because the two engines disagree about where a NULL goes in
    # a descending sort -- SQLite puts it last, PostgreSQL puts it first -- and
    # first is plainly wrong here: it would lead "Price reduced" with every
    # listing whose price has never moved.
    "price_drop": (Item.price_changed_at.desc().nulls_last(),),
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


#: The browse filter's Types, which **partition the catalog**: every listing is
#: in exactly one, and the counts beside them sum to the total.
#:
#: Police surplus is the reason rifle and pistol carry an exclusion. A police
#: trade-in Glock is a handgun and ``is_pistol`` says so -- that is the true
#: answer and the armory needs it -- but counting it under both Handguns and
#: Police surplus would break the partition and show a listing twice. So the
#: bucket is subtracted here, in the one place that cares, rather than by
#: making the underlying column lie.
KINDS: dict[str, Any] = {
    "rifle": Item.is_rifle.is_(True) & Item.is_police_surplus.is_(False),
    "pistol": Item.is_pistol.is_(True) & Item.is_police_surplus.is_(False),
    "bayonet": Item.is_bayonet.is_(True),
    "parts_kit": Item.is_parts_kit.is_(True),
    "police_surplus": Item.is_police_surplus.is_(True),
    # No police-surplus term needed: the column is only ever true for a listing
    # that is already a rifle or a handgun, so this clause excludes it already.
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
    forms: list[str] | None,
    kinds: list[str] | None,
    curio_states: list[str] | None,
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

    if forms:
        stmt = stmt.where(Item.kind.in_(forms))
    if kinds:
        clauses = [_kind_clause(k) for k in kinds if k in KINDS]
        if clauses:
            stmt = stmt.where(or_(*clauses))

    if curio_states:
        # Built by curio.clause so this and the badge on a listing's own page
        # are the same judgment. The fifty-year boundary moves, so it is a
        # comparison against a cut-off computed now rather than a stored
        # answer -- which is also why manufacture_year carries an index.
        wanted = [curio.clause(state) for state in curio_states if state in curio.STATES]
        if wanted:
            stmt = stmt.where(or_(*wanted))

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
        for term in _search_terms(search):
            stmt = stmt.where(_term_clause(term))

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
    # The finer kind -- revolver, carbine, percussion pistol. A *second*
    # question from "kind": that one picks which of the five buckets a listing
    # is in, this one narrows within it. See Item.kind.
    "form": True,
    # Curio and relic: eligible / not_eligible / unknown. Repeats, because
    # "eligible or I cannot tell" is a real thing to want -- a collector
    # clearing their own licence would rather see the maybes than lose them.
    "curio": True,
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
    "form": "forms",
    "curio": "curio_states",
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
        "forms": None,
        "kinds": None,
        "curio_states": None,
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

    if filters["curio_states"]:
        unknown = [c for c in filters["curio_states"] if c not in curio.STATES]
        if unknown:
            raise BadQuery(f"Unknown curio state {unknown[0]!r}. Valid: {', '.join(curio.STATES)}.")

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


def mention_search(name: str) -> str:
    """The browse search for listings that name *this* phrase, quoted whole.

    Quoted, so "Model 1808" asks for the phrase and not for every listing that
    says "Model" and, somewhere, "1808". Used by the armory to count what a
    pending row would explain, and handed to the browse page by its eyeball --
    one string for both, so the count and the page it opens cannot disagree.
    """
    return '"' + " ".join(name.replace('"', " ").split()) + '"'


def count_mentions(session: Session, name: str) -> int:
    """How many stored listings, sold and de-listed included, name this phrase."""
    from sqlalchemy import func

    stmt = apply_filters(
        select(func.count(Item.id)),
        site_ids=None,
        categories=None,
        calibers=None,
        countries=None,
        manufacturers=None,
        models=None,
        forms=None,
        kinds=None,
        curio_states=None,
        availability="all",
        search=mention_search(name),
        min_price=None,
        max_price=None,
        new_since_hours=None,
        price_drops_only=False,
    )
    return int(session.execute(stmt).scalar_one())


def count_mentions_many(session: Session, names: list[str]) -> dict[str, int]:
    """:func:`count_mentions` for many names at once, in one read of the table.

    The armory page shows a count on every row awaiting approval, and after
    "Load shipped armory" that is several hundred rows: one query each was
    seconds of page load. A quoted phrase matches when it appears, ignoring
    case, in any of the six columns the search reads (``_columns_clause``), so
    reading those columns once and testing each phrase in memory is the same
    answer -- ``test_armory_mentions.py`` holds the two to it on a catalog
    built for the purpose.
    """
    wanted = {name: " ".join(name.replace('"', " ").split()).lower() for name in names}
    counts = dict.fromkeys(names, 0)
    if not wanted:
        return counts
    columns = (
        Item.title,
        Item.description,
        Item.caliber,
        Item.manufacturer,
        Item.country,
        Item.category,
    )
    for row in session.execute(select(*columns)):
        # A separator no phrase can contain, so a phrase never spans two
        # columns -- which a real search, testing each column apart, cannot.
        document = "\x00".join((value or "").lower() for value in row)
        for name, phrase in wanted.items():
            if phrase and phrase in document:
                counts[name] += 1
    return counts
