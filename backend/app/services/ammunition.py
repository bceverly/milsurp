"""What it costs to shoot a caliber, and whether it can be reloaded.

"Ammunition" in ROADMAP.md, asked for on 2026-10-11: "understanding what it
costs to shoot a gun is probably more important to the economics than the
purchase price in most cases." For each caliber in the armory:

* **Bullet diameter and bullet weights**, from the cartridge's Wikipedia
  article (``Caliber.wikipedia_url``, proposed and accepted through
  app.services.wikipedia) -- the infobox's ``bullet`` and its ``bw1`` ...
  ``bwN``. Read once, and again whenever the caliber is edited, never on a
  clock: a cartridge's diameter does not change.
* **Factory cost per round**: for each of the caliber's weights, the cheapest
  in-stock box on AmmoSeek within 3% of that weight, divided by the rounds in
  it; the caliber's figure is the average of those. Box price over rounds,
  nothing else -- no shipping, hazmat or tax. Where AmmoSeek lists nothing,
  **Milsurp Munitions**, which loads the obsolete military cartridges nobody
  else does: its cheapest in-stock box.
* **Lee dies**: whether Lee Precision's rifle or handgun die catalog has a
  set for it, with the link.
* **Projectile cost**: AmmoSeek's reloading bullets at the caliber's diameter,
  averaged across its weights as the factory figure is.

**AmmoSeek's terms forbid automated collection without consent.** Reading it
anyway was decided on 2026-10-11, for a rough cost of shooting rather than
AmmoSeek's listings, so it is read lightly: each refresh asks only about
calibers with a listing for sale here, on the schedule an administrator sets
(daily, weekly or every two weeks; weekly by default), through
``ScrapeContext`` and so under robots.txt, the request delay and the cooldown
register -- a block or a challenge stops it rather than being worked around.
Only the derived figures are kept, each with a link back to the page.

Measured 2026-10-11: an AmmoSeek caliber page (``/ammo/7.62x54r``) carries its
query (``gun=rifle&cal=277&seo_name=7.62x54r``) and fills its table from one
POST to ``/`` returning JSON, cheapest per round first; reloading bullets are
the same POST with ``search_reloading=1&reloading_type=bullets`` and a bullet
caliber from the bullets form, which names them by diameter (``.311" diam.``).
"""

from __future__ import annotations

import html as htmlib
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urljoin

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AmmoSetting, ArmoryStatus, Caliber, CaliberBulletWeight, Item, as_utc, utcnow
from ..scrapers.base import Disallowed, ScrapeContext, ScrapeError, text_of
from . import armory, wikipedia

AMMOSEEK = "https://ammoseek.com/"
MILSURP_MUNITIONS = "https://milsurpmunitions.com/"
LEE = "https://leeprecision.com/"
LEE_DIE_CATEGORIES = ("reloading-dies-rifle-dies", "reloading-dies-hand-gun-dies")

#: The refresh frequencies an administrator chooses between, in days.
FREQUENCIES = {1: "Daily", 7: "Weekly", 14: "Every 2 weeks"}
DEFAULT_DAYS = 7

GRAINS_PER_GRAM = 15.4323584
MM_PER_INCH = 25.4
#: How close an offer's bullet must be to a weight to count as that weight:
#: AmmoSeek's 148 gr and 150 gr are the same choice, 174 gr and 180 gr are not.
SAME_WEIGHT = 0.03
#: How close a bullet caliber's diameter must be to the cartridge's: .311" for
#: a 7.62x54R stated as 7.92 mm (.3118").
SAME_DIAMETER = 0.0015
#: Offers asked for per query. Sorted cheapest per round first, so the first
#: hundred hold every weight's low that matters.
OFFERS = 100


# -- Wikipedia --------------------------------------------------------------
@dataclass(frozen=True)
class ArticleFacts:
    diameter_in: float | None
    grains: list[float]


def _infobox(wikitext: str) -> str | None:
    """The body of the cartridge infobox, balanced braces and all."""
    start = re.search(r"\{\{\s*Infobox (?:firearm )?cartridge", wikitext, re.I)
    if not start:
        return None
    depth = 0
    at = start.start()
    while at < len(wikitext) - 1:
        pair = wikitext[at : at + 2]
        if pair == "{{":
            depth += 1
            at += 2
            continue
        if pair == "}}":
            depth -= 1
            at += 2
            if depth == 0:
                return wikitext[start.end() : at - 2]
            continue
        at += 1
    return None


def _params(box: str) -> dict[str, str]:
    """An infobox's ``|name=value`` parameters, split at the top level only."""
    found: dict[str, str] = {}
    depth = 0
    piece = ""
    pieces = []
    for at, char in enumerate(box):
        two = box[at : at + 2]
        if two in ("{{", "[["):
            depth += 1
        elif two in ("}}", "]]"):
            depth -= 1
        if char == "|" and depth == 0:
            pieces.append(piece)
            piece = ""
        else:
            piece += char
    pieces.append(piece)
    for part in pieces:
        name, sep, value = part.partition("=")
        if sep:
            found[name.strip().lower()] = re.sub(
                r"<!--.*?-->|<ref.*?(?:/>|</ref>)", "", value, flags=re.S
            ).strip()
    return found


def _number(text: str | None) -> float | None:
    found = re.search(r"\d+(?:\.\d+)?|\.\d+", (text or "").replace(",", ""))
    return float(found.group(0)) if found else None


def article_facts(wikitext: str) -> ArticleFacts:
    """The bullet's diameter in inches and its weights in grains, from a
    cartridge article's infobox. Each is empty when the article does not say."""
    box = _infobox(wikitext)
    if box is None:
        return ArticleFacts(None, [])
    params = _params(box)
    diameter = None
    stated = params.get("bullet")
    number = _number(stated)
    if number:
        metric = (
            params.get("is_si_specs", "").lower().startswith("y")
            or "mm" in (stated or "").lower()
            or number > 1.5
        )
        diameter = round(number / MM_PER_INCH, 4) if metric else number
    grams = "gram" in params.get("bwunit", "").lower() or (
        params.get("is_si_ballistics", "").lower().startswith("y")
        and "grain" not in params.get("bwunit", "").lower()
    )
    weights: list[float] = []
    for key in sorted((k for k in params if re.fullmatch(r"bw\d+", k)), key=lambda k: int(k[2:])):
        value = _number(params[key])
        if not value:
            continue
        grains = float(round(value * GRAINS_PER_GRAM if grams else value))
        if grains not in weights:
            weights.append(grains)
    return ArticleFacts(diameter, sorted(weights))


def read_article(fetch: wikipedia.Fetch, url: str) -> str:
    """An article's wikitext, by its address."""
    title = url.rsplit("/wiki/", 1)[-1].replace("_", " ")
    answer = fetch(
        {
            "action": "parse",
            "page": unquote(title),
            "prop": "wikitext",
            "redirects": "1",
            "formatversion": "2",
        }
    )
    return str((answer.get("parse") or {}).get("wikitext") or "")


def set_weights(caliber: Caliber, grains: Iterable[float], source: str = "wikipedia") -> None:
    """Replace the caliber's weights from one source; typed ones are kept."""
    wanted = {float(g) for g in grains}
    for weight in list(caliber.bullet_weights):
        if weight.source == source and weight.grains not in wanted:
            caliber.bullet_weights.remove(weight)
    have = {weight.grains for weight in caliber.bullet_weights}
    for grains_value in sorted(wanted - have):
        caliber.bullet_weights.append(CaliberBulletWeight(grains=grains_value, source=source))


def refresh_articles(
    session: Session,
    fetch: wikipedia.Fetch,
    *,
    limit: int | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Read the facts of every caliber whose article has not been read since
    it was linked or edited. Returns how many were read."""
    due = list(
        session.execute(
            select(Caliber)
            .where(Caliber.wikipedia_url.is_not(None), Caliber.wikipedia_read_at.is_(None))
            .order_by(Caliber.id)
        ).scalars()
    )[:limit]
    for caliber in due:
        try:
            facts = article_facts(read_article(fetch, caliber.wikipedia_url or ""))
        except Exception as exc:  # a bad page must not stop the rest
            log(f"  {caliber.name}: Wikipedia did not answer ({exc}).")
            continue
        if facts.diameter_in:
            caliber.bullet_diameter_in = facts.diameter_in
        if facts.grains:
            set_weights(caliber, facts.grains)
        caliber.wikipedia_read_at = utcnow()
        session.commit()
        log(
            f"  {caliber.name}: diameter {facts.diameter_in or 'not stated'}, "
            f"weights {', '.join(f'{g:g}' for g in facts.grains) or 'none stated'}"
        )
    return len(due)


# -- Offers, from either source ---------------------------------------------
@dataclass(frozen=True)
class Offer:
    grains: float | None
    price: float
    rounds: int

    @property
    def each(self) -> float:
        return self.price / self.rounds


def _price(text: Any) -> float | None:
    found = re.search(r"[\d,]+(?:\.\d+)?", str(text or ""))
    try:
        return float(found.group(0).replace(",", "")) if found else None
    except ValueError:
        return None


def ammoseek_offers(payload: dict[str, Any]) -> list[Offer]:
    """The offers in an AmmoSeek results answer."""
    found = []
    for row in payload.get("data") or []:
        price = _price(row.get("price"))
        try:
            rounds = int(row.get("count") or 0)
        except (TypeError, ValueError):
            rounds = 0
        grains = _number(str(row.get("grains") or ""))
        if price and rounds > 0:
            found.append(Offer(grains, price, rounds))
    return found


def lows(offers: Iterable[Offer], weights: Iterable[float]) -> dict[float, float]:
    """Each weight's cheapest offer per round, for the weights any offer has.

    With no weights to go by, the weight offered most often stands in: one
    junk listing at a wrong weight is not the caliber's usual load.
    """
    offers = [o for o in offers if o.grains]
    weights = list(weights)
    if not weights:
        counted: dict[float, int] = {}
        for offer in offers:
            counted[offer.grains or 0] = counted.get(offer.grains or 0, 0) + 1
        if not counted:
            return {}
        weights = [max(counted, key=lambda grains: (counted[grains], -grains))]
    found = {}
    for weight in weights:
        near = [o.each for o in offers if abs((o.grains or 0) - weight) <= weight * SAME_WEIGHT]
        if near:
            found[weight] = round(min(near), 4)
    return found


# -- AmmoSeek ---------------------------------------------------------------
def ammoseek_calibers(html: str) -> list[tuple[str, list[str]]]:
    """Every caliber on AmmoSeek's caliber list: its page and its names.

    "7.7 Japanese (7.7x58mm, 7.7 Arisaka, 7.7x58 Arisaka)" is four names.
    """
    found = []
    for link in BeautifulSoup(html, "html.parser").select('a[href^="/ammo/"]'):
        label = text_of(link)
        head, _sep, rest = label.partition("(")
        names = [head.strip(), *(n.strip() for n in rest.rstrip(") ").split(",") if n.strip())]
        found.append((str(link.get("href")), [n for n in names if n]))
    return found


def ammoseek_pages(session: Session, html: str) -> dict[str, str]:
    """The armory caliber each AmmoSeek page is for, by caliber name."""
    found: dict[str, str] = {}
    for path, names in ammoseek_calibers(html):
        for name in names:
            mine = armory.canonical_caliber(session, name)
            if mine and mine not in found:
                found[mine] = path
                break
    return found


def query_of(html: str) -> str | None:
    """The query an AmmoSeek results page sends for its own table."""
    found = re.search(r'data-qstring="([^"]*)"', html)
    return htmlib.unescape(found.group(1)).lstrip("&") if found else None


def _ask_ammoseek(ctx: ScrapeContext, fields: dict[str, str], referer: str) -> dict[str, Any]:
    data = {"draw": "1", "start": "0", "length": str(OFFERS), **fields}
    response = ctx.post(
        AMMOSEEK,
        data=data,
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": referer},
    )
    try:
        return dict(response.json())
    except (ValueError, json.JSONDecodeError) as exc:
        raise ScrapeError(f"AmmoSeek answered with something other than JSON ({exc})") from exc


def bullet_calibers(html: str) -> list[tuple[str, float]]:
    """AmmoSeek's bullet calibers, ``(id, diameter in inches)``, from its
    bullets search form: '.311" diam.' is 0.311."""
    found = []
    select_ = BeautifulSoup(html, "html.parser").select_one("#bulletsCaliberSelect")
    for option in select_.select("option") if select_ else []:
        diameter = re.match(r"\s*(\.\d+)\"?\s*diam", text_of(option))
        if diameter and option.get("value"):
            found.append((str(option.get("value")), float(diameter.group(1))))
    return found


def nearest_bullet(options: list[tuple[str, float]], diameter: float) -> str | None:
    best = min(options, key=lambda option: abs(option[1] - diameter), default=None)
    return best[0] if best and abs(best[1] - diameter) <= SAME_DIAMETER else None


# -- Milsurp Munitions -------------------------------------------------------
def milsurp_offers(products: list[dict[str, Any]]) -> list[tuple[str, Offer]]:
    """In-stock loads from Milsurp Munitions' Store API: ``(name, offer)``.

    The bullet weight is in the name ("8x50R Mannlicher (205gr SP)") and the
    rounds in a box in the description ("20 rounds"); a product stating
    neither count is passed over rather than guessed.
    """
    found = []
    for product in products:
        if not product.get("is_in_stock"):
            continue
        name = htmlib.unescape(str(product.get("name") or ""))
        words = htmlib.unescape(
            re.sub(
                r"<[^>]+>",
                " ",
                f"{product.get('short_description') or ''} {product.get('description') or ''}",
            )
        )
        rounds = re.search(r"(\d+)\s*(?:rounds?|rds?\b|ct\b|count\b|per box)", words, re.I)
        prices = product.get("prices") or {}
        try:
            price = int(prices.get("price") or 0) / 10 ** int(
                prices.get("currency_minor_unit") or 2
            )
        except (TypeError, ValueError):
            continue
        grains = re.search(r"(\d+)\s*gr", name, re.I)
        if rounds and int(rounds.group(1)) > 0 and price > 0:
            found.append(
                (
                    name,
                    Offer(float(grains.group(1)) if grains else None, price, int(rounds.group(1))),
                )
            )
    return found


# -- Lee Precision -----------------------------------------------------------
def lee_dies(html: str) -> list[tuple[str, str]]:
    """The die sets on one page of Lee's catalog: ``(cartridge, page)``."""
    found = []
    for link in BeautifulSoup(html, "html.parser").select(".product-title a"):
        name = re.sub(r"\s+dies?\s*$", "", text_of(link), flags=re.I).strip()
        if name:
            found.append((name, urljoin(LEE, str(link.get("href")))))
    return found


def lee_catalog(ctx: ScrapeContext) -> list[tuple[str, str]]:
    """Every die set Lee lists, from its rifle and handgun die categories."""
    found: list[tuple[str, str]] = []
    for category in LEE_DIE_CATEGORIES:
        for page in range(1, 20):
            sets = lee_dies(ctx.get_text(urljoin(LEE, f"{category}?pagesize=48&pagenumber={page}")))
            fresh = [entry for entry in sets if entry not in found]
            if not fresh:
                break
            found.extend(fresh)
    return found


# -- The refresh ---------------------------------------------------------------
def settings(session: Session) -> AmmoSetting:
    row = session.get(AmmoSetting, 1)
    if row is None:
        row = AmmoSetting(id=1, refresh_days=DEFAULT_DAYS)
        session.add(row)
        session.commit()
    return row


def is_due(session: Session, now: datetime | None = None) -> bool:
    row = settings(session)
    if row.requested_at is not None:
        return True
    last = as_utc(row.last_run_at)
    return last is None or (now or utcnow()) - last >= timedelta(days=row.refresh_days or 7)


def for_sale(session: Session) -> list[Caliber]:
    """Approved calibers with a listing for sale here, which is what is asked about."""
    names = set(
        session.execute(
            select(Item.caliber).where(
                Item.is_active.is_(True), Item.is_sold.is_(False), Item.caliber.is_not(None)
            )
        ).scalars()
    )
    return [
        caliber
        for caliber in session.execute(
            select(Caliber)
            .where(Caliber.status == ArmoryStatus.APPROVED, Caliber.enabled.is_(True))
            .order_by(Caliber.name)
        ).scalars()
        if caliber.name in names
    ]


def _record(caliber: Caliber, found: dict[float, float], field: str) -> None:
    by_weight = {weight.grains: weight for weight in caliber.bullet_weights}
    for weight in caliber.bullet_weights:
        setattr(weight, field, None)
    for grains, each in found.items():
        if grains in by_weight:
            setattr(by_weight[grains], field, each)


def _from_ammoseek(
    ctx: ScrapeContext, caliber: Caliber, path: str | None, weights: list[float]
) -> dict[float, float]:
    """Each weight's cheapest round on AmmoSeek, finding its query the first
    time and keeping it."""
    if not path:
        return {}
    page = urljoin(AMMOSEEK, path.lstrip("/"))
    if not caliber.ammoseek_query:
        caliber.ammoseek_query = query_of(ctx.get_text(page))
    if not caliber.ammoseek_query:
        return {}
    fields = dict(parse_qsl(caliber.ammoseek_query, keep_blank_values=True))
    fields["search_ammo"] = "1"
    found = lows(ammoseek_offers(_ask_ammoseek(ctx, fields, page)), weights)
    if found:
        caliber.factory_source, caliber.factory_url = "ammoseek", page
    return found


def _factory(
    session: Session,
    ctx: ScrapeContext,
    caliber: Caliber,
    pages: dict[str, str],
    milsurp: list[tuple[str, Offer]],
    now: datetime,
) -> str | None:
    """Price one caliber's factory ammunition. Returns where it came from."""
    weights = [weight.grains for weight in caliber.bullet_weights]
    found: dict[float, float] = {}
    try:
        found = _from_ammoseek(ctx, caliber, pages.get(caliber.name), weights)
    except ScrapeError as exc:
        # One caliber AmmoSeek could not answer for still gets the fallback.
        # A Disallowed is not caught here: robots.txt saying no stops the run.
        if isinstance(exc, Disallowed):
            raise
    if not found:
        mine = [
            offer
            for name, offer in milsurp
            if armory.canonical_caliber(session, name) == caliber.name
        ]
        if mine:
            cheapest = min(mine, key=lambda offer: offer.each)
            found = {cheapest.grains or 0.0: round(cheapest.each, 4)}
            caliber.factory_source = "milsurp-munitions"
            caliber.factory_url = urljoin(MILSURP_MUNITIONS, "?s=" + quote(caliber.name))
    caliber.factory_checked_at = now
    if not found:
        caliber.factory_cpr = None
        caliber.factory_source = caliber.factory_url = None
        _record(caliber, {}, "factory_cpr")
        return None
    caliber.factory_cpr = round(mean(found.values()), 4)
    _record(caliber, found, "factory_cpr")
    return caliber.factory_source


def _projectiles(
    ctx: ScrapeContext, caliber: Caliber, options: list[tuple[str, float]], now: datetime
) -> bool:
    """Price one caliber's projectiles by its diameter. Whether any were found."""
    caliber.projectile_checked_at = now
    bullet = (
        nearest_bullet(options, caliber.bullet_diameter_in) if caliber.bullet_diameter_in else None
    )
    found: dict[float, float] = {}
    if bullet:
        payload = _ask_ammoseek(
            ctx,
            {"search_reloading": "1", "reloading_type": "bullets", "cal": bullet},
            AMMOSEEK,
        )
        found = lows(ammoseek_offers(payload), [w.grains for w in caliber.bullet_weights])
    caliber.projectile_cost = round(mean(found.values()), 4) if found else None
    caliber.projectile_url = AMMOSEEK if found else None
    _record(caliber, found, "projectile_cost")
    return bool(found)


def _refresh_lee(session: Session, ctx: ScrapeContext, now: datetime) -> str:
    """Mark every caliber with whether Lee lists dies for it. Returns a note."""
    try:
        catalog = lee_catalog(ctx)
    except (Disallowed, ScrapeError) as exc:
        return f"Lee not read ({exc})"
    dies: dict[str, str] = {}
    for name, url in catalog:
        mine = armory.canonical_caliber(session, name)
        if mine:
            dies.setdefault(mine, url)
    for caliber in session.execute(select(Caliber)).scalars():
        caliber.lee_dies = caliber.name in dies
        caliber.lee_url = dies.get(caliber.name)
        caliber.lee_checked_at = now
    session.commit()
    return f"Lee: {len(dies)} calibers with dies"


@dataclass
class Sources:
    """What one refresh read once and uses for every caliber."""

    pages: dict[str, str]
    options: list[tuple[str, float]]
    milsurp: list[tuple[str, Offer]]
    notes: list[str]


def _sources(session: Session, ctx: ScrapeContext) -> Sources:
    found = Sources({}, [], [], [])
    try:
        found.pages = ammoseek_pages(session, ctx.get_text(urljoin(AMMOSEEK, "calibers/")))
        found.options = bullet_calibers(
            ctx.get_text(urljoin(AMMOSEEK, "type1_genform.pl?f=bullets"))
        )
    except (Disallowed, ScrapeError) as exc:
        found.notes.append(f"AmmoSeek not read ({exc})")
    try:
        text = ctx.get_text(urljoin(MILSURP_MUNITIONS, "wp-json/wc/store/v1/products?per_page=100"))
        found.milsurp = milsurp_offers(json.loads(text))
    except (Disallowed, ScrapeError, ValueError) as exc:
        found.notes.append(f"Milsurp Munitions not read ({exc})")
    return found


def _price_calibers(
    session: Session,
    ctx: ScrapeContext,
    sources: Sources,
    now: datetime,
    log: Callable[[str], None],
) -> str:
    """Price every caliber for sale. Returns a summary."""
    priced = projectiles = 0
    asked = for_sale(session)
    for caliber in asked:
        try:
            if _factory(session, ctx, caliber, sources.pages, sources.milsurp, now):
                priced += 1
            if sources.options and _projectiles(ctx, caliber, sources.options, now):
                projectiles += 1
        except Disallowed as exc:
            # A robots.txt that changed its mind is an answer, not an error.
            sources.notes.append(f"stopped: {exc}")
            session.commit()
            break
        except ScrapeError as exc:
            log(f"  {caliber.name}: {exc}")
        session.commit()
        log(
            f"  {caliber.name}: factory {caliber.factory_cpr or '-'} "
            f"({caliber.factory_source or 'none'}), projectile {caliber.projectile_cost or '-'}"
        )
    head = (
        f"{len(asked)} calibers for sale: {priced} with factory prices, "
        f"{projectiles} with projectile prices"
    )
    return "; ".join([head, *sources.notes])


def refresh(
    session: Session,
    ctx: ScrapeContext,
    *,
    fetch: wikipedia.Fetch | None = None,
    log: Callable[[str], None] = print,
) -> str:
    """One full refresh. Returns its summary, also kept on the settings row.

    Wikipedia first (proposals for calibers without an article, and the facts
    of any not yet read), so the weights the prices are measured against are
    current; then Lee's catalog; then, per caliber for sale, the factory
    ammunition and the projectiles.
    """
    started = time.monotonic()
    row = settings(session)
    row.requested_at = None
    session.commit()
    now = utcnow()
    try:
        if fetch is not None:
            wikipedia.run(session, fetch, kinds=("caliber",), log=log)
            refresh_articles(session, fetch, log=log)
        ctx.keep_at_least(AMMOSEEK, 5.0)
        lee = _refresh_lee(session, ctx, now)
        sources = _sources(session, ctx)
        sources.notes.insert(0, lee)
        summary = _price_calibers(session, ctx, sources, now, log)
        status, error = "ok", None
    except Exception as exc:  # recorded where the Settings page shows it
        session.rollback()
        summary, status, error = f"Failed: {exc}", "failed", str(exc)[:500]
        log(summary)
    row = settings(session)
    row.last_status, row.last_error = status, error
    row.last_run_at = now
    row.last_summary = summary[:500]
    row.last_seconds = round(time.monotonic() - started, 1)
    session.commit()
    return summary


def facts(session: Session, name: str) -> Caliber | None:
    """The armory caliber a name means, for the Ammunition information panel."""
    canonical = armory.canonical_caliber(session, name) or name
    return session.execute(select(Caliber).where(Caliber.name == canonical)).scalars().first()
