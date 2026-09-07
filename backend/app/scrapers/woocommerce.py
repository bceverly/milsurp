"""Shared machinery for WooCommerce shops.

Ten of the vendors on the roadmap run WooCommerce, and WooCommerce renders its
catalog the same way everywhere: a list of ``li.product`` cards under a
``/product-category/…`` path, paginated with ``/page/N/``, each card carrying
the post id in its class list and the price in a ``.woocommerce-Price-amount``.
A shop's theme changes the wrapper and almost never the loop, so one base class
plus a handful of selector overrides covers the group.

**Why not the Store API.** WooCommerce also publishes
``/wp-json/wc/store/v1/products``, which returns exactly the structured data
this file goes to some trouble to recover from HTML. It is not used, for one
reason: filtering it to a category, or asking for anything past the first ten
products, needs a query string, and the first shop on the list disallows
``/*?*`` in robots.txt. Reading their whole 207,000-product catalog ten at a
time to find the surplus rifles is not a serious alternative to reading the
seventeen category pages that hold them. A shop whose rules permit it can still
override :meth:`scrape` and use the API.

**Pagination is by path, and by the "next" link.** Not by counting: a page
number computed from a total is a guess about a catalog that changes while it
is being read, and following the link the shop itself renders is not.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
)

#: The post id WordPress puts in every card's class list: `post-1398033`. It is
#: the shop's own primary key for the product, which makes it the right thing
#: to build an external key from -- a slug can be edited, a post id cannot.
POST_ID = re.compile(r"\bpost-(\d+)\b")

#: The categories a card belongs to, also from its class list.
PRODUCT_CATEGORY = re.compile(r"\bproduct_cat-([\w-]+)\b")

#: WordPress writes a generated size into the filename: `foo-1024x172.jpg` next
#: to `foo-scaled.jpg`. Stripping it gets back to the one the shop uploaded.
GENERATED_SIZE = re.compile(r"-\d{2,5}x\d{2,5}(?=\.[A-Za-z]{3,4}(?:$|\?))")

#: The other name WordPress gives the same photograph. An upload past the big-
#: image threshold is stored twice: the original as `foo.jpg` and a 2560px
#: version as `foo-scaled.jpg`, and a gallery links to both. They are one
#: picture and must be counted once, or a listing of nine photographs comes
#: back with twelve, three of them duplicates at a different file size.
SCALED = re.compile(r"-scaled(?=\.[A-Za-z]{3,4}(?:$|\?))")

#: A lazy-loading placeholder rather than a photograph.
PLACEHOLDER = re.compile(r"^data:|/(?:placeholder|spacer|blank)[.-]", re.I)

PRICE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]{2})?)")


def full_size(url: str) -> str:
    """The original upload behind a generated thumbnail URL."""
    return GENERATED_SIZE.sub("", url)


def same_photograph(url: str) -> str:
    """What two URLs share when they are the same picture at two sizes."""
    return SCALED.sub("", full_size(url))


def parse_price(text: str) -> float | None:
    match = PRICE.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:  # pragma: no cover - the pattern guarantees digits
        return None


def price_now(card: Tag) -> float | None:
    """The price being asked, which on a sale is not the first one shown.

    WooCommerce renders a sale as ``<del>$600</del> <ins>$450</ins>``. Taking
    the first amount in the block would report the price the shop is no longer
    asking, and — worse for this application — would hide the drop that is the
    whole point of watching.
    """
    block = card.select_one(".price") or card
    sale = block.select_one("ins .woocommerce-Price-amount, ins")
    if sale is not None:
        found = parse_price(sale.get_text(" ", strip=True))
        if found is not None:
            return found
    for amount in block.select(".woocommerce-Price-amount"):
        found = parse_price(amount.get_text(" ", strip=True))
        if found is not None:
            return found
    return parse_price(block.get_text(" ", strip=True))


def image_sources(tag: Tag) -> list[str]:
    """Every image URL an ``<img>`` offers, best first.

    Themes lazy-load, so the ``src`` is often a placeholder and the real URL is
    in ``data-src``, ``data-large_image`` or the largest entry of a ``srcset``.
    """
    found: list[str] = []
    for attribute in ("data-large_image", "data-src", "data-lazy-src", "src"):
        value = tag.get(attribute)
        if isinstance(value, str) and value.strip() and not PLACEHOLDER.match(value.strip()):
            found.append(value.strip())
    for attribute in ("srcset", "data-srcset"):
        value = tag.get(attribute)
        if not isinstance(value, str):
            continue
        widths: list[tuple[int, str]] = []
        for candidate in value.split(","):
            parts = candidate.split()
            if not parts:
                continue
            width = 0
            if len(parts) > 1 and parts[1].endswith("w"):
                with_digits = parts[1][:-1]
                width = int(with_digits) if with_digits.isdigit() else 0
            widths.append((width, parts[0]))
        found.extend(url for _width, url in sorted(widths, reverse=True))
    return found


class WooCommerceScraper(SiteScraper):
    """One WooCommerce shop. Subclasses supply the slug, name and sources."""

    #: Where to start, one entry per category page to walk. ``category`` is the
    #: vendor's own section name, which classification trusts over its own
    #: heuristics, so it should say what the section actually holds.
    sources: tuple[dict[str, str], ...] = ()

    #: How the theme differs from stock WooCommerce. Each is tried in order and
    #: the first that matches wins, so a subclass adds its theme's selector to
    #: the front rather than replacing the list.
    card_selector: str = "li.product, .product.type-product"
    title_selectors: tuple[str, ...] = (
        ".woocommerce-loop-product__title",
        "h2",
        "h3",
        ".product-title",
    )
    link_selectors: tuple[str, ...] = (
        "a.woocommerce-loop-product__link",
        "a[href*='/product/']",
        "a",
    )
    next_page_selectors: tuple[str, ...] = ("a.next.page-numbers", "a.next", ".nav-previous a")

    detail_title_selectors: tuple[str, ...] = ("h1.product_title", "h1.entry-title", "h1")
    detail_description_selectors: tuple[str, ...] = (
        "#tab-description",
        ".woocommerce-Tabs-panel--description",
        ".single-product-description",
        ".woocommerce-product-details__short-description",
    )
    detail_gallery_selectors: tuple[str, ...] = (
        ".woocommerce-product-gallery img",
        ".woocommerce-product-gallery__image img",
        "figure.woocommerce-product-gallery__wrapper img",
    )
    detail_sku_selectors: tuple[str, ...] = (".sku", ".product-sku", ".product_meta .sku")

    #: A pace this shop has been *measured* to need, whatever its robots.txt
    #: says. Zero means "take robots.txt at its word". Only ever slower: this
    #: cannot speed a scan up past a site's own Crawl-delay.
    min_request_delay: float = 0.0

    #: Pages to walk per source before giving up. A guard against a shop whose
    #: "next" link points at itself, not a real limit -- see max_pages in the
    #: scraping config for the one that is.
    max_pages_per_source = 200

    # -- the scan -----------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        if not self.sources:  # pragma: no cover - a subclass bug, not a state
            raise ScrapeError(f"{type(self).__name__} lists no sources to scan.")
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
                # A "next" link that points back into the pages already read.
                break
            visited.add(url)

            if not ctx.allowed(url):
                # Not a failure. Some shops disallow individual pages of a
                # category — collectorsfirearms.com names a dozen of them — and
                # the right response is to stop walking that section, not to
                # fail a scan over a page the shop asked us to skip.
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                return

            soup = BeautifulSoup(ctx.get_text(url), "html.parser")
            pages += 1
            cards = soup.select(self.card_selector)
            ctx.log(f"{category or 'catalog'} page {pages}: {len(cards)} listing(s).")

            for card in cards:
                item = self.item_from_card(card, url, category)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield self.with_detail(ctx, item)

            url = self.next_page(soup, url)

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
        classes = " ".join(card.get("class") or [])
        post = POST_ID.search(classes)
        link = self._first_href(card, self.link_selectors, page_url)
        if post is None or link is None:
            # Not a product card: themes put promotional tiles in the same list.
            return None

        title = self._first_text(card, self.title_selectors)
        if not title:
            return None

        thumbnails = [
            full_size(urljoin(page_url, url))
            for tag in card.select("img")
            for url in image_sources(tag)[:1]
        ]

        return ScrapedItem(
            external_key=f"post-{post.group(1)}",
            url=link,
            title=title,
            price=price_now(card),
            category=category or self._category_of(classes),
            is_sold="outofstock" in classes,
            image_urls=thumbnails[:1],
            # One low-resolution preview, not the gallery. Saying otherwise
            # would let a re-scan of the catalog grid delete the six
            # photographs a detail fetch had already collected.
            images_are_complete=False,
        )

    @staticmethod
    def _category_of(classes: str) -> str | None:
        found = PRODUCT_CATEGORY.search(classes)
        return found.group(1).replace("-", " ").title() if found else None

    def _first_text(self, scope: Tag, selectors: Iterable[str]) -> str:
        for selector in selectors:
            found = scope.select_one(selector)
            if found is not None:
                text = normalize_whitespace(found.get_text(" ", strip=True))
                if text:
                    return text
        return ""

    def _first_href(self, scope: Tag, selectors: Iterable[str], base: str) -> str | None:
        for selector in selectors:
            for found in scope.select(selector):
                href = found.get("href")
                if isinstance(href, str) and href.strip() and not href.startswith("#"):
                    absolute = urljoin(base, href.strip())
                    if "add-to-cart" in absolute:
                        continue
                    return absolute
        return None

    # -- the product page ---------------------------------------------------
    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """Fill in the description and the gallery, if they are still needed.

        The card gives a title, a price and one thumbnail, which is enough to
        notice a price change. Everything else is on the product page, and that
        is one request per listing — so it is fetched once and then skipped on
        every later scan.
        """
        if not ctx.needs_detail(item.external_key):
            return item
        try:
            soup = BeautifulSoup(ctx.get_text(item.url), "html.parser")
        except Disallowed:
            ctx.warn(f"robots.txt disallows {item.url}; keeping the catalog entry only.")
            return item

        description = self._first_text(soup, self.detail_description_selectors)
        images = self.gallery(soup, item.url)
        return replace(
            item,
            title=self._first_text(soup, self.detail_title_selectors) or item.title,
            description=description or item.description,
            image_urls=images or item.image_urls,
            # Only once the gallery has actually been read. A product page that
            # yields nothing is still a partial record.
            images_are_complete=bool(images),
            extra={**item.extra, "sku": self._sku(soup)},
        )

    def gallery(self, soup: BeautifulSoup, base: str) -> list[str]:
        """Every photograph on the product page, de-duplicated, largest first.

        Themes render each image several times over — a thumbnail strip, a
        zoom target, a ``<noscript>`` copy for browsers without JavaScript —
        and WordPress offers each of those at half a dozen generated sizes. All
        of them are the same photograph, so they are reduced to the original
        upload and counted once.
        """
        found: dict[str, str] = {}
        for selector in self.detail_gallery_selectors:
            for tag in soup.select(selector):
                for url in image_sources(tag):
                    absolute = full_size(urljoin(base, url))
                    identity = same_photograph(absolute)
                    # Where the same picture is offered both ways, take the
                    # scaled one: it is the version WordPress itself serves as
                    # full size, and the original behind it can be enormous.
                    if identity not in found or SCALED.search(absolute):
                        found.setdefault(identity, absolute)
            if found:
                break
        return list(found.values())

    def _sku(self, soup: BeautifulSoup) -> str:
        text = self._first_text(soup, self.detail_sku_selectors)
        # "Item Number: L2026-10918" -- the label is part of the element.
        return text.split(":", 1)[-1].strip() if ":" in text else text
