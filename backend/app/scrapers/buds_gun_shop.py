"""Bud's Gun Shop (budsgunshop.com) -- the used section.

A Kentucky dealer and one of the largest online; added on 2026-10-27 for its
used guns, asked for to catch the used pocket pistols -- Raven MP-25s and the
like -- that only ever sell secondhand. Measured twice before (ROADMAP.md) and
refused both times for want of a police trade-in section, which is not what
this reads.

Laravel with htmx, rendering plain HTML: the used section
(``/categories/firearms/used``) is 24 guns a page, paged by ``?page=N``, about
160 on 2026-10-27, mostly pistols. Every card carries the shop's own product
id, title, section and price in cents as ``data-product-*`` attributes, which
is the whole listing but its description and pictures. The product page adds
the description -- where Bud's states the condition, "rated at 80-90%" --
the maker and its stock state, read once per listing.

robots.txt allows everything but the account, cart and ``/lazy-load`` paths.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Iterator

from bs4 import BeautifulSoup, Tag

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

SITE_BASE = "https://www.budsgunshop.com/"
USED = f"{SITE_BASE}categories/firearms/used"
#: A guard: the section was seven pages on 2026-10-27.
MAX_PAGES = 30
_IMAGE = "https://legacy-images.b-cdn.net/images/{id}_{n}.jpg"
_GALLERY = re.compile(r"https://legacy-images\.b-cdn\.net/images/(\d+)_(\d+)\.jpg")


def page_url(page: int) -> str:
    return USED if page == 1 else f"{USED}?page={page}"


def item_from_card(card: Tag) -> ScrapedItem | None:
    product_id = card.get("data-product-id")
    title = normalize_whitespace(html.unescape(str(card.get("data-product-name") or "")))
    if not isinstance(product_id, str) or not product_id or not title:
        return None
    link = card.select_one("a[href*='/products/']")
    href = link.get("href") if link is not None else None
    if not isinstance(href, str):
        return None
    try:
        price = int(str(card.get("data-product-price") or "0")) / 100 or None
    except ValueError:
        price = None
    section = str(card.get("data-product-category") or "Used Guns")
    return ScrapedItem(
        external_key=f"buds-{product_id}",
        url=href,
        title=title,
        price=price,
        category=f"Used {section}",
        is_new=False,
        is_sold="add to cart" not in card.get_text(" ", strip=True).lower(),
        image_urls=[_IMAGE.format(id=product_id, n=1)],
        images_are_complete=False,
    )


def cards_on(page: str) -> list[ScrapedItem]:
    """Every gun on one page of the section, once each."""
    soup = BeautifulSoup(page, "html.parser")
    found: dict[str, ScrapedItem] = {}
    for card in soup.select("div[data-product-id][data-product-name]"):
        item = item_from_card(card)
        if item is not None:
            found.setdefault(item.external_key, item)
    return list(found.values())


def detail_from(
    page: str, product_id: str
) -> tuple[str | None, str | None, bool | None, list[str]]:
    """A product page's description, maker, whether it is sold, and pictures."""
    soup = BeautifulSoup(page, "html.parser")
    description = None
    # The description's own block, heading and all -- not its parent, which
    # also holds the specifications and a Proposition 65 warning.
    block = soup.select_one(".syncle-product-description")
    if block is not None:
        text = normalize_whitespace(html.unescape(block.get_text(" ", strip=True)))
        description = re.sub(r"^Description\s+", "", text) or None
    brand = soup.find(id="syncle-product-brand")
    maker = normalize_whitespace(brand.get_text(strip=True)) if brand is not None else ""
    stock = soup.find(id="syncle-stock-status")
    sold = None
    if stock is not None:
        sold = stock.get_text(strip=True).lower().replace(" ", "") != "instock"
    numbers = sorted({int(n) for pid, n in _GALLERY.findall(page) if pid == product_id})
    photos = [_IMAGE.format(id=product_id, n=n) for n in numbers]
    return description, maker or None, sold, photos


class BudsGunShopScraper(SiteScraper):
    slug = "buds-gun-shop"
    name = "Bud's Gun Shop"
    base_url = SITE_BASE
    description = "Kentucky dealer's used guns, mostly pistols, each with its condition rating."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "used"
    #: The maker comes from the shop's own field.
    states_facts = True
    newsletter_url = SITE_BASE
    newsletter_note = '"Get Connected!" email signup in the footer of every page'
    shipping_long_gun = 0.0
    shipping_handgun = 0.0
    shipping_note = "Free shipping to the lower 48 states, stated on each product page"
    shipping_source = USED
    min_request_delay: float = 3.0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            try:
                found = cards_on(ctx.get_text(page_url(page)))
            except ScrapeError as exc:
                if page == 1:
                    raise
                ctx.warn(f"Could not read page {page}: {exc}. Stopping the section there.")
                return
            fresh = [item for item in found if item.external_key not in seen]
            if not fresh:
                break
            ctx.log(f"Used page {page}: {len(fresh)} listing(s).")
            for item in fresh:
                seen.add(item.external_key)
                yield self._detailed(ctx, item)

    def _detailed(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        if not ctx.needs_detail(item.external_key):
            return item
        try:
            page = ctx.get_text(item.url)
        except ScrapeError as exc:
            ctx.warn(f"Could not read {item.url}: {exc}; keeping the card only.")
            return item
        description, maker, sold, photos = detail_from(
            page, item.external_key.removeprefix("buds-")
        )
        item.description = description or item.description
        item.manufacturer = maker or item.manufacturer
        if sold is not None:
            item.is_sold = sold
        if photos:
            item.image_urls = photos
            item.images_are_complete = True
        return item
