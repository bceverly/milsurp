"""Jim's Firearms (jimsfirearms.net) -- the used guns.

A Baton Rouge and Pensacola dealer, added on 2026-10-28 with the used-gun
shops asked for to catch used carry pistols. Its old address,
jimsfirearms.com, is now a parked domain; the shop is at .net.

A newer template on the ColdFusion storefront Sportsman's Outdoor runs, with
markup of its own: the used section is 40 cards a page (about 80 on
2026-10-28, two thirds pistols and revolvers, every title "Used ..."), paged
by ``/browse/page/N``. A card carries the shop's style id, the maker, the
title, the price and one picture; the product page adds the description and
whether it is still "IN STOCK", read once per listing. robots.txt asks for
ten seconds between requests, which the fetcher honors, and disallows only
cart, account and taxonomy scripts.
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

SITE_BASE = "https://www.jimsfirearms.net/"
USED = f"{SITE_BASE}firearms-used_guns"
MAX_PAGES = 20
_PHOTO = re.compile(r"/prodimages/alt_images/large/[^\"'\s<>]+\.(?:jpe?g|png|webp)", re.I)


def page_url(page: int) -> str:
    return USED if page == 1 else f"{USED}/browse/page/{page}"


def item_from_card(card: Tag) -> ScrapedItem | None:
    wrapper = card.select_one("div.product-wrapper[data-styleid]")
    link = card.select_one("a.product-link[href]")
    name = card.select_one("h5.product-name")
    if wrapper is None or link is None or name is None:
        return None
    style = str(wrapper.get("data-styleid") or "")
    title = normalize_whitespace(name.get_text(" ", strip=True))
    if not style or not title:
        return None
    brand = card.select_one(".brand")
    price = card.select_one("span.salePrice")
    image = card.select_one("img[src]")
    src = str(image.get("src")) if image is not None else ""
    return ScrapedItem(
        external_key=f"jims-{style}",
        url=urljoin(SITE_BASE, str(link.get("href"))),
        title=title,
        price=parse_price(price.get_text(" ", strip=True)) if price else None,
        category="Used Guns",
        manufacturer=normalize_whitespace(brand.get_text(" ", strip=True)) if brand else None,
        is_new=False,
        image_urls=[re.sub(r"-DEFAULT-m\.", "-DEFAULT-l.", urljoin(SITE_BASE, src))] if src else [],
        images_are_complete=False,
    )


def cards_on(page: str) -> list[ScrapedItem]:
    soup = BeautifulSoup(page, "html.parser")
    found: dict[str, ScrapedItem] = {}
    for card in soup.select("ul.product-list-grid li.product-item"):
        item = item_from_card(card)
        if item is not None:
            found.setdefault(item.external_key, item)
    return list(found.values())


def detail_from(page: str) -> tuple[str | None, bool, list[str]]:
    """The description, whether it is still for sale, and the alternate photos."""
    soup = BeautifulSoup(page, "html.parser")
    block = soup.select_one(".tab-content")
    description = None
    if block is not None:
        text = normalize_whitespace(block.get_text(" ", strip=True))
        description = re.sub(r"\s*Write a Review\s+SUBMIT\s*$", "", text) or None
    words = soup.get_text(" ", strip=True)
    for_sale = "IN STOCK" in words or "Add to Cart" in words
    photos = []
    for path in _PHOTO.findall(page):
        url = urljoin(SITE_BASE, path)
        if url not in photos:
            photos.append(url)
    return description, for_sale, photos


class JimsFirearmsScraper(SiteScraper):
    slug = "jims-firearms"
    name = "Jim's Firearms"
    base_url = SITE_BASE
    description = "Louisiana and Florida dealer's used guns, mostly pistols and revolvers."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "used"
    #: The maker comes from the card's own brand.
    states_facts = True
    newsletter_url = SITE_BASE
    newsletter_note = '"Sign Up" newsletter form in the footer of every page'
    shipping_note = "Ships once the buyer's dealer's FFL is on file; no firearm rate published"
    shipping_source = f"{SITE_BASE}shipping"

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            try:
                html = ctx.get_text(page_url(page))
            except ScrapeError as exc:
                if page == 1:
                    raise
                ctx.warn(f"Could not read page {page}: {exc}. Stopping the section there.")
                return
            fresh = [item for item in cards_on(html) if item.external_key not in seen]
            if not fresh:
                break
            ctx.log(f"Used page {page}: {len(fresh)} listing(s).")
            for item in fresh:
                seen.add(item.external_key)
                yield self._detailed(ctx, item)
            if f"/browse/page/{page + 1}" not in html:
                break

    def _detailed(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        if not ctx.needs_detail(item.external_key):
            return item
        try:
            page = ctx.get_text(item.url)
        except ScrapeError as exc:
            ctx.warn(f"Could not read {item.url}: {exc}; keeping the card only.")
            return item
        description, for_sale, photos = detail_from(page)
        item.description = description or item.description
        item.is_sold = not for_sale
        item.image_urls = item.image_urls + [url for url in photos if url not in item.image_urls]
        item.images_are_complete = True
        return item
