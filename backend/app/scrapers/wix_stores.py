"""Shared machinery for shops running Wix Stores.

**Wix renders client-side and this needs no browser**, which is the opposite of
what this project assumed for three years. The catalog grid and the product page
are both delivered as HTML with the store's data already in them; what is drawn
client-side is the interactivity, not the content. The roadmap said "Wix renders
client-side, so expect the browser path" — the fifth time that inference has
been wrong here, after J&G Sales, Centerfire, SARCO and AIM Surplus.

**Wix marks its own furniture, and that is the whole of this class.** Every
element worth reading carries a stable ``data-hook``:

* ``product-item-root`` — one card
* ``product-item-product-details-link`` — its link
* ``product-item-name`` — its title
* ``product-item-price-to-pay`` — what it costs, when it is for sale
* ``product-item-out-of-stock`` — when it is not, and then there is no price
* ``description`` / ``sku`` / ``product-price`` — on the product page

These are Wix's, not a theme's, so they survive the shop restyling itself.
That is worth more here than a CSS selector chosen from one vendor's markup,
which is what the BigCommerce and WooCommerce classes had to start from.

**Paging is ``?page=N``.** Wix hides an SEO pagination list beside its
"Load More" button — ``product-list-pagination-seo`` — so the pages a person
reaches by scrolling are reachable by asking. Check robots.txt allows a query
string: Surplus Defense disallows only ``*?lightbox=``, but Collectors Firearms
is the standing reminder that ``Disallow: /*?*`` exists and rules this out.

**Images: strip the transform.** Wix serves every image through a resizing
path — ``…~mv2.jpg/v1/fill/w_1000,h_750,…/file.jpg`` — and the page never
references the original. Cutting everything from ``/v1/`` gives it: 1.7MB
against 53KB for one M1 carbine photograph. Hunter's Lodge taught this on the
same CDN, where the difference was OCR that worked against OCR that returned
nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, flatten_html
from .storefront import parse_price

#: Wix's own hooks, not a theme's.
CARD = '[data-hook="product-item-root"]'
CARD_LINK = '[data-hook="product-item-product-details-link"]'
CARD_NAME = '[data-hook="product-item-name"]'
CARD_PRICE = '[data-hook="product-item-price-to-pay"]'
CARD_SOLD = '[data-hook="product-item-out-of-stock"]'

#: Where a Wix image lives before it is resized. See the module docstring.
_MEDIA = re.compile(
    r"https://static\.wixstatic\.com/media/[A-Za-z0-9_~.-]+?\.(?:jpg|jpeg|png|webp)"
)

#: A product's stable identity. Wix product URLs are `/product-page/<slug>`,
#: and the slug is what the shop controls -- a title change does not move it.
_SLUG = re.compile(r"/product-page/([A-Za-z0-9._-]+)")


def full_size(url: str) -> str:
    """The original, with Wix's resizing transform cut off.

    ``…~mv2.jpg/v1/fill/w_1000,h_750,…/file.jpg`` -> ``…~mv2.jpg``.
    """
    cut = url.find("/v1/")
    return url[:cut] if cut != -1 else url


def gallery(markup: str) -> list[str]:
    """Every distinct original image on a product page, in page order.

    De-duplicated because Wix emits each photograph several times at different
    sizes -- a thumbnail, a main view, a zoom -- and they all reduce to the same
    original.
    """
    seen: list[str] = []
    for found in _MEDIA.finditer(markup):
        url = full_size(found.group(0))
        if url not in seen:
            seen.append(url)
    return seen


class WixStoresScraper(SiteScraper):
    """One Wix Stores shop. Subclasses supply the slug, name and sources."""

    #: One entry per category: ``{"category": "Surplus Rifles", "path": "surplus-rifles"}``.
    #: The path is the shop's own page; the category is what listings are filed
    #: under here and what the classifier reads.
    sources: tuple[dict[str, str], ...] = ()

    #: Where the prose lives on the product page. Wix's own hook first; the
    #: Open Graph description is the fallback, and is what a shop that has
    #: restyled its description block still publishes.
    detail_description_selectors: tuple[str, ...] = (
        '[data-hook="description"]',
        '[data-hook="description-wrapper"]',
    )

    #: Small dealers, and a whole scan is a few dozen requests.
    min_request_delay: float = 2.0

    #: Bounded like every walk here.
    max_pages_per_source = 30

    requires_browser = False

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if not self.sources:  # pragma: no cover - a subclass bug, not a state
            raise ScrapeError(f"{type(self).__name__} lists no sources to scan.")
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)

        # Across sections: a shop usually files the same rifle under its type
        # and under an "all products" page, and the second copy must not arrive
        # as a second listing.
        seen: set[str] = set()
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, str], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        label = source["category"]
        page = 1
        while page <= min(self.max_pages_per_source, ctx.scraping.max_pages):
            ctx.check_stop()
            url = urljoin(self.base_url, source["path"])
            if page > 1:
                url = f"{url}?page={page}"

            soup = BeautifulSoup(ctx.get_text(url), "lxml")
            cards = soup.select(CARD)
            if not cards:
                break

            fresh = 0
            for card in cards:
                item = self._card(ctx, card, url, label)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                fresh += 1
                yield item

            ctx.log(f"{label} page {page}: {fresh} listing(s).")
            page += 1

    def _card(self, ctx: ScrapeContext, card: Tag, page_url: str, label: str) -> ScrapedItem | None:
        link = card.select_one(CARD_LINK)
        href = link.get("href") if link else None
        if not href:
            return None
        url = urljoin(page_url, str(href))
        found = _SLUG.search(url)
        if not found:
            return None

        name = card.select_one(CARD_NAME)
        title = name.get_text(" ", strip=True) if name else ""
        if not title:
            return None

        price_tag = card.select_one(CARD_PRICE)
        # Out of stock is how this platform says sold, and it takes the price
        # away with it -- so a listing with no price here is not "call for
        # price", it is gone.
        sold = card.select_one(CARD_SOLD) is not None

        key = f"wix-{found.group(1)}"
        item = ScrapedItem(
            external_key=key,
            url=url,
            title=title,
            price=parse_price(price_tag.get_text(" ", strip=True)) if price_tag else None,
            category=label,
            is_sold=sold,
            images_are_complete=False,
        )
        if not ctx.needs_detail(key):
            return item
        return self._detailed(ctx, item) or item

    def _detailed(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem | None:
        """The prose and the gallery from the product page.

        A failure keeps the grid record: the card already carries a title, a
        price and a URL, and losing those to a single bad product page would be
        a poor trade.
        """
        try:
            markup = ctx.get_text(item.url)
        except Exception as exc:
            ctx.warn(f"Could not read {item.url} ({exc})")
            return None

        soup = BeautifulSoup(markup, "lxml")
        description = None
        for selector in self.detail_description_selectors:
            tag = soup.select_one(selector)
            if tag:
                description = flatten_html(str(tag))
                if description:
                    break
        if not description:
            meta = soup.select_one('meta[property="og:description"]')
            # str(), because BeautifulSoup types an attribute as str *or* a
            # list of them: a multi-valued attribute like class comes back as a
            # list, and the type checker cannot know content never does.
            description = str(meta.get("content") or "").strip() if meta else None

        return ScrapedItem(
            external_key=item.external_key,
            url=item.url,
            title=item.title,
            price=item.price,
            description=description or None,
            category=item.category,
            is_sold=item.is_sold,
            image_urls=gallery(markup),
            images_are_complete=True,
        )
