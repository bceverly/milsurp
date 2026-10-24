"""Veteran Arms (veteranarms.com).

A living-history supplier of reproduction muskets and pistols, asked for on
2026-10-24 alongside Military Heritage: matchlocks, Brown Besses,
Charlevilles, Springfields and the pistols that went with them, 31 muskets and
11 pistols on 2026-10-24 -- all but two of them sold out that day, which is
worth reading too, because a gun coming back in stock is the news.

**It needs a browser.** The site is Joomla, and its shop is an Ecwid store
embedded in it: the category page arrives with no products in it, and Ecwid's
script draws them. Ecwid's own REST API wants a token the page does not
publish (403 without one), so the walk renders the page in headless Chrome
and reads the grid it draws -- every card carries Ecwid's product id, the
title, the price, one photograph and, on a sold-out gun, a class saying so.
Product pages are rendered the same way, once per listing, for the
description and the photographs.

robots.txt is Joomla's stock file and disallows only its own system folders;
every URL is still asked about before Chrome is sent to it.

**New or used**: the reproductions are new, and a gun labeled "Consignment"
is somebody's -- the one on 2026-10-24 was an original 18th-century French
flintlock pistol.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import (
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
    parse_price,
)
from .browser import chrome, wait_for_any

SITE_BASE = "https://veteranarms.com/"

#: The cards Ecwid draws, and the class it puts on a sold-out one.
CARD = ".grid-product"
_SOLD_OUT_CLASS = "ec-store-productsGrid-cell-outOfStock"
#: Ecwid's control for a next page of the grid. The sections held 31 and 11 on
#: 2026-10-24, inside one page; a section that grows past it is reported.
_NEXT_PAGE = ".pager__button--next, .pager__arrow--next"
_PRODUCT_ID = re.compile(r"-p(\d+)(?:$|[/?#])")
#: Ecwid groups thousands with a no-break space: "$5\xa0950.00".
_GROUPED = re.compile(r"(?<=\d)[\s\xa0\u202f](?=\d{3}\b)")


def ecwid_price(text: str | None) -> float | None:
    """A price as Ecwid writes it, thousands grouped by a space or not."""
    return parse_price(_GROUPED.sub("", text or ""))


def grid_items(page: str, category: str) -> list[ScrapedItem]:
    """Every card on a rendered category page."""
    soup = BeautifulSoup(page, "html.parser")
    items: list[ScrapedItem] = []
    for card in soup.select(CARD):
        item = item_from_card(card, category)
        if item is not None:
            items.append(item)
    return items


def item_from_card(card: Tag, category: str) -> ScrapedItem | None:
    link = card.select_one("a.grid-product__title[href], a.grid-product__image[href]")
    href = link.get("href") if link is not None else None
    title_node = card.select_one(".grid-product__title-inner")
    title = normalize_whitespace(title_node.get_text(" ", strip=True)) if title_node else ""
    if not isinstance(href, str) or not title:
        return None
    url = urljoin(SITE_BASE, href)
    wrap = card.select_one("[data-product-id]")
    product_id = wrap.get("data-product-id") if wrap is not None else None
    if not isinstance(product_id, str):
        found = _PRODUCT_ID.search(url)
        product_id = found.group(1) if found else None
    if not product_id:
        return None
    price_node = card.select_one(".grid-product__price-value")
    labels = [
        normalize_whitespace(node.get_text(" ", strip=True)) for node in card.select(".label__text")
    ]
    sold = _SOLD_OUT_CLASS in (card.get("class") or []) or any(
        label.lower() == "sold out" for label in labels
    )
    image = card.select_one("img.grid-product__picture")
    src = image.get("src") if image is not None else None
    return ScrapedItem(
        external_key=f"ecwid-{product_id}",
        url=url,
        title=title,
        price=ecwid_price(price_node.get_text(strip=True)) if price_node else None,
        category=category,
        is_sold=sold,
        image_urls=[src] if isinstance(src, str) and src.startswith("http") else [],
        images_are_complete=False,
        is_new=not any(label.lower() == "consignment" for label in labels),
    )


def detail_from(page: str) -> tuple[str | None, list[str]]:
    """The description and photographs on a rendered product page."""
    soup = BeautifulSoup(page, "html.parser")
    description = None
    for selector in (
        ".product-details__product-description",
        "#productDescription",
        ".product-details__description",
    ):
        node = soup.select_one(selector)
        if node is not None:
            text = normalize_whitespace(node.get_text(" ", strip=True))
            # The outer block repeats the title and breadcrumb before the prose.
            text = re.sub(r"^.*?\bProduct Details\s+", "", text, count=1)
            if text:
                description = text
                break
    photos: list[str] = []
    for image in soup.select(".details-gallery__picture, .details-gallery__thumb img"):
        src = image.get("src")
        if isinstance(src, str) and src.startswith("http") and src not in photos:
            photos.append(src)
    return description, photos


class VeteranArmsScraper(SiteScraper):
    slug = "veteran-arms"
    name = "Veteran Arms"
    base_url = SITE_BASE
    description = (
        "Living-history supplier of reproduction muskets and pistols, from the "
        "matchlock to the Civil War. Needs a headless browser (an Ecwid store)."
    )
    requires_browser = True
    default_interval_minutes = 1440
    #: New reproductions, and the odd original on consignment.
    sells = "mixed"
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-24"
    shipping_long_gun = 60.0
    shipping_handgun = 30.0
    shipping_note = (
        "Flat rate, continental US: musket $60, carbine $50, pistol $30; "
        "pre-1898 reproductions ship to the door in most states"
    )
    shipping_source = f"{SITE_BASE}ordering-shipping"
    #: How long Ecwid gets to draw a page after its first card appears.
    settle_seconds: float = 4.0
    #: The pause between one page and the next. Chrome fetches a page's
    #: scripts and pictures as well, so the pause is longer than a plain
    #: fetcher's.
    page_gap_seconds: float = 5.0

    sources = (
        {"category": "Muzzleloading Muskets", "url": f"{SITE_BASE}shop/muskets"},
        {"category": "Muzzleloading Pistols", "url": f"{SITE_BASE}shop/pistols"},
    )

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    _rendered = 0

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        self._rendered = 0
        found: dict[str, ScrapedItem] = {}
        with chrome(ctx.scraping) as driver:
            for source in self.sources:
                ctx.check_stop()
                url, category = source["url"], source["category"]
                if not ctx.allowed(url):
                    ctx.warn(f"{ctx.why_not(url)}; not reading {category}.")
                    ctx.not_read(category)
                    continue
                page = self._render(ctx, driver, url, CARD)
                if page is None:
                    ctx.warn(f"{category}: no products appeared at {url}.")
                    ctx.not_read(category)
                    continue
                items = grid_items(page, category)
                ctx.log(f"{category}: {len(items)} listing(s).")
                if BeautifulSoup(page, "html.parser").select_one(_NEXT_PAGE) is not None:
                    ctx.warn(f"{category} has grown past one page; only the first was read.")
                for item in items:
                    if item.external_key not in found:
                        found[item.external_key] = item
                        yield item
            if not found:
                raise ScrapeError("No products appeared on any Veteran Arms section.")
            yield from self._details(ctx, driver, list(found.values()))

    def _render(self, ctx: ScrapeContext, driver, url: str, selector: str) -> str | None:
        ctx.log(f"Rendering {url}")
        if self._rendered:
            ctx.sleep(self.page_gap_seconds)
        self._rendered += 1
        driver.get(url)
        if wait_for_any(driver, (selector,), timeout=25) is None:
            return None
        ctx.sleep(self.settle_seconds)
        return str(driver.page_source)

    def _details(
        self, ctx: ScrapeContext, driver, items: list[ScrapedItem]
    ) -> Iterator[ScrapedItem]:
        pending = [item for item in items if ctx.needs_detail(item.external_key)]
        if pending:
            ctx.log(f"Reading {len(pending)} product page(s)…")
        for item in pending:
            ctx.check_stop()
            if not ctx.allowed(item.url):
                continue
            page = self._render(ctx, driver, item.url, ".product-details")
            if page is None:
                ctx.warn(f"{item.url}: the product page did not draw.")
                continue
            description, photos = detail_from(page)
            if description:
                item.description = description
            if photos:
                item.image_urls = photos
                item.images_are_complete = True
            yield item
