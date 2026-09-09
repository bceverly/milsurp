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
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..models import (
    EmailLog,
    EmailPreference,
    EmailStatus,
    Item,
    SavedSearch,
    Site,
    User,
    as_utc,
    utcnow,
)
from . import mailer, search
from .image_store import ImageStore, ImageStoreError

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
    """What the digest HTML refers to by Content-ID, before any listings."""
    payload = _mark_bytes()
    return {MARK_CID: payload} if payload is not None else {}


#: How big a listing's photograph is in the message, in pixels.
#:
#: The cell is 72px, and this is twice that so it stays sharp on a phone. The
#: stored thumbnail is 640px, which is right for a web grid and far too heavy to
#: attach twenty of — those run 40-60KB each, so a digest would be over a
#: megabyte of pictures nobody asked to download on a mobile connection.
EMAIL_PHOTO_PX = 144

#: Never attach more than this, however many listings the digest covers.
#:
#: A digest is capped per site rather than overall, so a night when four
#: vendors all restock is a long message. The pictures stop; the listings do
#: not — a row without one still has its title, price and link.
MAX_EMAIL_PHOTOS = 24

#: And never more than this in total, as a second belt.
MAX_EMAIL_PHOTO_BYTES = 400 * 1024


def _photo_for(item: Item, store: ImageStore) -> bytes | None:
    """One listing's picture, sized for a message, or None.

    Read from the thumbnail already on disk and shrunk again rather than from
    the original: the original can be 2000px and several megabytes, and this
    runs while somebody is waiting for their email to send.
    """
    photo = next(
        (candidate for candidate in item.photos if candidate.thumb_filename or candidate.filename),
        None,
    )
    if photo is None:
        return None
    try:
        stored = photo.thumb_filename or photo.filename
        if not stored:
            return None
        with Image.open(store.absolute_path(stored)) as opened:
            # Rotated to how a phone actually took it, then flattened: a PNG
            # with transparency becomes black on a JPEG otherwise.
            upright = ImageOps.exif_transpose(opened) or opened
            small = upright.convert("RGB")
            small.thumbnail((EMAIL_PHOTO_PX, EMAIL_PHOTO_PX))
            buffer = BytesIO()
            small.save(buffer, format="JPEG", quality=78, optimize=True)
            payload: bytes = buffer.getvalue()
            return payload
    except (OSError, ValueError, ImageStoreError) as exc:
        # A missing or unreadable file costs this row its picture and nothing
        # else. A digest that fails to send because one photograph moved would
        # be a poor trade.
        log.info("No email photo for item %s: %s", item.id, exc)
        return None


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
                .order_by(Item.price_changed_at.desc().nulls_last())
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
#: How much of a title and a description an email row carries.
#:
#: A digest is read in a preview pane on a phone, and a vendor's title can run
#: to a hundred and forty characters of grading notes. Truncated on a word
#: boundary with an ellipsis, so a cut is visibly a cut.
TITLE_CHARS = 80
BLURB_CHARS = 160


def truncate(text: str | None, limit: int) -> str:
    """``text`` shortened to ``limit`` characters, cut at a word boundary.

    Returns "" for nothing, so a caller can treat it as a plain string. The
    ellipsis is a real "…" rather than three dots: it is one character of the
    budget instead of three, and it is what a reader expects to mean "there is
    more".
    """
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    cut = clean[:limit].rsplit(" ", 1)[0]
    # A single word longer than the whole budget has no boundary to cut on.
    return (cut or clean[:limit]).rstrip(" ,;:.-") + "…"


def collect_saved_searches(
    session: Session, user: User
) -> list[tuple[SavedSearch, list[Item], int]]:
    """Each of the user's mailing saved searches, its rows, and its true total.

    **The whole result set, capped** -- not "what is new since last time". A
    saved search is a standing question and its answer is the listings that
    match it today; the two sections above this one are about change, and this
    one deliberately is not.

    The cap is per search and set by its owner. The total is carried alongside
    so the email can say what it left out rather than quietly showing ten of
    four hundred.

    A search whose stored query has rotted is skipped rather than raised: one
    bad row must not cost the user their whole digest. It is validated when
    saved, so this should not happen -- but "should not" is not "cannot", and
    the failure mode of a nightly job is the one worth choosing deliberately.
    """
    rows = (
        session.execute(
            select(SavedSearch)
            .where(SavedSearch.user_id == user.id, SavedSearch.email_enabled.is_(True))
            .order_by(func.lower(SavedSearch.name))
        )
        .scalars()
        .all()
    )
    found = [collect_one_saved_search(session, row) for row in rows]
    return [one for one in found if one is not None]


def collect_one_saved_search(
    session: Session, row: SavedSearch
) -> tuple[SavedSearch, list[Item], int] | None:
    """One saved search's rows and its true total, or ``None``.

    ``None`` for a search that matches nothing, and for one whose stored query
    will not parse. The second is why this returns rather than raises: a
    nightly job runs every search a user has, and one bad row must not cost
    them the whole digest.
    """
    try:
        query = search.parse_query(row.query)
    except search.BadQuery:
        log.warning("Saved search %s has an unreadable query; skipping it.", row.id)
        return None
    items = search.run(session, query, limit=max(1, row.email_item_limit))
    if not items:
        return None
    total = int(
        session.execute(
            search.apply_filters(select(func.count(Item.id)), **query.filters)
        ).scalar_one()
    )
    return row, items, total


def _e(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _item_row(item: Item, zone, show_drop: bool, photo_cid: str | None = None) -> str:
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

    # The picture is its own cell rather than a float: floats are not reliable
    # in mail clients, and a table cell is. Fixed width so a row without a
    # photograph still lines up with the rows that have one.
    picture = (
        f"""
        <td width="84" valign="top"
            style="padding:14px 12px 14px 0;border-bottom:1px solid #E3E8F0;">
          <a href="{_e(item.url)}" style="text-decoration:none;">
            <img src="cid:{photo_cid}" width="72" height="72" alt=""
                 style="display:block;width:72px;height:72px;object-fit:cover;
                        border-radius:6px;border:1px solid #E3E8F0;" />
          </a>
        </td>"""
        if photo_cid
        else ""
    )

    return f"""
      <tr>{picture}
        <td valign="top" style="padding:14px 0;border-bottom:1px solid #E3E8F0;">
          <a href="{_e(item.url)}" style="color:{NAVY};font-weight:600;font-size:15px;
             text-decoration:none;line-height:1.35;">{_e(item.title)}</a>
          <div style="color:{MUTED};font-size:12px;margin:5px 0 8px;">{facts or '&nbsp;'}</div>
          {price_block}
          <div style="color:{MUTED};font-size:11px;margin-top:6px;">{seen}</div>
        </td>
      </tr>"""


def _saved_row(item: Item, base_url: str, site_name: str, photo_cid: str | None) -> str:
    """One listing in a saved-search section.

    **Linked to our own item page, not to the vendor.** That is what was asked
    for and it is the better link anyway: the item page carries the price
    history, every photograph, and a "View on vendor site" button — so the
    vendor is one more click away rather than unreachable, and the reader keeps
    the context the email is summarizing.
    """
    price = _money(item.current_price, item.currency)
    blurb = truncate(item.description, BLURB_CHARS)
    facts = " · ".join(_e(value) for value in (site_name, item.caliber, item.country) if value)
    here = f"{base_url}/items/{item.id}"

    picture = (
        f"""
        <td width="84" valign="top"
            style="padding:14px 12px 14px 0;border-bottom:1px solid #E3E8F0;">
          <a href="{_e(here)}" style="text-decoration:none;">
            <img src="cid:{photo_cid}" width="72" height="72" alt=""
                 style="display:block;width:72px;height:72px;object-fit:cover;
                        border-radius:6px;border:1px solid #E3E8F0;" />
          </a>
        </td>"""
        if photo_cid
        else ""
    )
    description = (
        f'<div style="color:{INK};font-size:13px;line-height:1.45;margin:6px 0 8px;">'
        f"{_e(blurb)}</div>"
        if blurb
        else ""
    )

    return f"""
      <tr>{picture}
        <td valign="top" style="padding:14px 0;border-bottom:1px solid #E3E8F0;">
          <a href="{_e(here)}" style="color:{NAVY};font-weight:600;font-size:15px;
             text-decoration:none;line-height:1.35;">{_e(truncate(item.title, TITLE_CHARS))}</a>
          <div style="color:{MUTED};font-size:12px;margin:5px 0 0;">{facts or '&nbsp;'}</div>
          {description}
          <span style="color:{NAVY};font-weight:700;font-size:16px;">{price}</span>
        </td>
      </tr>"""


def _site_name(sites: dict[int, Site], item: Item) -> str:
    site = sites.get(item.site_id)
    return site.name if site is not None else ""


def _saved_sections(
    searches: list[tuple[SavedSearch, list[Item], int]],
    sites: dict[int, Site],
    base_url: str,
    photos: dict[int, str] | None = None,
) -> str:
    """One block per saved search, in the order that search was saved with.

    The order is the point: ``search.run`` applies the saved sort, and the rows
    are rendered in the order it returned them. An email assembled by grouping
    or re-filtering would come out in whatever order the second query chose,
    which is not the order the reader asked for.
    """
    if not searches:
        return ""
    blocks = []
    for row, items, total in searches:
        rows = "".join(
            _saved_row(item, base_url, _site_name(sites, item), (photos or {}).get(item.id))
            for item in items
        )
        # Say what was left out rather than quietly showing ten of four
        # hundred, and make "the rest" one click.
        more = (
            f"""
          <div style="margin-top:10px;font-size:12px;">
            <a href="{_e(f'{base_url}/?{row.query}')}" style="color:{BLUE};">
              Showing {len(items)} of {total} matches — see them all
            </a>
          </div>"""
            if total > len(items)
            else f"""
          <div style="margin-top:10px;font-size:12px;">
            <a href="{_e(f'{base_url}/?{row.query}')}" style="color:{BLUE};">Open this search</a>
          </div>"""
        )
        blocks.append(f"""
        <tr><td style="padding:18px 24px 0;">
          <div style="font-size:12px;font-weight:700;letter-spacing:.10em;
               text-transform:uppercase;color:{BLUE};">{_e(row.name)}</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="border-collapse:collapse;">{rows}</table>{more}
        </td></tr>""")
    return f"""
      <tr><td style="padding:26px 24px 0;">
        <h2 style="margin:0;font-size:17px;color:{INK};font-weight:700;
            border-left:4px solid {BLUE};padding-left:10px;">Your saved searches</h2>
      </td></tr>{''.join(blocks)}"""


def _section(
    heading: str,
    grouped: dict[int, list[Item]],
    sites: dict[int, Site],
    zone,
    show_drop: bool,
    photos: dict[int, str] | None = None,
) -> str:
    if not grouped:
        return ""
    blocks = []
    for site_id, items in grouped.items():
        site = sites.get(site_id)
        site_name = _e(site.name if site else "Unknown site")
        rows = "".join(
            _item_row(item, zone, show_drop, (photos or {}).get(item.id)) for item in items
        )
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
    saved: list[tuple[SavedSearch, list[Item], int]] | None = None,
) -> tuple[str, str, dict[str, bytes]]:
    """Return ``(subject, html_body, inline_images)``.

    The pictures travel with the message rather than being linked: mail clients
    block remote images by default, so a linked thumbnail is an empty box for
    most readers on first open.
    """
    # None means the user never chose one; the email has no browser to ask,
    # so UTC is the only honest fallback.
    preference = user.email_preference
    zone = _tz((preference.display_timezone if preference else None) or "UTC")
    base_url = config.server.public_url
    new_count = sum(len(v) for v in new_items.values())
    drop_count = sum(len(v) for v in price_drops.values())

    saved = saved or []
    saved_count = sum(len(items) for _row, items, _total in saved)

    parts = []
    if new_count:
        parts.append(f"{new_count} new listing{'s' if new_count != 1 else ''}")
    if drop_count:
        parts.append(f"{drop_count} price drop{'s' if drop_count != 1 else ''}")
    if saved_count:
        # Named rather than counted where there is one: "Mosins under $400" is
        # a better subject line than "12 saved-search matches".
        parts.append(f"{saved[0][0].name}" if len(saved) == 1 else f"{len(saved)} saved searches")
    subject = f"{BRAND}: {' and '.join(parts)}" if parts else f"{BRAND}: nothing new"

    # One picture per listing, attached and referenced by Content-ID, until the
    # budget runs out. A digest covering four vendors restocking at once is a
    # long message, and nobody wants a megabyte of photographs arriving on a
    # phone — so the pictures stop and the listings carry on without them.
    images = inline_images()
    photo_cids: dict[int, str] = {}
    store = ImageStore(config)
    budget = MAX_EMAIL_PHOTO_BYTES
    saved_groups = [{0: items} for _row, items, _total in saved]
    for group in (new_items, price_drops, *saved_groups):
        for items in group.values():
            for item in items:
                if len(photo_cids) >= MAX_EMAIL_PHOTOS or budget <= 0:
                    break
                payload = _photo_for(item, store)
                if payload is None or len(payload) > budget:
                    continue
                cid = f"item-{item.id}"
                images[cid] = payload
                photo_cids[item.id] = cid
                budget -= len(payload)

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

  {_section('New listings', new_items, sites, zone, False, photo_cids)}
  {_section('Price reductions', price_drops, sites, zone, True, photo_cids)}
  {_saved_sections(saved, sites, base_url, photo_cids)}

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
    return subject, body, images


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def next_send_time(preference: EmailPreference, from_time: datetime | None = None) -> datetime:
    base = from_time or utcnow()
    return base + timedelta(hours=max(1, preference.frequency_hours))


def build_digest(
    session: Session, user: User, config: Config | None = None
) -> tuple[str, str, dict[str, bytes], int, int, datetime] | None:
    """Assemble one user's digest.

    Returns ``(subject, html, inline_images, new_count, drop_count, cutoff)``,
    or ``None`` when the user has nothing selected at all.
    """
    config = config or get_config()
    preference = user.email_preference
    if preference is None:
        return None

    # Saved searches are the user's own and are not scoped by the site
    # selection: a search that names its sites already says so in its query,
    # and one that does not is asking about the whole catalog on purpose.
    saved = collect_saved_searches(session, user)

    site_ids = selected_site_ids(session, preference)
    # No sites chosen means no new-listing or price-drop sections. It used to
    # mean no digest at all, and that is still right when there is nothing else
    # to send -- but a saved search is a reason to send one.
    if not site_ids and not saved:
        return None

    # First run has no watermark: look back one interval rather than emailing
    # the entire back catalog.
    since = _as_utc(preference.last_digest_cutoff) or (
        utcnow() - timedelta(hours=max(1, preference.frequency_hours))
    )
    cutoff = utcnow()

    new_items = collect_new_items(session, preference, site_ids, since)
    price_drops = collect_price_drops(session, preference, site_ids, since)

    # Every site a row in this email mentions, not only the selected ones: a
    # saved search can match a vendor the digest's site filter leaves out, and
    # its rows still have to say where they came from.
    wanted = set(site_ids) | {item.site_id for _row, items, _total in saved for item in items}
    sites = {
        site.id: site
        for site in session.execute(select(Site).where(Site.id.in_(wanted))).scalars().all()
    }
    subject, body, images = render_digest(user, new_items, price_drops, sites, since, config, saved)
    new_count = sum(len(v) for v in new_items.values())
    drop_count = sum(len(v) for v in price_drops.values())
    return subject, body, images, new_count, drop_count, cutoff


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

    subject, body, images, new_count, drop_count, cutoff = built

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
        mailer.send_html(user.email, subject, body, config=config, inline_images=images)
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


def send_saved_search(
    session: Session, user: User, row: SavedSearch, config: Config | None = None
) -> EmailLog:
    """Mail one saved search's results now, on demand.

    **Out of band, and deliberately so.** This touches neither
    ``next_send_at`` nor ``last_digest_cutoff``: pressing "Send now" on one
    search is not the daily digest arriving early, and it must not move the
    watermark that decides what counts as new in the next real one.

    It ignores ``email_enabled`` too. That flag answers "send this every day";
    the button answers "send this to me now", and they are different questions
    -- being able to see what a search would mail before turning the daily one
    on is most of the point.

    A search matching nothing sends nothing. An empty email is worse than a
    line of text on the screen the button is on, and the caller reports it.
    """
    config = config or get_config()
    now = utcnow()
    collected = collect_one_saved_search(session, row)

    if collected is None:
        entry = EmailLog(
            user_id=user.id,
            status=EmailStatus.SKIPPED,
            subject=f"{BRAND}: {row.name}",
            error_message=f"{row.name!r} matches nothing right now.",
        )
        session.add(entry)
        session.commit()
        return entry

    _row, items, _total = collected
    sites = {
        site.id: site
        for site in session.execute(
            select(Site).where(Site.id.in_({item.site_id for item in items}))
        )
        .scalars()
        .all()
    }
    subject, body, images = render_digest(user, {}, {}, sites, now, config, [collected])

    try:
        mailer.send_html(user.email, subject, body, config=config, inline_images=images)
    except mailer.MailError as exc:
        entry = EmailLog(
            user_id=user.id,
            status=EmailStatus.FAILED,
            subject=subject,
            error_message=str(exc),
            body_html=body,
            body_text=mailer.html_to_text(body),
        )
        session.add(entry)
        session.commit()
        return entry

    row.last_emailed_at = now
    entry = EmailLog(
        user_id=user.id,
        status=EmailStatus.SENT,
        subject=subject,
        # Neither a new listing nor a price drop: those two counts are what the
        # digest history reports per section, and this message has no such
        # section. Left at zero rather than borrowed.
        body_html=body,
        body_text=mailer.html_to_text(body),
    )
    session.add(entry)
    session.commit()
    return entry


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
