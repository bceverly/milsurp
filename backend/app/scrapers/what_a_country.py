"""What A Country (whatacountry.com).

A parts-kit shop, and the pick of what was left on the parts-kit candidate list:
thirty kits, every one of them surplus -- a Colt M16A1, an M1 Carbine, a
Hungarian AK63D and AMD-65, a Finnish Suomi M-31, a Rheinmetall MG3, an HK11,
an Imbel FAL, Galil and UZI kits, Polish DPM and RPD, PPS-43, three STENs and
a Yugo M72B1 RPK. Only the Parts Kits section is read; the rest of the shop is
individual parts, slings, stocks and air rifles, which the standing rule keeps
out.

**An older ASP.NET storefront, and a plain one to read.** Each product on the
category page is a ``div.product-list-item`` with a link, a name, a list price
and -- on about half of them -- a sale price beside it. The section is one page:
thirty products, no pager, and a page-number parameter returns the same first
product.

**The product page is read on every scan, not once.** It is the only place the
shop says whether a kit is in stock, and a kit that sells out stays listed. At
thirty pages and the two-second pace that is a minute a day.

**Keyed by URL path.** The product id (``var prodId``) is only on the product
page, so a key built from it would change for any listing whose page failed to
load on a given scan -- and a changed key reads as the listing de-listed and a
new one arriving. The path is on the category card, stable while the shop keeps
its URLs, which for a catalog this size it does.

**Some kits are "Starting at" a price**, when the product has options (a state
compliance variant, a stock choice). That lowest figure is what is recorded;
the options are on the shop's page.

robots.txt disallows the cart, account, checkout and search pages and nothing a
product lives under.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .base import (
    SOLD_OUT_TEXT,
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
    text_of,
    vendors_answer,
)
from .storefront import parse_price

SITE_BASE = "https://whatacountry.com/"

CARD = "div.product-list-item"
CARD_LINK = "h5 a[href]"
#: The sale price when there is one, the list price otherwise.
CARD_SALE = ".product-list-sale-value"
CARD_COST = ".product-list-cost-value"

DETAIL_STOCK = ".prod-detail-stock"
DETAIL_DESCRIPTION = ".prod-detail-desc"

#: The product's own photographs, at the largest size the shop keeps. The
#: page also shows related products, but only as thumbnails from another
#: folder, so this cannot pick up a neighbor's picture.
_GALLERY = re.compile(r"/images/products/detail/[^\"'\s)<>]+\.(?:jpe?g|png|gif|webp)", re.I)


def gallery(markup: str) -> list[str]:
    """Every distinct product photograph on a product page, in page order."""
    seen: list[str] = []
    for found in _GALLERY.finditer(markup):
        url = urljoin(SITE_BASE, found.group(0))
        if url not in seen:
            seen.append(url)
    return seen


def card_price(card: Tag) -> float | None:
    """What the kit costs today: the sale figure if there is one."""
    for selector in (CARD_SALE, CARD_COST):
        found = card.select_one(selector)
        if found is not None:
            price = parse_price(found.get_text(" ", strip=True))
            if price:
                return price
    return None


class WhatACountryScraper(SiteScraper):
    slug = "what-a-country"
    name = "What A Country"
    base_url = SITE_BASE
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-09-26"
    description = (
        "Parts kit specialist: Colt M16A1, M1 Carbine, Hungarian and Polish AKs, "
        "FAL, Galil, UZI, Suomi, MG3, HK11, STEN and RPD kits."
    )
    requires_browser = False
    default_interval_minutes = 1440
    min_request_delay: float = 2.0

    sources: tuple[dict[str, str], ...] = ({"category": "Parts Kits", "path": "parts-kits.aspx"},)

    #: Stop reading product pages after this many fail in a row, so a shop that
    #: serves its grid and refuses its products is not walked one refusal at a
    #: time. Same reasoning as the platform classes.
    MAX_DETAIL_FAILURES = 3

    _detail_failures = 0
    _gave_up_on_details = False

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._detail_failures = 0
        self._gave_up_on_details = False
        seen: set[str] = set()
        for source in self.sources:
            ctx.check_stop()
            url = urljoin(self.base_url, source["path"])
            soup = BeautifulSoup(ctx.get_text(url), "html.parser")
            cards = soup.select(CARD)
            if not cards:
                ctx.warn(f"{source['category']!r} showed no products; has the page changed?")
                continue
            ctx.log(f"{source['category']}: {len(cards)} listing(s).")
            for card in cards:
                item = self._card(card, url, source["category"])
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield self._detailed(ctx, item)

    def _card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        link = card.select_one(CARD_LINK)
        if link is None:
            return None
        url = urljoin(page_url, str(link.get("href") or ""))
        title = normalize_whitespace(link.get_text(" ", strip=True))
        path = urlparse(url).path.strip("/")
        if not title or not path:
            return None
        thumbnail = card.select_one("img.product-list-img")
        thumb = str(thumbnail.get("src") or "") if thumbnail is not None else ""
        return ScrapedItem(
            external_key=f"wac-{path.removesuffix('.aspx').lower()}",
            url=url,
            title=title,
            price=card_price(card),
            category=category,
            image_urls=[urljoin(page_url, thumb)] if thumb else [],
            images_are_complete=False,
        )

    def _detailed(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """Stock, description and gallery from the product page.

        A page that cannot be read keeps the card: its title, price and
        thumbnail are good, and losing them to one bad request would be a poor
        trade. Its stock is then unknown, and it is left marked for sale.
        """
        if self._gave_up_on_details:
            return item
        try:
            markup = ctx.get_text(item.url)
        except Disallowed:
            ctx.warn(f"robots.txt disallows {item.url}; keeping the catalog entry only.")
            return item
        except ScrapeError as exc:
            self._detail_failures += 1
            if self._detail_failures >= self.MAX_DETAIL_FAILURES:
                self._gave_up_on_details = True
                ctx.warn(
                    f"{self._detail_failures} product pages in a row could not be read; "
                    f"taking the rest of this scan from the category page. Last error: {exc}"
                )
            else:
                say = ctx.log if vendors_answer(exc) else ctx.warn
                say(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item

        self._detail_failures = 0
        soup = BeautifulSoup(markup, "html.parser")
        stock = soup.select_one(DETAIL_STOCK)
        description = soup.select_one(DETAIL_DESCRIPTION)
        photos = gallery(markup)
        return ScrapedItem(
            external_key=item.external_key,
            url=item.url,
            title=item.title,
            price=item.price,
            description=text_of(description) if description is not None else None,
            category=item.category,
            is_sold=bool(stock is not None and SOLD_OUT_TEXT.search(text_of(stock))),
            image_urls=photos or item.image_urls,
            images_are_complete=bool(photos),
        )
