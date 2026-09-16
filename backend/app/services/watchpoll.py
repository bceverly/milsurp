"""Re-read the listings somebody is watching, faster than their shop is scanned.

A watched rifle reaching its price is news that keeps badly: the shelf holds
one of it, and the reader asked to be told. But a price only *changes* in this
database when a scan stores it, and twenty-five of the twenty-eight shops are
scanned once a day -- so an alert that fires the instant the database moves is
still a day behind the shop.

This closes that. A watchlist is tens of listings, so re-reading each one every
couple of hours is forty requests an hour against shops that take thousands
during a single catalog scan. The cost is negligible *because it is one page
per listing*, which is what `SiteScraper.check_price` is for.

**It reads through ScrapeContext like everything else.** robots.txt, the host
cooldown register and the politeness delay all apply, so a shop that has asked
to be left alone is left alone -- the poller is the most frequent thing this
application does and would be the first to earn a block if it were not.

**A shop that publishes no structured price is skipped, not guessed at.**
Fourteen of the twenty-eight publish one this can read; the rest keep the
freshness their scan gives them. Guessing a price out of theme markup would
eventually mail somebody about a rifle that is not on offer, which is worse
than telling them a few hours late.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Config
from ..models import Item, PriceHistory, WatchedItem, as_utc, utcnow
from ..scrapers import get_scraper
from ..scrapers.base import ScrapeContext, ScrapeError
from . import cooldown

log = logging.getLogger("milsurp.watchpoll")

#: Listings to re-read in one pass. A ceiling rather than a target: it stops a
#: watchlist that has grown surprisingly from turning one tick into a crawl,
#: and the ones left over are read on the next pass.
MAX_PER_PASS = 60


@dataclass
class Result:
    """What one pass did, for the log line."""

    checked: int = 0
    changed: int = 0
    sold: int = 0
    skipped: int = 0
    failed: int = 0


def watched_items(session: Session) -> list[Item]:
    """Every distinct listing anybody is watching, oldest check first.

    Distinct, because two readers watching one rifle is one request. Oldest
    first so a watchlist longer than MAX_PER_PASS is read round-robin rather
    than the same head of it every time.
    """
    rows = (
        session.execute(
            select(WatchedItem).options(selectinload(WatchedItem.item)).order_by(WatchedItem.id)
        )
        .scalars()
        .all()
    )
    seen: dict[int, Item] = {}
    for watch in rows:
        item = watch.item
        # A de-listed or sold listing is not re-read: its story has ended, and
        # the watcher has already been told. Keeping it in the rotation would
        # spend requests on rifles nobody can buy.
        if item is None or not item.is_active or item.is_sold:
            continue
        seen.setdefault(item.id, item)
    return sorted(
        seen.values(),
        # as_utc, because the column is naive and _EPOCH is not: comparing
        # the two directly raises rather than sorting.
        key=lambda item: (as_utc(item.last_checked_at) or _EPOCH, item.id),
    )


#: Sorts a never-checked listing first, which is what it deserves.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _record(session: Session, item: Item, price: float, when: datetime) -> bool:
    """Store a new price the way a scan does. True when it actually moved.

    Deliberately the same columns and the same history row -- the watchlist,
    the price spectrum and the digest all read those, and a price arriving by
    a second route must be indistinguishable from one a scan found. The
    history row carries no scan_run_id, which is already nullable: this did
    not happen during a scan and inventing a run to point at would put a lie
    in the scan history to keep a foreign key company.
    """
    if round((item.current_price or -1) * 100) == round(price * 100):
        return False
    item.previous_price = item.current_price
    item.current_price = price
    item.price_changed_at = when
    item.lowest_price = price if item.lowest_price is None else min(item.lowest_price, price)
    item.highest_price = price if item.highest_price is None else max(item.highest_price, price)
    session.add(
        PriceHistory(
            item_id=item.id,
            scan_run_id=None,
            price=price,
            currency=item.currency,
            observed_at=when,
        )
    )
    return True


def run(session: Session, config: Config, limit: int = MAX_PER_PASS) -> Result:
    """Re-read watched listings and store what changed."""
    result = Result()
    items = watched_items(session)[:limit]
    if not items:
        return result

    ctx = ScrapeContext(config)
    for item in items:
        scraper = get_scraper(_slug_of(item))
        if scraper is None:
            result.skipped += 1
            continue
        # The register is consulted before the request rather than after the
        # refusal: this runs every couple of hours, and walking into a host
        # that has asked for quiet is how a poll turns into a block.
        if cooldown.paused_for(item.url) > 0:
            result.skipped += 1
            continue
        now = utcnow()
        try:
            found = scraper.check_price(ctx, item.url, key=item.external_key)
        except ScrapeError as exc:
            result.failed += 1
            log.info("Watch poll: %s refused (%s)", item.url, exc)
            continue
        except Exception:
            result.failed += 1
            log.exception("Watch poll raised for %s", item.url)
            continue

        # Marked checked even when the shop published nothing this can read, so
        # the round-robin moves on rather than asking the same unreadable page
        # first on every pass.
        item.last_checked_at = now
        result.checked += 1
        if found is None:
            result.skipped += 1
            continue
        if found.sold_out and not item.is_sold:
            item.is_sold = True
            item.price_changed_at = now
            result.sold += 1
        if _record(session, item, found.price, now):
            result.changed += 1
    session.commit()
    return result


def _slug_of(item: Item) -> str:
    site = item.site
    return site.slug if site is not None else ""
