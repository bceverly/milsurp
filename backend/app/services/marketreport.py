"""The monthly market report: what got cheaper, what got scarce, what sold fast.

The digest is a shopping list -- your sites, what is new, what dropped -- and
the Market page answers "what does it cost" for whoever opens it. Neither says
how the market *moved*. This does, once a month, for whoever asks for it.

**Then and now, reconstructed.** The catalog keeps every price change
(``price_history``) and when each listing appeared, sold or came down, so the
shelf as it stood on any earlier day can be rebuilt: a listing was on it if it
had appeared and had not yet left, at the last price recorded before that day.
Each armory model's median then is compared with its median now.

**The window is what the data covers.** Thirty days, or fewer when the
catalog has not been watched that long -- production's history begins on 5
September 2026 -- and the email says which. A comparison against a day before
the first scan would set a model's whole shelf against nothing.

**Same rules as the Market page.** Firearms only, models with at least five
listings at *both* ends, medians not means, and a move smaller than five
percent is not a move worth a line in an email.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..models import EmailLog, EmailStatus, FirearmModel, Item, PriceHistory, Site, User, utcnow
from . import mailer

WINDOW_DAYS = 30
#: Fewer than this many days of history and there is nothing to report.
MIN_WINDOW_DAYS = 7
#: Listings a model needs at *both* ends before its median is compared. Eight
#: rather than the Market page's five: a move is a difference of two medians,
#: and over five listings that difference is mostly which five they were.
MIN_LISTINGS = 8
#: And the shelf has to be recognizably the same shelf. A model whose count
#: more than halved or doubled has a different mix of guns at each end, and
#: the median moving says that, not that prices moved -- so it is reported
#: under "got scarcer" (or not at all) rather than as cheaper or dearer.
MAX_MIX_CHANGE = 2.0
#: A move smaller than this is noise, not news.
MIN_MOVE = 0.05
#: How many lines each section carries.
LINES = 5


@dataclass(frozen=True)
class Move:
    model: str
    model_id: int
    then: float
    now: float
    then_count: int
    now_count: int

    @property
    def change(self) -> float:
        return (self.now - self.then) / self.then if self.then else 0.0

    @property
    def count_change(self) -> float:
        return (self.now_count - self.then_count) / self.then_count if self.then_count else 0.0


@dataclass(frozen=True)
class Seller:
    model: str
    model_id: int
    sold: int
    median_days: float


@dataclass
class Report:
    since: datetime
    until: datetime
    days: int
    cheaper: list[Move] = field(default_factory=list)
    dearer: list[Move] = field(default_factory=list)
    scarcer: list[Move] = field(default_factory=list)
    fastest: list[Seller] = field(default_factory=list)
    arrivals: int = 0
    busiest_shop: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.cheaper or self.dearer or self.scarcer or self.fastest)


def _naive(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=None) if moment is not None else None


def build(session: Session, now: datetime | None = None) -> Report | None:
    """The report as of ``now``, or None when there is not yet a week of history."""
    now = _naive(now or utcnow())
    assert now is not None
    first = _naive(session.execute(select(func.min(Item.first_seen_at))).scalar_one_or_none())
    if first is None:
        return None
    # A week of settling after the first scans: those find every shelf at once.
    earliest = first + timedelta(days=MIN_WINDOW_DAYS)
    since = max(now - timedelta(days=WINDOW_DAYS), earliest)
    days = (now - since).days
    if days < MIN_WINDOW_DAYS:
        return None

    names = dict(session.execute(select(FirearmModel.id, FirearmModel.name)).all())
    rows = session.execute(
        select(
            Item.id,
            Item.site_id,
            Item.firearm_model_id,
            Item.current_price,
            Item.first_seen_at,
            Item.sold_at,
            Item.delisted_at,
            Item.is_active,
            Item.is_sold,
        ).where(
            (Item.is_rifle.is_(True) | Item.is_pistol.is_(True)),
            Item.is_parts_kit.is_(False),
            Item.firearm_model_id.is_not(None),
        )
    ).all()
    prices = _price_histories(session)

    then_prices: dict[int, list[float]] = defaultdict(list)
    now_prices: dict[int, list[float]] = defaultdict(list)
    durations: dict[int, list[float]] = defaultdict(list)
    report = Report(since=since, until=now, days=days)
    arrivals_by_site: dict[int, int] = defaultdict(int)

    for row in rows:
        seen = _naive(row.first_seen_at)
        left = min(
            (moment for moment in (_naive(row.sold_at), _naive(row.delisted_at)) if moment),
            default=None,
        )
        if seen is None:
            continue
        # On the shelf then: appeared before, not yet gone. A listing marked
        # sold with no date of sale cannot be placed in time -- Centerfire keeps
        # sold guns on its pages, and 137 of its K98ks would otherwise read as
        # for sale then and gone now -- so it is left out of "then" entirely.
        undated_sale = row.is_sold and row.sold_at is None
        if seen <= since and (left is None or left > since) and not undated_sale:
            then = [price for at, price in prices.get(row.id, []) if at <= since]
            if then and then[-1] > 0:
                then_prices[row.firearm_model_id].append(then[-1])
        if row.is_active and not row.is_sold and row.current_price and row.current_price > 0:
            now_prices[row.firearm_model_id].append(float(row.current_price))
        if seen > since:
            report.arrivals += 1
            arrivals_by_site[row.site_id] += 1
            if left is not None and left > seen:
                durations[row.firearm_model_id].append((left - seen).total_seconds() / 86400)

    moves = _moves(then_prices, now_prices, names)
    steady = [
        m for m in moves if 1 / MAX_MIX_CHANGE <= m.now_count / m.then_count <= MAX_MIX_CHANGE
    ]
    report.cheaper = sorted((m for m in steady if m.change <= -MIN_MOVE), key=lambda m: m.change)[
        :LINES
    ]
    report.dearer = sorted((m for m in steady if m.change >= MIN_MOVE), key=lambda m: -m.change)[
        :LINES
    ]
    report.scarcer = sorted(
        (m for m in moves if m.count_change <= -0.2), key=lambda m: m.count_change
    )[:LINES]
    report.fastest = sorted(
        (
            Seller(names.get(model_id, "?"), model_id, len(found), statistics.median(found))
            for model_id, found in durations.items()
            if len(found) >= 3
        ),
        key=lambda seller: (seller.median_days, -seller.sold),
    )[:LINES]
    if arrivals_by_site:
        busiest = max(arrivals_by_site, key=lambda site_id: arrivals_by_site[site_id])
        site = session.get(Site, busiest)
        report.busiest_shop = site.name if site else None
    return report


def _price_histories(session: Session) -> dict[int, list[tuple[datetime, float]]]:
    """Every listing's price changes, oldest first."""
    prices: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for item_id, observed_at, price in session.execute(
        select(PriceHistory.item_id, PriceHistory.observed_at, PriceHistory.price).order_by(
            PriceHistory.observed_at
        )
    ).all():
        prices[item_id].append((observed_at.replace(tzinfo=None), float(price)))
    return prices


def _moves(
    then_prices: dict[int, list[float]],
    now_prices: dict[int, list[float]],
    names: dict[int, str],
) -> list[Move]:
    """Each model's median then and now, where both ends have enough listings."""
    moves = []
    for model_id, then in then_prices.items():
        current = now_prices.get(model_id, [])
        if len(then) < MIN_LISTINGS or len(current) < MIN_LISTINGS:
            continue
        moves.append(
            Move(
                model=names.get(model_id, "?"),
                model_id=model_id,
                then=statistics.median(then),
                now=statistics.median(current),
                then_count=len(then),
                now_count=len(current),
            )
        )
    return moves


# ---------------------------------------------------------------------------
# The email
# ---------------------------------------------------------------------------
def render(user: User, report: Report, config: Config) -> tuple[str, str, dict[str, bytes]]:
    """``(subject, html_body, inline_images)``."""
    from .digest import (
        BLUE,
        BRAND,
        INK,
        MARK_CID,
        MUTED,
        NAVY,
        NAVY_DEEP,
        PAPER,
        SILVER,
        _e,
        _mark_bytes,
        _money,
        inline_images,
    )

    base = config.server.public_url
    month = report.until.strftime("%B %Y")
    subject = f"{BRAND}: the market, {month}"

    def money(value: float) -> str:
        return _money(value, "USD")

    def link(model_id: int, name: str) -> str:
        return (
            f'<a href="{_e(base)}/?model={model_id}" style="color:{BLUE};'
            f'text-decoration:none;font-weight:600;">{_e(name)}</a>'
        )

    def section(title: str, lines: list[str], note: str = "") -> str:
        if not lines:
            return ""
        items = "".join(f'<li style="margin:4px 0;">{line}</li>' for line in lines)
        aside = (
            f'<div style="color:{MUTED};font-size:12px;margin-top:4px;">{note}</div>'
            if note
            else ""
        )
        return f"""
  <tr><td style="padding:20px 24px 0;color:{INK};font-size:14px;line-height:1.5;">
    <div style="font-weight:700;color:{NAVY};font-size:15px;">{_e(title)}</div>
    <ul style="margin:6px 0 0;padding-left:18px;">{items}</ul>{aside}
  </td></tr>"""

    cheaper = [
        f"{link(m.model_id, m.model)} — typically {money(m.now)}, down "
        f"{abs(m.change) * 100:.0f}% from {money(m.then)}"
        for m in report.cheaper
    ]
    dearer = [
        f"{link(m.model_id, m.model)} — typically {money(m.now)}, up "
        f"{m.change * 100:.0f}% from {money(m.then)}"
        for m in report.dearer
    ]
    scarcer = [
        f"{link(m.model_id, m.model)} — {m.now_count} listed, down from {m.then_count}"
        for m in report.scarcer
    ]
    fastest = [
        f"{link(s.model_id, s.model)} — typically gone in {s.median_days:.0f} "
        f"day{'s' if round(s.median_days) != 1 else ''} ({s.sold} watched)"
        for s in report.fastest
    ]
    window = (
        f"the last {report.days} days"
        if report.days >= 28
        else f"the {report.days} days since there was enough history to compare"
    )
    arrivals = (
        f"{report.arrivals:,} guns arrived across the shops"
        + (f", the most at {_e(report.busiest_shop)}" if report.busiest_shop else "")
        + "."
    )
    mark = (
        f'<img src="cid:{MARK_CID}" width="132" height="82" alt="{_e(BRAND)}" '
        f'style="display:block;margin:0 auto;border:0;" />'
        if _mark_bytes() is not None
        else ""
    )
    body = f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(subject)}</title></head>
<body style="margin:0;padding:0;background:{PAPER};
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{PAPER};padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="max-width:620px;background:#FFFFFF;border-radius:12px;overflow:hidden;
              box-shadow:0 1px 3px rgba(10,34,64,.12);">
  <tr><td style="background:{NAVY};padding:24px;text-align:center;">
    {mark}
    <div style="color:#FFFFFF;font-size:20px;font-weight:700;margin-top:10px;">{BRAND}</div>
    <div style="color:{SILVER};font-size:12px;margin-top:4px;">The market, {_e(month)}</div>
  </td></tr>
  <tr><td style="padding:20px 24px 0;color:{INK};font-size:14px;line-height:1.5;">
    Hello {_e(user.full_name or user.username)}, here is how the surplus market moved over
    {window}. {arrivals} Each figure is the median asking price of a model's listings,
    across every shop, for models with at least {MIN_LISTINGS} listed at both ends.
  </td></tr>
  {section("Got cheaper", cheaper)}
  {section("Got dearer", dearer)}
  {section("Got scarcer", scarcer, "Fewer listed now than at the start of the window.")}
  {section("Sold fastest", fastest, "Days from appearing to selling or coming down.")}
  <tr><td style="padding:26px 24px 24px;">
    <a href="{_e(base)}/market" style="display:inline-block;background:{BLUE};color:#FFFFFF;
       text-decoration:none;padding:11px 22px;border-radius:6px;font-weight:600;font-size:14px;">
       Open the Market</a>
  </td></tr>
  <tr><td style="background:{NAVY_DEEP};padding:16px 24px;color:{SILVER};font-size:11px;
      line-height:1.6;">
    You asked for this monthly report on your
    <a href="{_e(base)}/settings" style="color:#FFFFFF;">email settings</a>, where it can be
    switched off.
  </td></tr>
</table></td></tr></table></body></html>"""
    return subject, body, inline_images()


def send(
    session: Session, user: User, config: Config | None = None, now: datetime | None = None
) -> EmailLog:
    """Build and mail the report to one reader. Recorded in the email history."""
    config = config or get_config()
    report = build(session, now)
    if report is None or report.empty:
        entry = EmailLog(
            user_id=user.id,
            status=EmailStatus.SKIPPED,
            subject="Market report",
            error_message="Not enough history yet to say how the market moved.",
        )
        session.add(entry)
        session.commit()
        return entry
    subject, body, images = render(user, report, config)
    status, error = EmailStatus.SENT, None
    try:
        mailer.send_html(user.email, subject, body, config=config, inline_images=images)
    except mailer.MailError as exc:
        status, error = EmailStatus.FAILED, str(exc)
    entry = EmailLog(
        user_id=user.id,
        status=status,
        subject=subject,
        error_message=error,
        body_html=body,
        body_text=mailer.html_to_text(body),
    )
    session.add(entry)
    session.commit()
    return entry


def due(now: datetime | None = None) -> bool:
    """Whether today is report day: the first of the month, from 13:00 UTC."""
    now = now or utcnow()
    return now.day == 1 and now.hour >= 13
