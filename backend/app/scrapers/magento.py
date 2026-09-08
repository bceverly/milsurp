"""Shared machinery for Magento shops.

The fourth storefront platform. Magento renders a category as a list of
``li.product-item`` cards with the title in ``.product-item-link`` and
pagination as ``?p=N`` — but it is themed more heavily than the others in
practice, so the selectors here are defaults rather than assumptions.
Classic Firearms and Century Arms are both Magento and share almost no CSS
class between their two grids.

**The product page is where this platform is generous.** Magento emits
schema.org ``Product`` JSON-LD, and where a shop has left it on it carries the
name, the SKU, the description, the original-resolution images and the price
and availability — everything the HTML scrapers reconstruct from markup that a
theme is free to rearrange. So that is read first and the selectors are the
fallback, which is the opposite of the other base classes and is the right way
round wherever a shop publishes structured data.

**Pagination has to be asked about, not assumed.** ``?p=N`` is a query string,
and Classic Firearms' robots.txt disallows exactly that: ``Disallow: /*?p=``
with an ``Allow:`` only for ``/news``. Their category pages therefore stop at
page one, which is not a failure and is reported rather than worked around.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    flatten_html,
    is_prose,
    is_sold_out,
    normalize_whitespace,
    offer_of,
    product_json_ld,
    text_of,
)
from .storefront import image_sources, parse_price

#: Magento serves a resized copy from a cache path that names the size and ends
#: with a 32-character hash of the theme configuration:
#:
#:   /media/catalog/product/cache/<hash>/h/g/hg2265e.jpg          (Magento 2)
#:   /media/catalog/product/cache/1/small_image/270x170/<hash>/2/0/x.png
#:
#: Both end with that hash immediately before the real path, which is what makes
#: one rule enough for both.
_CACHE_PATH = re.compile(r"/cache/(?:[^/]+/)*?[0-9a-f]{32}/")

#: The count a layered-navigation link carries: "8mm Mauser (8x57) (18)".
_FACET_COUNT = re.compile(r"\((\d+)\)\s*$")

#: Where a theme puts the cents in their own element beside the dollars.
_CENTS = ".decimal, .price-cents, sup"

#: The numeric product id Magento writes onto the card's wrapper.
_ITEM_ID = re.compile(r"product-item-info_(\d+)")


def full_size(url: str) -> str:
    """The original upload behind a Magento cache URL."""
    return _CACHE_PATH.sub("/", url)


def _plain_text(value: object) -> str:
    """One JSON-LD text field, with its HTML entities decoded.

    Magento writes the *escaped* name into its structured data on at least one
    shop: Apex Gun Parts publish ``1911 Pistol Parts Kit, 5&quot; Barrel`` in
    the JSON-LD and the correct ``5" Barrel`` in the ``<h1>`` beside it. JSON is
    not HTML, so nothing decodes those on the way in, and the entity would be
    stored, shown to the reader and handed to the classifier as-is.

    ``html.unescape`` and not a BeautifulSoup round-trip: a name is plain text
    that happens to be escaped, not markup, and an ampersand in a product name
    should survive as an ampersand.
    """
    if not isinstance(value, str):
        return ""
    return normalize_whitespace(unescape(value))


def price_now(card: Tag) -> float | None:
    """What the shop is asking, from a category card.

    Absent far more often than on the other platforms, and for two unrelated
    reasons that both mean "no price to watch": an out-of-stock listing, and a
    minimum-advertised-price rule that shows the number only in the cart.
    """
    # Magento puts this on a descendant span; a theme could put it on the card
    # itself, and select_one() only looks at descendants.
    for element in (card, *card.select("[data-price-amount]")):
        raw = element.get("data-price-amount")
        if raw is not None:
            price = parse_price(str(raw))
            if price is not None:
                return price
    for selector in (".special-price .price", ".price-wrapper", ".price"):
        found = card.select_one(selector)
        if found is not None:
            price = _amount(found)
            if price is not None:
                return price
    return None


def _amount(element: Tag) -> float | None:
    """One price, including the shops that set the cents in their own element.

    Classic Firearms renders ``$1599<span class="decimal">99</span>``, whose
    text is "$1599 99". Read as one number that is $1599.00 — and then the
    product page's structured data says 1599.99, so every re-scan that skipped
    the detail fetch would report a price change that had not happened.
    """
    if element.select_one(_CENTS) is None:
        return parse_price(element.get_text(" ", strip=True))

    # Work on a copy and take the cents element *out of the tree*, rather than
    # deleting its text from the string. "$1599 99" with the "99" removed by
    # text is "$15 9", which parses to 15.99 — a wrong answer that looks like a
    # right one.
    clone = BeautifulSoup(str(element), "html.parser")
    cents = clone.select_one(_CENTS)
    digits = re.sub(r"\D", "", cents.get_text(strip=True)) if cents is not None else ""
    if cents is not None:
        cents.extract()
    whole = parse_price(clone.get_text(" ", strip=True))
    if whole is None:
        return None
    return whole + int(digits[:2]) / 100 if digits else whole


class MagentoScraper(SiteScraper):
    """One Magento shop. Subclasses supply the slug, name and sources."""

    sources: tuple[dict[str, str], ...] = ()

    card_selector: str = "li.product-item, .products-grid .item"
    title_selectors: tuple[str, ...] = (
        "a.product-item-link",
        ".product-item-name a",
        ".product-name a",
        "h2 a",
    )
    link_selectors: tuple[str, ...] = (
        "a.product-item-link",
        "a.product-item-photo",
        "a.product-photo",
        "a[href]",
    )
    next_page_selectors: tuple[str, ...] = (
        "li.pages-item-next a",
        "a.action.next",
        ".pages a.next",
        "link[rel=next]",
    )

    detail_title_selectors: tuple[str, ...] = ("h1.page-title", "h1")
    detail_description_selectors: tuple[str, ...] = (
        ".product.attribute.description",
        ".product-view-descriptions-full",
        ".full-description",
        ".short-description",
        "#description",
    )
    detail_gallery_selectors: tuple[str, ...] = (
        ".fotorama__img",
        "[data-gallery-role] img",
        ".product.media img",
        ".product-view-images img",
    )

    min_request_delay: float = 5.0
    max_pages_per_source = 200
    requires_browser = False

    #: Walk the layered navigation instead of paging the category.
    #:
    #: For a shop that disallows its own pagination. Magento's layered nav is a
    #: set of facet groups — caliber, manufacturer, action — each of which
    #: *partitions* the category, and each facet value is a plain path with no
    #: query string in it. So where `?p=2` is off limits, the same products are
    #: still reachable one facet at a time, entirely within the rules.
    #:
    #: Off by default: it costs one request per facet value, which is only
    #: worth paying when the ordinary route is closed.
    follow_facets: bool = False
    facet_nav_selectors: tuple[str, ...] = (
        "#narrow-by-list",
        ".filter-options",
        "#layered-filter-block",
    )
    #: How many listings one category page shows, which is the threshold a
    #: facet has to fit under. Taken from the first page when left None, which
    #: is right as long as that page is full — and it is only consulted when
    #: there is a next page, so it is.
    facet_page_size: int | None = None

    # -- the scan -----------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        seen: set[str] = set()
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, str], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        category = source.get("category") or ""
        url: str | None = source["url"]
        visited: set[str] = set()
        pages = 0

        while url and pages < min(self.max_pages_per_source, ctx.scraping.max_pages):
            ctx.check_stop()
            if url in visited:
                break
            visited.add(url)

            if not ctx.allowed(url):
                # A shop is entitled to disallow its own pagination, and one of
                # these two does. Page one is still a page of listings.
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                return

            try:
                soup = BeautifulSoup(ctx.get_text(url), "html.parser")
            except Disallowed:
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                return
            except ScrapeError as exc:
                if pages == 0:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {pages}.")
                return

            pages += 1
            cards = soup.select(self.card_selector)
            ctx.log(f"{category or 'catalog'} page {pages}: {len(cards)} listing(s).")

            for card in cards:
                item = self.item_from_card(card, url, category)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield self.with_detail(ctx, item)

            following = self.next_page(soup, url)
            if self.follow_facets and pages == 1:
                # Only worth paying for when there is more to get. A section
                # that fits on one page has no second page to be barred from,
                # and walking its facets would re-fetch what is already read.
                if following is not None:
                    yield from self._walk_facets(
                        ctx, soup, url, category, seen, self.facet_page_size or len(cards)
                    )
                return

            url = following

    def _walk_facets(
        self,
        ctx: ScrapeContext,
        soup: BeautifulSoup,
        page_url: str,
        category: str,
        seen: set[str],
        page_size: int,
    ) -> Iterator[ScrapedItem]:
        """Read a category one facet at a time, for a shop that bars paging."""
        facets = self._best_facet(soup, page_url, page_size)
        if not facets:
            ctx.warn(
                f"No facet small enough to walk under {page_url}; "
                f"this section is the first page only."
            )
            return

        ctx.log(f"{category or 'catalog'}: walking {len(facets)} facet(s) instead of pages.")
        for url in facets:
            ctx.check_stop()
            if not ctx.allowed(url):
                continue
            try:
                page = BeautifulSoup(ctx.get_text(url), "html.parser")
            except (Disallowed, ScrapeError) as exc:
                # One facet that will not load costs its share of the category,
                # not the section: the others still partition the rest.
                ctx.warn(f"Could not read {url}: {exc}. Skipping that facet.")
                continue
            for card in page.select(self.card_selector):
                item = self.item_from_card(card, url, category)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield self.with_detail(ctx, item)

    def _best_facet(self, soup: BeautifulSoup, page_url: str, page_size: int) -> list[str]:
        """The cheapest facet group that covers the category one page at a time.

        A group qualifies when every one of its values holds no more listings
        than a single page shows — otherwise walking it would hit the same wall
        the pagination did. Among those, the one with the fewest values wins,
        because each value is a request.

        On the shop this was written for, "Caliber/Gauge" is 19 values with a
        largest of 19, summing to the whole category; "Manufacturer" would also
        fit but costs 38 requests, and "Action" (largest 60) and "Price"
        (largest 48) do not fit at all.
        """
        best: list[str] = []
        best_score: tuple[int, int] | None = None
        for group in self._facet_groups(soup):
            counts = [count for _href, count in group]
            if not counts or min(counts) <= 0 or max(counts) > page_size:
                continue
            # Most coverage first, then fewest requests to get it.
            score = (sum(counts), -len(counts))
            if best_score is None or score > best_score:
                best_score = score
                best = [urljoin(page_url, href) for href, _count in group]
        return best

    def _facet_groups(self, soup: BeautifulSoup) -> Iterator[list[tuple[str, int]]]:
        """Each facet group as its (path, count) pairs.

        Only paths: a facet rendered as a query string is the thing that was
        disallowed in the first place, so it is no use here.
        """
        for selector in self.facet_nav_selectors:
            nav = soup.select_one(selector)
            if nav is None:
                continue
            for heading in nav.select("dt, .filter-options-title"):
                body = heading.find_next_sibling(("dd", "div"))
                if body is None:
                    continue
                group: list[tuple[str, int]] = []
                for link in body.select("a[href]"):
                    href = str(link.get("href") or "")
                    if not href or "?" in href or href.startswith("#"):
                        continue
                    found = _FACET_COUNT.search(
                        normalize_whitespace(link.get_text(" ", strip=True))
                    )
                    group.append((href, int(found.group(1)) if found else 0))
                if group:
                    yield group
            return

    def next_page(self, soup: BeautifulSoup, current: str) -> str | None:
        for selector in self.next_page_selectors:
            link = soup.select_one(selector)
            href = link.get("href") if isinstance(link, Tag) else None
            if isinstance(href, str) and href.strip():
                found = urljoin(current, href.strip())
                if urlparse(found).netloc == urlparse(current).netloc:
                    return found
        return None

    # -- one card -----------------------------------------------------------
    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        link = self._first_href(card, self.link_selectors, page_url)
        if link is None:
            return None

        title = self._first_text(card, self.title_selectors)
        if not title:
            # A themed grid may put the name only in the photograph's alt text,
            # which is where Classic Firearms keeps it.
            image = card.select_one("img[alt]")
            title = normalize_whitespace(str(image.get("alt"))) if image is not None else ""
        if not title:
            return None

        return ScrapedItem(
            external_key=self._key(card, link),
            url=link,
            title=title,
            price=price_now(card),
            category=category or None,
            image_urls=[
                full_size(urljoin(page_url, url))
                for tag in card.select("img")
                for url in image_sources(tag)[:1]
            ][:1],
            images_are_complete=False,
        )

    def _key(self, card: Tag, link: str) -> str:
        """The shop's own product id where it wrote one, else the URL path.

        Only ``product-item-info_<n>`` counts as the id. That is Magento's own
        wrapper, so a shop either has it on every card or on none — which is
        what a key has to be.

        Taking any ``data-product-id`` instead looked more generous and was
        worse: on Classic Firearms the only element carrying one is a financing
        widget that appears on in-stock products and not on sold-out ones, so a
        rifle selling out would silently change key and read as one listing
        de-listed and a different one arriving.
        """
        for element in (card, *card.select('[id^="product-item-info"]')):
            found = _ITEM_ID.search(str(element.get("id") or ""))
            if found:
                return f"magento-{found.group(1)}"
        return f"path-{urlparse(link).path.strip('/').replace('/', '-')[:180]}"

    # -- the product page ---------------------------------------------------
    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """Fill in what only the product page has.

        Structured data first: where a shop publishes schema.org Product, it is
        both richer and steadier than the markup around it.
        """
        if not ctx.needs_detail(item.external_key):
            return item
        try:
            soup = BeautifulSoup(ctx.get_text(item.url), "html.parser")
        except Disallowed:
            ctx.warn(f"robots.txt disallows {item.url}; keeping the catalog entry only.")
            return item
        except ScrapeError as exc:
            ctx.warn(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item

        node = product_json_ld(soup)
        if node is not None:
            found = self._from_json_ld(item, node)
            if is_prose(found.description):
                return found
            # The structured data's description is not one. On a Page Builder
            # shop that field is Magento's auto-generated meta description,
            # truncated inside the layout's stylesheet, and the real text is in
            # the markup -- so ask the markup, and keep everything else the
            # structured data gave (price, availability, SKU, full-size images),
            # which is not in doubt.
            #
            # No description at all is better than a stylesheet: this is the
            # text a reader is shown and the text the classifier reasons over.
            return replace(
                found,
                description=self._first_text(soup, self.detail_description_selectors) or None,
            )

        images = [full_size(urljoin(item.url, url)) for url in self._gallery(soup)]
        return replace(
            item,
            title=self._first_text(soup, self.detail_title_selectors) or item.title,
            description=self._first_text(soup, self.detail_description_selectors) or None,
            image_urls=images or item.image_urls,
            images_are_complete=bool(images),
        )

    def _from_json_ld(self, item: ScrapedItem, node: dict[str, Any]) -> ScrapedItem:
        offer = offer_of(node)
        raw_images = node.get("image")
        if isinstance(raw_images, str):
            raw_images = [raw_images]
        images = [
            full_size(urljoin(item.url, url))
            for url in (raw_images or [])
            if isinstance(url, str) and url.strip()
        ]
        price = parse_price(str(offer.get("price"))) if offer.get("price") is not None else None
        sku = node.get("sku")

        return replace(
            item,
            title=_plain_text(node.get("name")) or item.title,
            # The description is HTML in this field, so it is flattened the way
            # the detail view and the classifier both want it.
            description=self._as_text(node.get("description")) or item.description,
            # The card's price is the one that is missing on a MAP listing; the
            # offer's is the one the shop publishes.
            price=price if price is not None else item.price,
            is_sold=is_sold_out(node),
            image_urls=images or item.image_urls,
            images_are_complete=bool(images),
            extra={**item.extra, "sku": str(sku) if sku else ""},
        )

    @staticmethod
    def _as_text(value: object) -> str | None:
        """One JSON-LD description, as prose.

        The field is HTML, and on a Page Builder shop that HTML opens with a
        stylesheet -- which ``get_text()`` reads out like any other text.
        :func:`flatten_html` drops it; see ``_NOT_PROSE``.
        """
        if not isinstance(value, str):
            return None
        return flatten_html(value) or None

    def _gallery(self, soup: BeautifulSoup) -> list[str]:
        found: dict[str, str] = {}
        for selector in self.detail_gallery_selectors:
            for tag in soup.select(selector):
                for url in image_sources(tag):
                    found.setdefault(full_size(url), url)
            if found:
                break
        return list(found)

    # -- small helpers ------------------------------------------------------
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
