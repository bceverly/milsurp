"""Builds and sends each user's periodic HTML digest.

What goes in a digest is entirely the recipient's choice: which sites, whether
to include new listings, whether to include price reductions, and a hard cap on
how many of each to show **per site** so a big scan cannot produce a
hundred-item email.

"New" means first seen after the user's own watermark (``last_digest_cutoff``),
not a fixed window, so nothing is missed when a digest is delayed and nothing is
repeated when two run close together.

Times inside the body are rendered in the recipient's chosen timezone, because
an email has no browser to convert them. Storage stays UTC throughout.
"""

from __future__ import annotations

import html
import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..models import (
    EmailLog,
    EmailPreference,
    EmailStatus,
    Item,
    Site,
    User,
    as_utc,
    utcnow,
)
from . import mailer

log = logging.getLogger("milsurp.digest")

BRAND = "Milsurp Monitor"

# The Senior Airman dress-insignia palette, inlined because email clients strip
# <style> blocks and have no CSS variables.
NAVY = "#0A2240"
NAVY_DEEP = "#061529"
BLUE = "#1B4B8F"
SILVER = "#C7CEDB"
PAPER = "#F4F6FA"
INK = "#11151C"
MUTED = "#5A6474"

#: Content-ID for the mark attached to every digest. Fixed rather than
#: generated: the HTML that references it is built in one place and the two
#: have to agree.
MARK_CID = "milsurp-mark"

#: The mark itself, written by `python scripts/brand.py` from the same geometry
#: as the favicon and the web header.
MARK_PATH = Path(__file__).resolve().parent.parent / "assets" / "insignia-email.png"


@lru_cache(maxsize=1)
def _mark_bytes() -> bytes | None:
    """The mark, read once, or None when it has not been generated.

    A missing file is not worth failing a send over — the header still carries
    the brand name — so this reports absence rather than raising, and the
    template leaves the image out entirely when it gets None.
    """
    try:
        return MARK_PATH.read_bytes()
    except OSError:
        log.warning("The email mark is missing at %s; sending without it.", MARK_PATH)
        return None


def inline_images() -> dict[str, bytes]:
    """What the digest HTML refers to by Content-ID."""
    payload = _mark_bytes()
    return {MARK_CID: payload} if payload is not None else {}


GREEN = "#1E7A46"


def _tz(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


# The shared helper lives in models.py next to utcnow(); this alias keeps the
# call sites in this module short.
_as_utc = as_utc


def _fmt_time(value: datetime | None, zone) -> str:
    value = _as_utc(value)
    if value is None:
        return "—"
    return value.astimezone(zone).strftime("%b %-d, %Y at %-I:%M %p %Z")


def _money(value: float | None, currency: str = "USD") -> str:
    if value is None:
        return "Call for price"
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{value:,.0f}" if float(value).is_integer() else f"{symbol}{value:,.2f}"


def selected_site_ids(session: Session, preference: EmailPreference) -> list[int]:
    """Sites this digest covers; no explicit selection means all enabled sites."""
    chosen = preference.site_ids
    enabled = session.execute(select(Site.id).where(Site.enabled.is_(True))).scalars().all()
    if not chosen:
        return list(enabled)
    return [site_id for site_id in chosen if site_id in set(enabled)]


def collect_new_items(
    session: Session, preference: EmailPreference, site_ids: list[int], since: datetime
) -> dict[int, list[Item]]:
    """New listings per site, capped at the user's per-site limit."""
    if not preference.include_new_items or not site_ids:
        return {}
    results: dict[int, list[Item]] = {}
    limit = max(1, preference.new_items_per_site_limit)
    for site_id in site_ids:
        items = (
            session.execute(
                select(Item)
                .where(
                    Item.site_id == site_id,
                    Item.is_active.is_(True),
                    Item.is_sold.is_(False),
                    Item.first_seen_at > since,
                )
                .order_by(Item.first_seen_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        if items:
            results[site_id] = list(items)
    return results


def collect_price_drops(
    session: Session, preference: EmailPreference, site_ids: list[int], since: datetime
) -> dict[int, list[Item]]:
    """Listings whose price fell since the watermark, capped per site."""
    if not preference.include_price_drops or not site_ids:
        return {}
    results: dict[int, list[Item]] = {}
    limit = max(1, preference.price_drops_per_site_limit)
    minimum = max(0.0, preference.minimum_price_drop)
    for site_id in site_ids:
        candidates = (
            session.execute(
                select(Item)
                .where(
                    Item.site_id == site_id,
                    Item.is_active.is_(True),
                    Item.is_sold.is_(False),
                    Item.price_changed_at.is_not(None),
                    Item.price_changed_at > since,
                    Item.previous_price.is_not(None),
                    Item.current_price.is_not(None),
                    Item.current_price < Item.previous_price,
                )
                .order_by(Item.price_changed_at.desc())
            )
            .scalars()
            .all()
        )
        # The minimum-drop filter is applied here rather than in SQL so the
        # comparison uses the same rounding as the rendered amount.
        drops = [
            item
            for item in candidates
            if item.previous_price is not None
            and item.current_price is not None
            and (item.previous_price - item.current_price) >= minimum
        ][:limit]
        if drops:
            results[site_id] = drops
    return results


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _e(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _item_row(item: Item, zone, show_drop: bool) -> str:
    price = _money(item.current_price, item.currency)
    if show_drop and item.previous_price is not None and item.current_price is not None:
        was = _money(item.previous_price, item.currency)
        delta = _money(item.previous_price - item.current_price, item.currency)
        price_block = (
            f'<span style="color:{GREEN};font-weight:700;font-size:16px;">{price}</span>'
            f'<span style="color:{MUTED};text-decoration:line-through;margin-left:8px;">{was}</span>'
            f'<div style="color:{GREEN};font-size:12px;margin-top:2px;">▼ {delta} lower</div>'
        )
    else:
        price_block = f'<span style="color:{NAVY};font-weight:700;font-size:16px;">{price}</span>'

    facts = " · ".join(_e(value) for value in (item.caliber, item.country, item.category) if value)
    seen = _fmt_time(item.price_changed_at if show_drop else item.first_seen_at, zone)

    return f"""
      <tr>
        <td style="padding:14px 0;border-bottom:1px solid #E3E8F0;">
          <a href="{_e(item.url)}" style="color:{NAVY};font-weight:600;font-size:15px;
             text-decoration:none;line-height:1.35;">{_e(item.title)}</a>
          <div style="color:{MUTED};font-size:12px;margin:5px 0 8px;">{facts or '&nbsp;'}</div>
          {price_block}
          <div style="color:{MUTED};font-size:11px;margin-top:6px;">{seen}</div>
        </td>
      </tr>"""


def _section(
    heading: str,
    grouped: dict[int, list[Item]],
    sites: dict[int, Site],
    zone,
    show_drop: bool,
) -> str:
    if not grouped:
        return ""
    blocks = []
    for site_id, items in grouped.items():
        site = sites.get(site_id)
        site_name = _e(site.name if site else "Unknown site")
        rows = "".join(_item_row(item, zone, show_drop) for item in items)
        blocks.append(f"""
        <tr><td style="padding:18px 24px 0;">
          <div style="font-size:12px;font-weight:700;letter-spacing:.10em;
               text-transform:uppercase;color:{BLUE};">{site_name}</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="border-collapse:collapse;">{rows}</table>
        </td></tr>""")
    return f"""
      <tr><td style="padding:26px 24px 0;">
        <h2 style="margin:0;font-size:17px;color:{INK};font-weight:700;
            border-left:4px solid {BLUE};padding-left:10px;">{_e(heading)}</h2>
      </td></tr>{''.join(blocks)}"""


def render_digest(
    user: User,
    new_items: dict[int, list[Item]],
    price_drops: dict[int, list[Item]],
    sites: dict[int, Site],
    since: datetime,
    config: Config,
) -> tuple[str, str]:
    """Return ``(subject, html_body)``."""
    # None means the user never chose one; the email has no browser to ask,
    # so UTC is the only honest fallback.
    preference = user.email_preference
    zone = _tz((preference.display_timezone if preference else None) or "UTC")
    base_url = config.server.public_url
    new_count = sum(len(v) for v in new_items.values())
    drop_count = sum(len(v) for v in price_drops.values())

    parts = []
    if new_count:
        parts.append(f"{new_count} new listing{'s' if new_count != 1 else ''}")
    if drop_count:
        parts.append(f"{drop_count} price drop{'s' if drop_count != 1 else ''}")
    subject = f"{BRAND}: {' and '.join(parts)}" if parts else f"{BRAND}: nothing new"

    # The mark travels with the message and is referenced by Content-ID.
    #
    # It used to be three CSS-border triangles under a text star, on the theory
    # that a remote image would be blocked and an attachment was not worth the
    # weight. The first half is true and the second was not: what those
    # triangles actually render as is three stacked wedges, which is not the
    # insignia and does not look like anything. Two kilobytes buys the real
    # mark, drawn from the same geometry as the favicon and the web header.
    mark = (
        f'<img src="cid:{MARK_CID}" width="132" height="82" alt="{_e(BRAND)}" '
        f'style="display:block;margin:0 auto;border:0;outline:none;text-decoration:none;" />'
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
    <div style="color:#FFFFFF;font-size:20px;font-weight:700;letter-spacing:.02em;
         margin-top:10px;">{BRAND}</div>
    <div style="color:{SILVER};font-size:12px;margin-top:4px;">
      Listings since {_fmt_time(since, zone)}
    </div>
  </td></tr>

  <tr><td style="padding:20px 24px 0;color:{INK};font-size:14px;line-height:1.5;">
    Hello {_e(user.full_name or user.username)}, here is what changed across the
    sites you follow.
  </td></tr>

  {_section('New listings', new_items, sites, zone, False)}
  {_section('Price reductions', price_drops, sites, zone, True)}

  {'' if (new_count or drop_count) else f'''
  <tr><td style="padding:24px;color:{MUTED};font-size:14px;">
    No new listings or price reductions this time.
  </td></tr>'''}

  <tr><td style="padding:26px 24px 24px;">
    <a href="{_e(base_url)}" style="display:inline-block;background:{BLUE};color:#FFFFFF;
       text-decoration:none;padding:11px 22px;border-radius:6px;font-weight:600;
       font-size:14px;">Open {BRAND}</a>
  </td></tr>

  <tr><td style="background:{NAVY_DEEP};padding:16px 24px;color:{SILVER};font-size:11px;
      line-height:1.6;">
    You are receiving this because digests are enabled on your
    {BRAND} account. Change the frequency, the sites, or turn digests off in
    <a href="{_e(base_url)}/settings" style="color:#FFFFFF;">your settings</a>.
  </td></tr>

</table></td></tr></table></body></html>"""
    return subject, body


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def next_send_time(preference: EmailPreference, from_time: datetime | None = None) -> datetime:
    base = from_time or utcnow()
    return base + timedelta(hours=max(1, preference.frequency_hours))


def build_digest(
    session: Session, user: User, config: Config | None = None
) -> tuple[str, str, int, int, datetime] | None:
    """Assemble one user's digest.

    Returns ``(subject, html, new_count, drop_count, cutoff)``, or ``None`` when
    the user has nothing selected at all.
    """
    config = config or get_config()
    preference = user.email_preference
    if preference is None:
        return None

    site_ids = selected_site_ids(session, preference)
    if not site_ids:
        return None

    # First run has no watermark: look back one interval rather than emailing
    # the entire back catalog.
    since = _as_utc(preference.last_digest_cutoff) or (
        utcnow() - timedelta(hours=max(1, preference.frequency_hours))
    )
    cutoff = utcnow()

    new_items = collect_new_items(session, preference, site_ids, since)
    price_drops = collect_price_drops(session, preference, site_ids, since)

    sites = {
        site.id: site
        for site in session.execute(select(Site).where(Site.id.in_(site_ids))).scalars().all()
    }
    subject, body = render_digest(user, new_items, price_drops, sites, since, config)
    new_count = sum(len(v) for v in new_items.values())
    drop_count = sum(len(v) for v in price_drops.values())
    return subject, body, new_count, drop_count, cutoff


def send_digest_for_user(
    session: Session, user: User, config: Config | None = None, force: bool = False
) -> EmailLog:
    """Build and send one digest, always recording the outcome."""
    config = config or get_config()
    preference = user.email_preference
    now = utcnow()

    if preference is None:
        log = EmailLog(
            user_id=user.id,
            status=EmailStatus.SKIPPED,
            error_message="User has no digest preferences.",
        )
        session.add(log)
        session.commit()
        return log

    built = build_digest(session, user, config)
    if built is None:
        preference.next_send_at = next_send_time(preference, now)
        log = EmailLog(
            user_id=user.id,
            status=EmailStatus.SKIPPED,
            error_message="No sites selected, or every selected site is disabled.",
        )
        session.add(log)
        session.commit()
        return log

    subject, body, new_count, drop_count, cutoff = built

    if not force and preference.skip_when_empty and not (new_count or drop_count):
        # Advance the schedule but not the watermark, so the next digest still
        # covers everything since the last message that was actually sent.
        preference.next_send_at = next_send_time(preference, now)
        log = EmailLog(
            user_id=user.id,
            status=EmailStatus.SKIPPED,
            subject=subject,
            error_message="Nothing new to report.",
        )
        session.add(log)
        session.commit()
        return log

    try:
        mailer.send_html(user.email, subject, body, config=config, inline_images=inline_images())
    except mailer.MailError as exc:
        log = EmailLog(
            user_id=user.id,
            status=EmailStatus.FAILED,
            subject=subject,
            new_item_count=new_count,
            price_drop_count=drop_count,
            error_message=str(exc),
            # Kept even though it never left: "what would have been sent" is
            # most of what you want when working out why it was not.
            body_html=body,
            body_text=mailer.html_to_text(body),
        )
        session.add(log)
        # Retry on the normal cadence rather than hammering a broken SMTP host.
        preference.next_send_at = next_send_time(preference, now)
        session.commit()
        return log

    preference.last_sent_at = now
    preference.last_digest_cutoff = cutoff
    preference.next_send_at = next_send_time(preference, now)
    log = EmailLog(
        user_id=user.id,
        status=EmailStatus.SENT,
        subject=subject,
        new_item_count=new_count,
        price_drop_count=drop_count,
        body_html=body,
        # The same conversion the mailer used for the plain-text alternative,
        # so what is stored is what was sent rather than a second rendering
        # that might drift from it.
        body_text=mailer.html_to_text(body),
    )
    session.add(log)
    session.commit()
    return log


def due_user_ids(session: Session) -> list[int]:
    """Active users with digests enabled whose next send time has arrived."""
    now = utcnow()
    rows = session.execute(
        select(User.id, EmailPreference.next_send_at)
        .join(EmailPreference, EmailPreference.user_id == User.id)
        .where(
            User.is_active.is_(True),
            EmailPreference.enabled.is_(True),
        )
    ).all()
    due: list[int] = []
    for user_id, next_send in rows:
        aware = _as_utc(next_send)
        if aware is None or aware <= now:
            due.append(user_id)
    return due
