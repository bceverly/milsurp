"""When a price we have already mailed somebody about is news again.

Two notifications remember what they said: a watchlist target alert
(``WatchedItem.alerted_price`` and ``alerted_at``) and a hot-deal email
(``HotDealNotice.price`` and ``sent_at``). Both used to treat *any different
price* as news, which got two cases wrong:

- **A recurring sale went dark.** $500, then $450 (mailed), back to $500, then
  $450 again: the second $450 equalled what we had said, so it was never
  mailed. A shop running the same markdown every month was announced once,
  ever -- and vendor mailing lists make exactly that pattern common.
- **A rise was mailed.** $450 (mailed) and then $480, still under the target or
  still a deal, differed from what we had said, so it went out as though it
  were good news. A price going back up is never news.

The rule now, for a listing that otherwise qualifies:

1. never mentioned to this reader -- news;
2. mentioned longer ago than ``renotify_after_days`` -- news again, as a
   reminder, so nothing stays silent forever on the strength of one old email;
3. **a new low** below the price we mentioned -- news;
4. **back at or below that price after going above it** since we said so --
   news. "Went above" is read from ``price_history``, which records every
   price a scan sees, so nothing extra has to be written as prices move;
5. anything else, including every rise -- not news.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HotDealSetting, PriceHistory, as_utc

#: The expiry when no settings row exists, and the model's column default.
DEFAULT_RENOTIFY_AFTER_DAYS = 30

#: Prices are dollars stored as floats; compared in cents so a price
#: round-tripped through a scrape and a column is still equal to itself.
_CENT = 0.005


def renotify_after_days(session: Session) -> int:
    """The administrator's setting, 0 meaning a notice never expires."""
    row = session.execute(select(HotDealSetting).limit(1)).scalar_one_or_none()
    if row is None or row.renotify_after_days is None:
        return DEFAULT_RENOTIFY_AFTER_DAYS
    return row.renotify_after_days


def peaks_since(session: Session, told: Iterable[tuple[int, datetime | None]]) -> dict[int, float]:
    """The highest price each listing has had since we last mentioned it.

    ``told`` is ``(item_id, when we said so)`` pairs. A listing with no
    history since then is absent from the answer.
    """
    since: dict[int, datetime] = {}
    for item_id, when in told:
        stamp = as_utc(when)
        if stamp is not None:
            since[item_id] = stamp
    if not since:
        return {}
    # The column holds naive UTC, so the bound is compared naive too.
    earliest = min(since.values()).replace(tzinfo=None)
    peaks: dict[int, float] = {}
    ids = list(since)
    # Chunked for SQLite's bound-variable limit, as hot deals' saved-search
    # matching is.
    for start in range(0, len(ids), 500):
        rows = session.execute(
            select(PriceHistory.item_id, PriceHistory.price, PriceHistory.observed_at).where(
                PriceHistory.item_id.in_(ids[start : start + 500]),
                PriceHistory.observed_at > earliest,
            )
        ).all()
        for item_id, price, observed_at in rows:
            seen = as_utc(observed_at)
            if seen is None or seen <= since[item_id]:
                continue
            if price > peaks.get(item_id, float("-inf")):
                peaks[item_id] = price
    return peaks


def is_news(
    price: float,
    told_price: float | None,
    told_at: datetime | None,
    *,
    peak_since: float | None,
    now: datetime,
    after_days: int,
) -> bool:
    """Whether ``price`` is worth mailing again. See the module docstring.

    ``now`` is timezone-aware, as :func:`utcnow` returns it.
    """
    if told_price is None:
        return True
    told = as_utc(told_at)
    if after_days > 0 and told is not None and told <= now - timedelta(days=after_days):
        return True
    if price < told_price - _CENT:
        return True
    rebounded = peak_since is not None and peak_since > told_price + _CENT
    return rebounded and price <= told_price + _CENT
