"""Shared machinery for PrestaShop shops.

The fifth storefront platform, and so far a class of one: Atlantic Firearms.
That is worth saying out loud, because "one platform, one shop" is exactly the
arithmetic the BigCommerce group got wrong -- but the shape of the work is the
same as the other four and the class is small, so the cost of putting it here
rather than in the subclass is a few lines.

PrestaShop renders a category as ``article.product`` (or ``.js-product``) cards
carrying the name in ``.product-title`` and the price in ``.price``, and it
paginates with ``?page=N``.

**The query string is the thing to check first**, as always. PrestaShop ships a
generated robots.txt that disallows a long list of query parameters --
``?order=``, ``?tag=``, ``?search_query=``, ``?n=``, ``?limit=`` and the
``controller=`` routes -- and every one of those is a *facet or a sort*.
``?page=`` is not among them, so ordinary pagination is permitted where sorting
and filtering are not. The walk asks robots.txt about each page anyway, which
is what makes that safe to rely on rather than merely true today.

**Half of what these shops list has no price.** That is not a parsing failure:
PrestaShop hides the price of an out-of-stock product, and a surplus dealer's
catalog is full of them. A listing with no price is still worth storing -- it
is what "call for price" means on the item page -- but a shop where most of the
catalog is unpriced is a poor subject for a price watcher, and that is a
judgement to make from a measurement rather than from the platform.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    flatten_html,
    text_of,
    vendors_answer,
)
from .storefront import image_sources, parse_price

#: PrestaShop names the size in the id segment of an image path:
#:
#:   /470108-detail_product_thumbnail/vz-58-barrel.jpg   a thumbnail
#:   /470108-product_main/vz-58-barrel.jpg               the main view
#:   /470108/vz-58-barrel.jpg                            the upload
#:
#: The theme's own ``data-image-large-src`` points at that last form, which is
#: what makes the rule safe to apply rather than merely plausible: dropping the
#: suffix is what the shop itself does to ask for the original.
#: Anchored at the start of the path, because that is where PrestaShop puts
#: these and a looser rule rewrites things that merely look like one:
#: ``/img/2024-holiday/banner.jpg`` is not an image id and a size.
_IMAGE_SIZE = re.compile(r"^/(\d+)-[a-z0-9_]+/")


def full_size(url: str) -> str:
    """The original upload behind a PrestaShop thumbnail URL."""
    parts = urlsplit(url)
    path = _IMAGE_SIZE.sub(r"/\g<1>/", parts.path)
    return urlunsplit(parts._replace(path=path)) if path != parts.path else url


class PrestaShopScraper(SiteScraper):
    """One PrestaShop shop. Subclasses supply the slug, name and sources."""

    sources: tuple[dict[str, str], ...] = ()

    #: Several names for the same card, and a theme may carry more than one of
    #: them *nested*: Atlantic Firearms wrap every ``article.product-miniature``
    #: in a ``div.js-product``, so a plain comma-selector matches each product
    #: twice. See _cards(), which keeps the innermost.
    card_selector: str = "article.product, .js-product, .product-miniature"
    title_selectors: tuple[str, ...] = (".product-title", "h2.product-title", "h2", "h3")
    link_selectors: tuple[str, ...] = (".product-title a", "a.product-thumbnail", "a[href]")
    price_selectors: tuple[str, ...] = (".price", ".product-price", "[itemprop=price]")

    detail_title_selectors: tuple[str, ...] = ("h1.page-title", "h1[itemprop=name]", "h1")
    detail_description_selectors: tuple[str, ...] = (
        "#description .product-description",
        ".product-description",
        "#description",
        '[itemprop="description"]',
    )
    #: The gallery before the cover, and that order is the whole point.
    #: ``.product-cover img`` is one photograph -- the main view -- and
    #: ``.product-images img`` is the strip that contains it and the other
    #: sixteen. The base walk stops at the first selector that yields anything,
    #: so putting the cover first would store one picture per listing and call
    #: the gallery complete.
    detail_gallery_selectors: tuple[str, ...] = (
        ".product-images img",
        "#main .images-container img",
        ".product-cover img",
        ".js-qv-product-cover",
    )

    min_request_delay: float = 5.0
    max_pages_per_source = 40
    requires_browser = False

    #: Give up on product pages after this many in a row fail. Same reasoning
    #: as the other platforms: a shop that refuses every one of them should not
    #: have its whole catalog walked a pointless request at a time.
    MAX_DETAIL_FAILURES = 3

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        if not self.sources:  # pragma: no cover - a subclass bug, not a state
            raise ScrapeError(f"{type(self).__name__} lists no sources to scan.")
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._detail_failures = 0
        self._gave_up_on_details = False
        seen: set[str] = set()
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, str], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        category = source.get("category") or ""
        base = source["url"]
        page = 1

        while page <= min(self.max_pages_per_source, ctx.scraping.max_pages):
            ctx.check_stop()
            url = base if page == 1 else f"{base}?page={page}"

            if not ctx.allowed(url):
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                if page == 1:
                    ctx.not_read(category)
                return
            try:
                soup = BeautifulSoup(ctx.get_text(url), "html.parser")
            except Disallowed:
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                if page == 1:
                    ctx.not_read(category)
                return
            except ScrapeError as exc:
                if page == 1:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {page - 1}.")
                return

            cards = self._cards(soup)
            ctx.log(f"{category or 'catalog'} page {page}: {len(cards)} listing(s).")
            # An empty page is the end of the section. PrestaShop answers 200
            # for a page number past the last one, so there is no error to
            # notice -- only the absence of cards.
            if not cards:
                return

            fresh = 0
            for card in cards:
                item = self.item_from_card(card, url, category)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                fresh += 1
                yield self.with_detail(ctx, item)

            # Every card already seen means the shop is serving the same page
            # again rather than a further one, which is what a `?page=` past
            # the end does on some themes.
            if not fresh:
                return
            page += 1

    def _cards(self, soup: BeautifulSoup) -> list[Tag]:
        """The product cards, one per product.

        The selector names several things a theme may call a card, and a theme
        may use more than one of them for the *same* product: Atlantic Firearms
        wrap each ``article.product-miniature`` in a ``div.js-product``, so a
        plain ``select()`` returns 24 cards for 12 products.

        Keeping the innermost match fixes it without a per-shop override, and
        it is right on the merits: the inner element is the card and the outer
        is the grid cell holding it. The ``seen`` set would collapse the
        duplicates by key anyway -- but the scan log would report double what
        the shop sells, and a count that is wrong in the logs is one somebody
        later trusts.
        """
        found = soup.select(self.card_selector)
        inner = [tag for tag in found if not any(other in tag.descendants for other in found)]
        return inner or found

    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        link = self._first_href(card, self.link_selectors, page_url)
        title = self._first_text(card, self.title_selectors)
        if link is None or not title:
            return None

        thumbnails = [
            full_size(urljoin(page_url, url))
            for tag in card.select("img")
            for url in image_sources(tag)[:1]
        ]
        return ScrapedItem(
            external_key=self.key_for(card, link),
            url=link,
            title=title,
            price=self._price(card),
            category=category,
            image_urls=thumbnails[:1],
            # One preview, not the gallery.
            images_are_complete=False,
        )

    def key_for(self, card: Tag, link: str) -> str:
        """The shop's own product id where the theme writes one.

        PrestaShop puts it on the card as ``data-id-product``. Preferred over
        the URL for the usual reason: a renamed product keeps its id and would
        otherwise read as one listing withdrawn and another appearing.
        """
        for attribute in ("data-id-product", "data-product-id"):
            value = card.get(attribute)
            if isinstance(value, str) and value.strip().isdigit():
                return f"ps-{value.strip()}"
        return f"path-{urlparse(link).path.strip('/').replace('/', '-')[:180]}"

    def _price(self, card: Tag) -> float | None:
        """What the shop is asking, or None where it shows nothing.

        Nothing is the common case on these shops and is not a failure: an
        out-of-stock product has its price hidden, and roughly half of a
        surplus dealer's catalog is out of stock at any moment.
        """
        for selector in self.price_selectors:
            found = card.select_one(selector)
            if found is None:
                continue
            price = parse_price(text_of(found))
            if price:
                return price
        return None

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """Fill in the description and the gallery, if they are still needed."""
        if not ctx.needs_detail(item.external_key) or self._gave_up_on_details:
            return item
        try:
            soup = BeautifulSoup(ctx.get_text(item.url), "html.parser")
        except Disallowed:
            ctx.warn(f"robots.txt disallows {item.url}; keeping the catalog entry only.")
            return item
        except ScrapeError as exc:
            self._detail_failures += 1
            if self._detail_failures >= self.MAX_DETAIL_FAILURES:
                self._gave_up_on_details = True
                ctx.warn(
                    f"{self._detail_failures} product pages in a row could not be read; "
                    f"taking the rest of this scan from the catalog only. Last error: {exc}"
                )
            else:
                # Logged rather than warned when the shop is stating a policy: a
                # single 403 or 404 on a product page is a standing decision, and
                # warning about it every scan makes the site permanently PARTIAL.
                # A run of them still warns, above. See base.vendors_answer.
                say = ctx.log if vendors_answer(exc) else ctx.warn
                say(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item

        self._detail_failures = 0
        images = self.gallery(soup, item.url)
        return replace(
            item,
            title=self._first_text(soup, self.detail_title_selectors) or item.title,
            description=self._description(soup) or item.description,
            image_urls=images or item.image_urls,
            images_are_complete=bool(images),
        )

    def _description(self, soup: BeautifulSoup) -> str | None:
        for selector in self.detail_description_selectors:
            found = soup.select_one(selector)
            if found is None:
                continue
            # Flattened rather than read as text: these blocks are vendor HTML
            # and may carry a stylesheet, which get_text() would hand back as
            # prose. See scrapers.base.flatten_html.
            text = flatten_html(str(found))
            if text:
                return text
        return None

    def gallery(self, soup: BeautifulSoup, base: str) -> list[str]:
        found: list[str] = []
        for selector in self.detail_gallery_selectors:
            for tag in soup.select(selector):
                for url in image_sources(tag):
                    absolute = full_size(urljoin(base, url))
                    if absolute not in found:
                        found.append(absolute)
            if found:
                break
        return found

    def _first_text(self, scope: Tag | BeautifulSoup, selectors: Iterable[str]) -> str:
        for selector in selectors:
            found = scope.select_one(selector)
            if found is not None:
                text = text_of(found)
                if text:
                    return text
        return ""

    def _first_href(self, scope: Tag, selectors: Iterable[str], base: str) -> str | None:
        for selector in selectors:
            for found in scope.select(selector):
                href = found.get("href")
                if isinstance(href, str) and href.strip() and not href.startswith("#"):
                    return urljoin(base, href.strip())
        return None
