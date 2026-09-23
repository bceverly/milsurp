"""Listings that are cheap for what they are, found on a clock.

The catalog can already answer "is *this* a good deal" -- the price spectrum on
a listing's own page places it among the others of the same gun. This asks the
question from the other end: **of everything on every shelf, which ones are the
bargains right now.** Nothing could answer that, because answering it means
placing every listing in the catalog rather than one.

**Why it is a scheduled pass and not a query.** Placing a listing means finding
its peers, sorting them and reading off a rank. Done one listing at a time
that is a query each, and the catalog holds nine thousand of them. Done the way
:func:`_place_everything` does it -- load once, group in memory, sort each group
once -- it is a single pass costing seconds, and the answer changes only when a
scan changes a price. So it runs on a cadence, writes :class:`HotDeal` rows,
and the page reads those.

**The rule, and why it is four numbers rather than one.**

Ranking purely by how far below its peers a listing sits produces a page of
misclassified parts. Measured against the live catalog, the top of that list
was a $25 ``GERMAN LUGER P.08 PISTOL SEAR`` reading as 99% below the median --
a sear matched to the Luger P.08 model, sitting in a group of complete Lugers.
Below it: a ZFK-55 bolt, a P.08 magazine, a set of plastic grips, a non-firing
miniature Colt, a bare 1911A1 frame.

None of those is mispriced. They are *mismatched*, and no threshold on price
alone separates a mismatch from a bargain -- except, it turns out, the size of
the gap. Sampling the bands:

===================  ===========================================
20-35% below median  real guns, real bargains -- an FN 150 Match
                     at $395 against a $595 median
35-50%               real -- a Walther PPK at $1,750 / $2,750
50-65%               real, shading into condition: sporters,
                     "gunsmith specials", a Carl Gustav at $250
65-80%               mixed; mostly wrecks and sporters
80%+                 magazines, bolts, grips, frames, replicas
===================  ===========================================

So the ceiling is the load-bearing number and the floor is the obvious one: the
floor keeps out the merely-slightly-cheaper (in a group whose prices sit within
a few dollars the cheapest undercuts every one of them and is not a deal), and
the ceiling keeps out the things that are not the same object as their peers.

The fourth number is the vendor count. One dealer's shelf is that dealer's
pricing rather than a market -- the finding :mod:`app.services.market` reports
as ``concentrated`` -- so a listing that undercuts only its own shop's other
copies is an internal price spread, not a deal.

All four are settings rather than constants, because they are policy and the
person who should be able to change them is an administrator with a browser.

**Peers are exactly the ones the listing page draws**, sold ones included, and
that is deliberate: a reader who clicks through from here to a listing must not
find a different number under the same words. What is narrowed is the pool of
*candidates* -- a sold listing is never itself offered as a deal, because the
buying opportunity is over.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    HotDeal,
    HotDealNotice,
    HotDealPreference,
    HotDealSetting,
    Item,
    SavedSearch,
    User,
    as_utc,
    utcnow,
)
from . import pricing

log = logging.getLogger("milsurp.hotdeals")

#: The three filters, which are the browse page's own buckets under its own
#: names. Ordered as the page offers them.
#:
#: Police surplus is first in :func:`bucket_of` for the reason
#: ``search.KINDS`` subtracts it from the other two: a police trade-in Glock is
#: a handgun and ``is_pistol`` says so, but counting it under both Handguns and
#: Police surplus would show one listing twice.
BUCKETS: tuple[str, ...] = ("rifle", "pistol", "police_surplus")

#: What each is called where a person reads it. Server-side so the page, the
#: email and the API cannot drift on the wording.
BUCKET_LABELS = {
    "rifle": "Rifles",
    "pistol": "Handguns",
    "police_surplus": "Police surplus",
}

#: The orders the page may be read in. The key is what a query string carries,
#: the value is what the database is asked for, and the tie-break on ``id`` is
#: on every one of them so that paging through an order with ties -- and prices
#: tie constantly in a catalog full of the same rifle at $295 -- is stable
#: rather than whatever the engine felt like.
#:
#: Decided here rather than in the page for the same reason the bucket labels
#: are: the ordering is part of the answer, and a page that sorted the two
#: hundred rows it was given would be sorting the top two hundred *by
#: discount*, which is the wrong two hundred for every order but that one.
SORTS: dict[str, tuple[Any, ...]] = {
    "discount": (HotDeal.discount_percent.desc(), HotDeal.id.asc()),
    # Dollars off, which is a genuinely different question from percent off and
    # the reason both are offered. The docstring on :func:`deals` explains why
    # this is not the *default*: a 30% saving is $200 on a Mosin and $2,000 on
    # a Luger, so this order leads with the expensive guns whatever the bargain
    # was. That is a fine thing to ask for and a poor thing to assume.
    "saving": ((HotDeal.median_price - HotDeal.price).desc(), HotDeal.id.asc()),
    "price_asc": (HotDeal.price.asc(), HotDeal.id.asc()),
    "price_desc": (HotDeal.price.desc(), HotDeal.id.asc()),
    # ``first_listed_at`` is carried across a rebuild, so this really is "new
    # since you last looked" and not "found by the most recent pass", which
    # every row shares and which would therefore sort by nothing at all.
    "newest": (HotDeal.first_listed_at.desc(), HotDeal.id.asc()),
}

#: The order the page offers them in, and the default when none is asked for.
SORT_SEQUENCE: tuple[str, ...] = ("discount", "saving", "price_asc", "price_desc", "newest")
DEFAULT_SORT = "discount"

#: What each order is called where a person reads it, server-side for the same
#: reason :data:`BUCKET_LABELS` is.
SORT_LABELS = {
    "discount": "Biggest discount",
    "saving": "Biggest saving",
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
    "newest": "Newly found",
}

#: Which preference column governs each bucket.
BUCKET_PREFERENCE = {
    "rifle": "include_rifles",
    "pistol": "include_handguns",
    "police_surplus": "include_police_surplus",
}

#: Most deals one email will carry. A pass that has just been switched on finds
#: several hundred at once, and a first email listing all of them is not a
#: thing anybody reads -- it is a thing that teaches them to filter the sender.
#: The rest are not lost: they stay unsent and go out next time.
MAX_PER_EMAIL = 25


class Status:
    """What the last pass did, as stored on the settings row."""

    OK = "ok"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(frozen=True)
class Placed:
    """One listing, placed among its peers. The input to the rule."""

    item: Item
    bucket: str
    price: float
    median: float
    discount: float
    cheaper_than: int
    peers: int
    vendors: int
    #: What makes two of these the *same offer*: the same gun, at the same
    #: shop, at the same price. See :func:`_collapse_duplicates`.
    offer: tuple[object, int, float]


@dataclass(frozen=True)
class RefreshResult:
    considered: int
    placed: int
    found: int
    seconds: float


# -- settings ---------------------------------------------------------------
def settings(session: Session) -> HotDealSetting:
    """The one settings row, created if a database somehow lacks it.

    Migration 0036 seeds it, so the create here is for a database built some
    other way -- a ``create_all()`` in a test, an old stamp -- rather than a
    path anybody takes on purpose. The same shape ``backup.settings`` has.
    """
    row = session.get(HotDealSetting, 1)
    if row is None:
        row = HotDealSetting(id=1)
        session.add(row)
        session.commit()
    return row


def is_due(session: Session, *, now: datetime | None = None) -> bool:
    """Whether a pass is owed.

    Measured from ``last_run_at`` rather than from a timer in the scheduler,
    for the reason backups measure from the newest file: a process that
    restarts twice a day should still refresh on its own cadence, and a timer
    resets on every restart while a stored timestamp does not.
    """
    row = settings(session)
    if not row.enabled:
        return False
    last = as_utc(row.last_run_at)
    if last is None:
        return True
    return (now or utcnow()) - last >= timedelta(hours=max(1, row.interval_hours))


# -- the pass ---------------------------------------------------------------
def bucket_of(item: Item) -> str | None:
    """Which of the three filters a listing belongs to, or None for neither.

    The browse page's partition, applied to a loaded row rather than in SQL --
    see ``search.KINDS``, which is the same rule and the authority on it.

    **One bucket, not several.** Browse counts a listing under every filter it
    matches; this stores one row per listing and has to choose. Police surplus
    wins because it is the most specific claim, and rifle over handgun for the
    handful of listings that read as both, which are nearly always a rifle
    sold with a pistol or a title the classifier read twice.
    """
    if item.is_police_surplus:
        return "police_surplus"
    if item.is_rifle:
        return "rifle"
    if item.is_pistol:
        return "pistol"
    return None


def _group_key(item: Item) -> tuple[int, str, str | None] | None:
    """What makes two listings peers, as a hashable key.

    The model and the cartridge always; the maker only where it tells two guns
    apart. This *is* :func:`pricing.peers`'s rule -- see the docstring there
    for why -- rearranged from a query per listing into a key that groups them
    all in one pass. ``test_hotdeals`` holds the two to the same answer.
    """
    if not (item.firearm_model_id and item.caliber and item.current_price):
        return None
    if pricing.maker_distinguishes(item.firearm_model):
        if not item.manufacturer:
            # Cannot be told apart from the others, and guessing costs more
            # than leaving it alone. pricing.peers returns [] here.
            return None
        return (item.firearm_model_id, item.caliber, item.manufacturer)
    return (item.firearm_model_id, item.caliber, None)


def _place_everything(session: Session) -> tuple[list[Placed], int]:
    """Every candidate listing, placed among its peers. (placed, considered)

    One query for the pool, then arithmetic. The pool is *wider* than the
    candidates on purpose: peers include sold listings, because the listing
    page counts them and a reader clicking through must not meet a different
    number under the same words.
    """
    pool = list(
        session.execute(
            select(Item)
            .options(selectinload(Item.firearm_model))
            .where(
                Item.is_active.is_(True),
                Item.current_price.is_not(None),
                Item.firearm_model_id.is_not(None),
                Item.caliber.is_not(None),
            )
        )
        .scalars()
        .all()
    )

    groups: dict[tuple[int, str, str | None], list[Item]] = {}
    for item in pool:
        key = _group_key(item)
        if key is not None:
            groups.setdefault(key, []).append(item)

    placed: list[Placed] = []
    considered = 0
    for members in groups.values():
        if len(members) < pricing.MIN_PEERS:
            continue
        prices = sorted(float(other.current_price or 0) for other in members)
        median = pricing.percentile(prices, 50.0)
        vendors = len({other.site_id for other in members})
        for item in members:
            # A sold listing is a peer but never a deal: the buying
            # opportunity is over, and offering one is the wrong side of
            # useful -- the same judgment watchlist._alert_is_due makes.
            if item.is_sold:
                continue
            bucket = bucket_of(item)
            if bucket is None:
                continue
            considered += 1
            price = float(item.current_price or 0)
            if price <= 0 or median <= 0:
                continue
            # Strict, so a shelf of identical prices reports 0% rather than
            # every listing on it claiming to undercut the others.
            dearer = sum(1 for other in prices if other > price)
            placed.append(
                Placed(
                    item=item,
                    bucket=bucket,
                    price=price,
                    median=median,
                    discount=100.0 * (median - price) / median,
                    cheaper_than=round(100 * dearer / len(prices)),
                    peers=len(prices),
                    vendors=vendors,
                    offer=(key, item.site_id, round(price, 2)),
                )
            )
    return placed, considered


def _collapse_duplicates(keepers: list[Placed]) -> list[tuple[Placed, int]]:
    """One row per offer, with how many listings it stands for.

    **Dealers buy surplus by the crate and list it one rifle at a time.** A
    shop with nine W+F Bern K11s at $295 has nine genuinely cheap rifles and
    exactly one thing to tell somebody, and the page opened with nine
    identical rows. Measured on the catalog as it stands, 216 qualifying
    listings are 163 distinct offers -- a quarter of the page was repetition.

    Same gun, same shop, *same price*. Two K11s at $295 and $325 are two
    offers and both are shown: the price is the thing being reported, so a
    difference in it is a difference that matters. The representative is the
    lowest id, which is stable across passes and so keeps ``first_listed_at``
    attached to the same row rather than shuffling it between identical ones.
    """
    by_offer: dict[tuple[object, int, float], list[Placed]] = {}
    for entry in keepers:
        by_offer.setdefault(entry.offer, []).append(entry)
    collapsed = [
        (min(group, key=lambda entry: entry.item.id or 0), len(group))
        for group in by_offer.values()
    ]
    return sorted(collapsed, key=lambda pair: (-pair[0].discount, pair[0].item.id or 0))


def qualifies(placed: Placed, row: HotDealSetting) -> bool:
    """Whether one placed listing clears the rule. See the module docstring."""
    return (
        placed.cheaper_than >= row.min_cheaper_than
        and placed.discount >= row.min_discount_percent
        and placed.discount <= row.max_discount_percent
        and placed.vendors >= row.min_vendors
    )


def refresh(session: Session, *, now: datetime | None = None) -> RefreshResult:
    """Rebuild the hot deals table. Returns what the pass found.

    **The table is replaced, not merged**, because it is a cache: every row is
    derived from prices that may all have moved, and a row nothing recomputed
    is a deal that has gone away. The one thing carried across is
    ``first_listed_at`` -- "new since you last looked" has to survive the
    recompute that finds the same deal again.

    Records what happened on the settings row either way, so the page can say
    so without anybody reading a log.
    """
    now = now or utcnow()
    started = time.monotonic()
    row = settings(session)

    placed, considered = _place_everything(session)
    keepers = _collapse_duplicates([entry for entry in placed if qualifies(entry, row)])

    # .tuples() rather than the rows themselves: a Row is only tuple-like,
    # and dict() wants the real thing.
    since: dict[int, datetime] = dict(
        session.execute(select(HotDeal.item_id, HotDeal.first_listed_at)).tuples().all()
    )
    session.execute(delete(HotDeal))
    session.flush()
    for entry, duplicates in keepers:
        session.add(
            HotDeal(
                item_id=entry.item.id,
                bucket=entry.bucket,
                price=entry.price,
                median_price=entry.median,
                discount_percent=round(entry.discount, 1),
                cheaper_than=entry.cheaper_than,
                peer_count=entry.peers,
                vendor_count=entry.vendors,
                duplicate_count=duplicates,
                first_listed_at=as_utc(since.get(entry.item.id)) or now,
                computed_at=now,
            )
        )

    seconds = round(time.monotonic() - started, 2)
    row.last_run_at = now
    row.last_status = Status.OK
    row.last_error = None
    row.last_deal_count = len(keepers)
    row.last_considered = considered
    row.last_seconds = seconds
    session.commit()
    log.info(
        "Hot deals: %s of %s considered listing(s) qualify (%.2fs).",
        len(keepers),
        considered,
        seconds,
    )
    return RefreshResult(
        considered=considered, placed=len(placed), found=len(keepers), seconds=seconds
    )


def record_failure(session: Session, exc: Exception, *, now: datetime | None = None) -> None:
    """Note that a pass failed, where the page will show it.

    ``last_run_at`` is moved too, deliberately: a pass that raises every time
    would otherwise stay permanently due and retry on every scheduler tick.
    """
    row = settings(session)
    row.last_run_at = now or utcnow()
    row.last_status = Status.FAILED
    row.last_error = f"{type(exc).__name__}: {exc}"[:500]
    session.commit()


# -- reading ----------------------------------------------------------------
def deals(
    session: Session,
    bucket: str | None = None,
    *,
    sort: str = DEFAULT_SORT,
    limit: int | None = None,
) -> list[HotDeal]:
    """The current deals, deepest discount first unless asked otherwise.

    The default is how far below the median rather than dollars saved: this is
    a catalog where a 30% saving is $200 on a Mosin and $2,000 on a Luger, and
    ordering by the dollars would put every expensive gun above every cheap one
    whatever the bargain was. It is offered as ``saving`` for the reader who
    wants exactly that, which is a different question rather than a wrong one.

    **The order is applied before the limit, which is the whole reason this
    takes a sort at all.** The page is capped, so a caller that asked for two
    hundred rows and re-ordered them itself would be re-ordering the two
    hundred deepest discounts -- the right answer for one order out of five,
    and a quietly wrong one for the other four.

    An unknown sort falls back to the default rather than raising. The HTTP
    layer refuses it loudly before it ever reaches here; this is the belt to
    that braces, and a background caller is better served by a sane order than
    by a traceback.
    """
    statement = (
        select(HotDeal)
        .options(selectinload(HotDeal.item).selectinload(Item.photos))
        .order_by(*SORTS.get(sort, SORTS[DEFAULT_SORT]))
    )
    if bucket:
        statement = statement.where(HotDeal.bucket == bucket)
    if limit:
        statement = statement.limit(limit)
    return list(session.execute(statement).scalars().all())


def counts(session: Session) -> dict[str, int]:
    """How many deals each filter holds, so the page can label its tabs."""
    found = dict.fromkeys(BUCKETS, 0)
    for deal in session.execute(select(HotDeal.bucket)).scalars():
        if deal in found:
            found[deal] += 1
    return found


# -- who wants to hear about them -------------------------------------------
def preference(session: Session, user: User) -> HotDealPreference:
    """This reader's subscription, created on first sight with the defaults.

    Only called where a row is about to be *written*. Readers go through
    :func:`wants`, which treats a missing row as "subscribed to all three" --
    that absence is what gives every existing account the feature without a
    backfill, and creating rows just to read them would throw it away.
    """
    row = session.execute(
        select(HotDealPreference).where(HotDealPreference.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        row = HotDealPreference(user_id=user.id)
        session.add(row)
        session.commit()
    return row


def wants(row: HotDealPreference | None, bucket: str) -> bool:
    """Whether this subscription covers a bucket. None means all three."""
    if row is None:
        return True
    if not row.enabled:
        return False
    return bool(getattr(row, BUCKET_PREFERENCE[bucket], False))


def subscribed_user_ids(session: Session) -> list[int]:
    """Everybody who should be mailed, which is everybody who has not opted out.

    Two halves, because the default lives in the *absence* of a row: every
    active account, minus the ones whose row says no.
    """
    active = set(session.execute(select(User.id).where(User.is_active.is_(True))).scalars().all())
    off = set(
        session.execute(
            select(HotDealPreference.user_id).where(HotDealPreference.enabled.is_(False))
        )
        .scalars()
        .all()
    )
    return sorted(active - off)


def unsent_for(session: Session, user: User, *, limit: int = MAX_PER_EMAIL) -> list[HotDeal]:
    """The deals this reader has not been told about, at their current price.

    **A price, not a timestamp**, which is the whole of what makes each email
    different from the last. Without a memory every pass would mail the same
    hundred listings; with a timestamp, a listing that dropped again after we
    mentioned it would read as "already told you about that one". A price gets
    both right -- and it is the same reasoning, and the same shape, as
    ``WatchedItem.alerted_price``.
    """
    row = session.execute(
        select(HotDealPreference).where(HotDealPreference.user_id == user.id)
    ).scalar_one_or_none()
    if row is not None and not row.enabled:
        return []

    told: dict[int, float] = dict(
        session.execute(
            select(HotDealNotice.item_id, HotDealNotice.price).where(
                HotDealNotice.user_id == user.id
            )
        )
        .tuples()
        .all()
    )
    current = deals(session)
    # Asked once for every deal rather than once per deal: a reader's saved
    # searches are a handful of queries, each run over the whole set.
    matched = (
        matching_saved_searches(session, user, [deal.item_id for deal in current])
        if row is not None and row.match_saved_searches
        else None
    )
    fresh: list[HotDeal] = []
    for deal in current:
        if not wants(row, deal.bucket):
            continue
        if matched is not None and deal.item_id not in matched:
            continue
        seen = told.get(deal.item_id)
        # Compared in cents. These are dollars stored as floats, and a price
        # round-tripped through a scrape and a column can differ from itself
        # in the last bits -- which would mail the same listing every pass.
        if seen is not None and round(seen, 2) == round(deal.price, 2):
            continue
        fresh.append(deal)
        if len(fresh) >= limit:
            break
    return fresh


#: Item ids per query when asking a saved search which deals it matches.
#: SQLite caps a statement at 999 bound variables; the pass can find more deals
#: than that, and a saved search adds bound values of its own.
_IDS_PER_QUERY = 500


def saved_search_count(session: Session, user: User) -> int:
    return len(session.execute(select(SavedSearch.id).where(SavedSearch.user_id == user.id)).all())


def matching_saved_searches(session: Session, user: User, item_ids: Sequence[int]) -> set[int]:
    """Which of these listings at least one of this reader's saved searches matches.

    **Run through the search module, never re-read.** Each stored query goes
    through :func:`search.parse_query` and :func:`search.apply_filters`, the
    same two calls the browse page and the saved-search email make, so "this
    deal matches your Swiss rifles search" means exactly what clicking that
    search shows. A second reading of the query string written here would
    drift from the first the next time a filter is added, and the reader would
    believe the email.

    A stored query that no longer parses is skipped and logged rather than
    raised: this runs unattended after a pass, and one rotted search must not
    cost the reader every other one. No searches at all matches nothing -- the
    reader asked for "only my searches", and has none.
    """
    from . import search  # here, not at the top: search imports curio and more

    wanted = list(dict.fromkeys(item_ids))
    if not wanted:
        return set()
    matched: set[int] = set()
    for saved in session.execute(
        select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.id)
    ).scalars():
        try:
            query = search.parse_query(saved.query)
        except search.BadQuery as exc:
            log.warning(
                "Saved search %s (%r) no longer parses; skipped for hot deals: %s",
                saved.id,
                saved.name,
                exc,
            )
            continue
        for start in range(0, len(wanted), _IDS_PER_QUERY):
            chunk = wanted[start : start + _IDS_PER_QUERY]
            statement = search.apply_filters(select(Item.id), **query.filters).where(
                Item.id.in_(chunk)
            )
            matched.update(session.execute(statement).scalars().all())
    return matched


def mark_sent(
    session: Session, user: User, sent: Iterable[HotDeal], *, now: datetime | None = None
) -> None:
    """Record what this reader was told, and at what price.

    The caller's job rather than the sender's, and called only after a send
    returns: a failure is then retried next pass rather than recorded as
    delivered. The same ordering ``watchlist.mark_alerted`` exists to preserve.
    """
    now = now or utcnow()
    existing = {
        notice.item_id: notice
        for notice in session.execute(
            select(HotDealNotice).where(HotDealNotice.user_id == user.id)
        ).scalars()
    }
    for deal in sent:
        notice = existing.get(deal.item_id)
        if notice is None:
            session.add(
                HotDealNotice(user_id=user.id, item_id=deal.item_id, price=deal.price, sent_at=now)
            )
        else:
            notice.price = deal.price
            notice.sent_at = now


def forget_stale_notices(session: Session) -> int:
    """Drop notices for listings that are no longer deals at all.

    Housekeeping, not correctness: a notice for a listing nobody will be
    offered again is dead weight, and without this the table grows with every
    listing that was ever briefly cheap. Returns how many went.
    """
    live = set(session.execute(select(HotDeal.item_id)).scalars().all())
    stale = [
        notice_id
        for notice_id, item_id in session.execute(select(HotDealNotice.id, HotDealNotice.item_id))
        if item_id not in live
    ]
    if stale:
        session.execute(delete(HotDealNotice).where(HotDealNotice.id.in_(stale)))
        session.commit()
    return len(stale)


def label(bucket: str) -> str:
    return BUCKET_LABELS.get(bucket, bucket)


def known_bucket(value: str | None) -> str | None:
    """A bucket name from a query string, or None. Raises nothing."""
    return value if value in BUCKETS else None


def known_sort(value: str | None) -> str | None:
    """A sort name from a query string, or None. Raises nothing."""
    return value if value in SORTS else None


def sort_label(sort: str) -> str:
    return SORT_LABELS.get(sort, sort)


def bucket_sequence() -> Sequence[str]:
    return BUCKETS
