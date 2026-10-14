"""What a variant costs new today, from gun.deals.

Slice 4 of "New-gun prices, and the makers' own pages" (ROADMAP.md). gun.deals
lists every store's price for a product on the page its UPC search lands on
-- the price, the store, whether it is in stock -- and that is all this reads:
**the lowest in-stock price and how many stores have it**, a fact about the
market, kept with a link to the page it came from, shown as the source. None
of gun.deals' own content is copied. Their terms of use (read 2026-10-11)
claim copyright in the site's contents and say nothing of automated reading;
robots.txt allows the search pages and turns away only ``/api``, ``/ajax`` and
the store redirects, none of which is asked.

**Only by an identifier that cannot be the wrong gun.** A variant's UPC; or,
lacking one, its maker's part number where a product on gun.deals carries
exactly that part number -- in a list of results, or on the product's own
page when the search goes straight there. A name search is never used -- one search for
"Taurus Tracker 44 Magnum" returned five products, two of them blemished
seconds and one a police trade-in.

**At most daily, and only for what is for sale**: a variant is asked about
when a listing of its model is on a shelf here and its answer is a day old.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from ..models import ArmoryStatus, FirearmModel, Item, ModelVariant, utcnow
from ..scrapers.base import Disallowed, ScrapeContext, ScrapeError, text_of

BASE = "https://gun.deals/"
#: How old an answer may be before it is asked again.
MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class NewPrice:
    low: float | None
    stores: int
    url: str


def search_url(term: str) -> str:
    return urljoin(BASE, "search/apachesolr_search/" + quote(term.strip()))


def _part(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def offers(html: str, url: str, upc: str | None = None) -> NewPrice | None:
    """The in-stock offers on a product's price table, or None if it has none.

    A row out of stock carries ``is-oos`` and is left out; a row for another
    UPC, when one was asked for, too.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(".price-compare-table")
    if table is None:
        return None
    prices = []
    for row in table.select("tr[data-price]"):
        if "is-oos" in (row.get("class") or []):
            continue
        if upc and row.get("data-upc") and str(row.get("data-upc")) != upc:
            continue
        try:
            prices.append(float(str(row.get("data-price"))))
        except ValueError:
            continue
    return NewPrice(low=round(min(prices), 2) if prices else None, stores=len(prices), url=url)


def _upc_for_part(html: str, part: str) -> str | None:
    """The UPC of the one product on a search page whose part number is this."""
    wanted = _part(part)
    found = set()
    for tile in BeautifulSoup(html, "html.parser").select(".product-details-tile"):
        text = text_of(tile)
        mpn = re.search(r"MPN:\s*(\S+)", text)
        upc = re.search(r"UPC:\s*(\d{8,14})", text)
        if mpn and upc and _part(mpn.group(1)) == wanted:
            found.add(upc.group(1))
    return found.pop() if len(found) == 1 else None


_PRODUCT_TITLE = re.compile(r"^\s*(\S+)\s+-\s+.*\s(\d{8,14})\s*\|\s*gun\.deals\s*$", re.S)


def _product_upc(html: str, part: str) -> str | None:
    """The UPC of a product page that a part number's search landed on.

    A search for a part number gun.deals knows exactly ("2842475", a Walther
    PDP) answers with that product's own page, not a list of tiles, titled
    "2842475 - Walther PDP Full Size 9mm 723364216954 | gun.deals": the part,
    the name, the UPC. Only the title says so on every such page -- the
    ``mpn`` markup is missing from some, and a price row may carry a store's
    mistyped UPC. A title naming any other part is no answer.
    """
    title = BeautifulSoup(html, "html.parser").title
    found = _PRODUCT_TITLE.match(text_of(title) if title else "")
    if found is None or _part(found.group(1)) != _part(part):
        return None
    return found.group(2)


def lookup(ctx: ScrapeContext, variant: ModelVariant) -> NewPrice | None:
    """What gun.deals lists this variant at today, or None if it cannot tell."""
    upc = variant.upc
    if not upc and variant.maker_part:
        url = search_url(variant.maker_part)
        html = ctx.get_text(url)
        upc = _upc_for_part(html, variant.maker_part)
        if upc is None and (upc := _product_upc(html, variant.maker_part)):
            # Already the product's page: its table is the answer.
            return offers(html, url, upc)
    if not upc:
        return None
    url = search_url(upc)
    return offers(ctx.get_text(url), url, upc)


def due(session: Session, now: datetime) -> list[ModelVariant]:
    """Approved variants with an identifier, whose model has a listing for
    sale, and whose answer is missing or a day old."""
    for_sale = exists().where(
        Item.firearm_model_id == ModelVariant.model_id,
        Item.is_active.is_(True),
        Item.is_sold.is_(False),
    )
    return list(
        session.execute(
            select(ModelVariant)
            .join(FirearmModel, FirearmModel.id == ModelVariant.model_id)
            .where(
                ModelVariant.status == ArmoryStatus.APPROVED,
                ModelVariant.enabled.is_(True),
                FirearmModel.modern_production.is_(True),
                (ModelVariant.upc.is_not(None)) | (ModelVariant.maker_part.is_not(None)),
                (ModelVariant.new_price_checked_at.is_(None))
                | (ModelVariant.new_price_checked_at < now - MAX_AGE),
                for_sale,
            )
            .order_by(ModelVariant.new_price_checked_at.is_(None).desc(), ModelVariant.id)
        ).scalars()
    )


def run(
    session: Session,
    ctx: ScrapeContext,
    *,
    limit: int | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Ask about every variant that is due. Returns counts."""
    counts = {"asked": 0, "priced": 0, "none_in_stock": 0, "unknown": 0}
    ctx.keep_at_least(BASE, 4.0)
    now = utcnow()
    for variant in due(session, now)[: limit if limit is not None else None]:
        counts["asked"] += 1
        try:
            found = lookup(ctx, variant)
        except (Disallowed, ScrapeError) as exc:
            log(f"  {variant.label}: gun.deals did not answer ({exc}).")
            continue
        variant.new_price_checked_at = now
        if found is None:
            counts["unknown"] += 1
            variant.new_price, variant.new_stores = None, None
        else:
            variant.new_price, variant.new_stores = found.low, found.stores
            variant.new_price_url = found.url
            counts["priced" if found.low is not None else "none_in_stock"] += 1
            log(
                f"  {variant.label}: "
                + (
                    f"${found.low:,.2f} at {found.stores} store(s)"
                    if found.low
                    else "none in stock"
                )
            )
        session.commit()
    return counts
