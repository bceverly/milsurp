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

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ..services import cooldown
from .base import (
    Disallowed,
    HostResting,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    text_of,
    vendors_answer,
)
from .storefront import background_images, image_sources, parse_price

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


def full_size(url: str) -> str:
    """The original upload behind a generated thumbnail URL."""
    return GENERATED_SIZE.sub("", url)


def same_photograph(url: str) -> str:
    """What two URLs share when they are the same picture at two sizes."""
    return SCALED.sub("", full_size(url))


def price_now(card: Tag) -> float | None:
    """The price being asked, which on a sale is not the first one shown.

    WooCommerce renders a sale as ``<del>$600</del> <ins>$450</ins>``. Taking
    the first amount in the block would report the price the shop is no longer
    asking, and — worse for this application — would hide the drop that is the
    whole point of watching.
    """
    block = card.select_one(".price")
    if block is None and not card.select_one(".woocommerce-Price-amount"):
        # No price element at all. Reading a number out of the card's text
        # here invents one: a category tile reading "AK Style Shotguns In 12
        # Gauge" became a twelve-dollar listing.
        return None

    scope = block or card
    sale = scope.select_one("ins .woocommerce-Price-amount, ins")
    if sale is not None:
        found = parse_price(sale.get_text(" ", strip=True))
        if found is not None:
            return found
    for amount in scope.select(".woocommerce-Price-amount"):
        found = parse_price(amount.get_text(" ", strip=True))
        if found is not None:
            return found
    return parse_price(scope.get_text(" ", strip=True))


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
    #: says. Only ever slower: this cannot speed a scan up past a site's own
    #: Crawl-delay.
    #:
    #: Five seconds by default, rather than the application-wide one second.
    #: These are small dealers on shared hosting behind a WAF, and one request
    #: a second is enough to be refused: Checkpoint Charlie's returned 429 part
    #: way through a twelve-listing catalog. Collectors Firearms went further
    #: and refused the ten seconds its own robots.txt asks for, which is why it
    #: overrides this again.
    #:
    #: The cost is wall clock and nothing else. A scan is a few hundred
    #: requests of a few kilobytes, it runs once a day, and the detail pages
    #: are fetched once per listing ever — so a slower first pass is paid once.
    min_request_delay: float = 5.0

    #: Pages to walk per source before giving up. A guard against a shop whose
    #: "next" link points at itself, not a real limit -- see max_pages in the
    #: scraping config for the one that is.
    max_pages_per_source = 200

    # -- the scan -----------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        if not self.sources:  # pragma: no cover - a subclass bug, not a state
            raise ScrapeError(f"{type(self).__name__} lists no sources to scan.")
        return self._stream(ctx)

    #: Give up on product pages after this many in a row fail.
    #:
    #: Some shops serve their catalog happily and refuse every product page.
    #: Checkpoint Charlie's was the example this was built for and is no longer
    #: one -- their refusal turned out to be a user-agent blocklist at their
    #: CDN, not a policy about product pages. The limit stays because the shape
    #: is real: without it, a scan works patiently through a whole catalog
    #: discovering the same refusal one listing at a time.
    MAX_DETAIL_FAILURES = 3

    #: How many product pages have failed since the last one that worked, and
    #: whether the run has stopped asking. Reset at the top of every scan.
    _detail_failures = 0
    _gave_up_on_details = False

    #: Sections skipped this run because the host is in a cooldown. Counted so
    #: a run that asked for nothing at all can say so rather than reporting an
    #: empty shop.
    _sections_resting = 0

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._detail_failures = 0
        self._gave_up_on_details = False
        self._sections_resting = 0
        seen: set[str] = set()
        opened = 0
        for source in self.sources:
            before = len(seen)
            yield from self._walk(ctx, source, seen)
            if len(seen) > before:
                opened += 1

        # Every section skipped because *we* are resting is not a scan that
        # found an empty shop -- it is a scan that never asked. Each one has
        # already been marked not_read, so nothing is de-listed either way;
        # this is about whether the run reports success.
        #
        # Loud only when nothing at all was read. One section resting out of
        # thirteen is a partial result worth keeping, and the warnings say so.
        #
        # **HostResting, not ScrapeError**, and that one word is the whole
        # difference between the two things this can mean. Both the canary and
        # the scan service already know what to do with a host that is resting
        # -- report it as resting rather than broken, and come back when the
        # pause lifts instead of a day later. Raising the base class threw both
        # of those away and reported the shop broken, which is how Checkpoint
        # Charlie's came to be on the canary every morning while the register
        # was quietly doing exactly what it was built to do.
        if opened == 0 and self._sections_resting:
            remaining = cooldown.paused_for(self.base_url)
            raise HostResting(
                self.base_url,
                remaining,
                detail=(
                    f"Every section was skipped: this host is in a cooldown from an "
                    f"earlier refusal, with {self._sections_resting} section(s) not "
                    f"asked and {remaining:.0f}s still to wait. Nothing was read and "
                    f"nothing was de-listed."
                ),
            )

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
                # Only the *whole* section counts as unread. Stopping at page
                # four has still read pages one to three, and the listings on
                # them were genuinely observed.
                if pages == 0:
                    ctx.not_read(category)
                return

            try:
                soup = BeautifulSoup(ctx.get_text(url), "html.parser")
            except HostResting as exc:
                # Our own decision, not this vendor's refusal of this page.
                #
                # The cooldown register is keyed by *host*, and the evidence
                # that fills it is often path-specific: a shop whose catalog
                # answers 200 and whose product pages refuse publishes a
                # host-wide pause, and then the next section's first page
                # arrives here. Treating that as the vendor refusing a catalog
                # page is a category error, and an expensive one -- it is how
                # Checkpoint Charlie's produced nine failed scans against one
                # partial while the detail-page fallback below worked exactly
                # as designed.
                #
                # So it behaves like the robots.txt case above, which is the
                # same shape of thing: somebody said do not ask, we are not
                # asking, and the section is a gap rather than a failure.
                ctx.warn(f"Not asking {url}: {exc}")
                self._sections_resting += 1
                if pages == 0:
                    ctx.not_read(category)
                return
            except ScrapeError as exc:
                # The same argument as a refused product page, one level up.
                # Two pages read and the third refused is two pages of listings
                # worth keeping, not a scan worth throwing away — which is
                # exactly what Checkpoint Charlie's cost before this existed:
                # 56 minutes, 24 listings walked, and a run that reported zero
                # because page 3 answered 429.
                #
                # The first page is the exception. A section that could not be
                # opened at all yielded nothing, and nothing is not a partial
                # result — it is a failure, and it should be loud.
                if pages == 0:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {pages}.")
                return
            pages += 1
            cards = soup.select(self.card_selector)
            ctx.log(f"{category or 'catalog'} page {pages}: {len(cards)} listing(s).")

            found: list[ScrapedItem] = []
            for card in cards:
                item = self.item_from_card(card, url, category)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                found.append(item)

            yield from self._detailed(ctx, found)

            url = self.next_page(soup, url)

    def _detailed(self, ctx: ScrapeContext, items: list[ScrapedItem]) -> Iterator[ScrapedItem]:
        """One page of cards, filled in.

        Where the shop offers the Store API, the whole page's descriptions and
        galleries arrive in a single request. The other path is not an error
        path: anything the batch did not answer for is asked for the old way,
        one product page at a time, which is also what every shop without the
        flag does for all of them.
        """
        records = (
            self._store_api_records(ctx, items)
            if self.store_api_details and not self._gave_up_on_details
            else {}
        )
        for item in items:
            record = records.get(item.external_key)
            if record is not None and ctx.needs_detail(item.external_key):
                yield self._from_store_api(item, record)
            else:
                yield self.with_detail(ctx, item)

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
        if not thumbnails:
            # A page builder can place the picture as a CSS background on a
            # link or a div, leaving no <img> in the card at all. CO Gun Sales'
            # grid is built this way throughout.
            thumbnails = [
                full_size(urljoin(page_url, url))
                for tag in card.select("[style*=background]")
                for url in background_images(tag)[:1]
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
                text = text_of(found)
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
    #: Read the descriptions and galleries from WooCommerce's Store API instead
    #: of from each product page.
    #:
    #: Off by default and turned on per vendor, because it has only been
    #: measured against the shops it is enabled for. Where it is on it is
    #: better on both counts that matter:
    #:
    #: * **Fewer requests.** The card already carries the product id -- it is
    #:   the `post-N` class the external key is built from -- so a page of
    #:   cards resolves in *one* request via `?include=`, against one per
    #:   listing before.
    #: * **More of the description.** Measured on Checkpoint Charlie's, the API
    #:   returned 395, 373 and 363 characters where scraping the same three
    #:   product pages returned 37, 158 and 26. The prose a shop writes lives in
    #:   WooCommerce's *short* description, and the themes render only part of
    #:   it above the fold. Galleries matched exactly: 13, 14 and 16 images
    #:   either way.
    store_api_details: bool = False

    #: Where the Store API lives, relative to the site root. Standard across
    #: every WooCommerce since blocks shipped, and a setting only so a shop
    #: that has moved it is a one-line subclass rather than a fork.
    store_api_path: str = "wp-json/wc/store/v1/products"

    #: Ids per `?include=` request. The endpoint's own page size is 100.
    STORE_API_BATCH = 100

    def _store_api_records(
        self, ctx: ScrapeContext, items: list[ScrapedItem]
    ) -> dict[str, dict[str, Any]]:
        """Fetch the Store API rows for whichever of *items* still need detail.

        Keyed by external key, so the caller does not have to know that the key
        is the product id wearing a prefix.

        Never raises. A failure here costs the page its descriptions and
        galleries and nothing else: the caller falls back to asking for the
        product pages one at a time, which is what it did before this existed.
        """
        wanted = {
            item.external_key: item.external_key.removeprefix("post-")
            for item in items
            if item.external_key.startswith("post-") and ctx.needs_detail(item.external_key)
        }
        if not wanted:
            return {}

        found: dict[str, dict[str, Any]] = {}
        ids = list(wanted.values())
        for start in range(0, len(ids), self.STORE_API_BATCH):
            batch = ids[start : start + self.STORE_API_BATCH]
            url = (
                f"{self.base_url}{self.store_api_path}"
                f"?include={','.join(batch)}&per_page={len(batch)}"
            )
            try:
                records = json.loads(ctx.get_text(url))
            except (ScrapeError, ValueError) as exc:
                ctx.log(f"Store API unavailable ({exc}); reading product pages instead.")
                return found
            if not isinstance(records, list):
                return found
            for record in records:
                key = f"post-{record.get('id')}"
                found[key] = record
        return found

    def _from_store_api(self, item: ScrapedItem, record: dict[str, Any]) -> ScrapedItem:
        """One Store API row onto one listing, in the shape with_detail makes.

        The *short* description is the prose a shop writes; the long one is
        almost always boilerplate -- "FFL TRANSFER REQUIRED" and nothing else.
        Taking the longer of the two rather than assuming either way, because
        a shop that puts real text in the other field should not be punished
        for it.
        """
        descriptions = [
            text_of(BeautifulSoup(record.get(field) or "", "html.parser"))
            for field in ("short_description", "description")
        ]
        description = max(descriptions, key=len)
        images = [
            full_size(str(image.get("src")))
            for image in record.get("images") or []
            if image.get("src")
        ]
        return replace(
            item,
            title=str(record.get("name") or "") or item.title,
            description=description or item.description,
            image_urls=images or item.image_urls,
            images_are_complete=bool(images),
            extra={**item.extra, "sku": str(record.get("sku") or "")},
        )

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """Fill in the description and the gallery, if they are still needed.

        The card gives a title, a price and one thumbnail, which is enough to
        notice a price change. Everything else is on the product page, and that
        is one request per listing — so it is fetched once and then skipped on
        every later scan.
        """
        if not ctx.needs_detail(item.external_key) or self._gave_up_on_details:
            return item
        try:
            soup = BeautifulSoup(ctx.get_text(item.url), "html.parser")
        except Disallowed:
            ctx.warn(f"robots.txt disallows {item.url}; keeping the catalog entry only.")
            return item
        except ScrapeError as exc:
            # A product page that cannot be fetched costs this listing its
            # description and gallery. It does not cost the scan: the catalog
            # entry already carries the title, the price and a thumbnail, which
            # is what price watching actually needs.
            #
            # Checkpoint Charlie's is why this exists: their category pages
            # answered 200 while their product pages answered 429, so the old
            # behavior spent an hour backing off and then threw away a
            # perfectly good catalog read. That particular refusal turned out
            # to be a user-agent blocklist and is fixed, but a shop that serves
            # a catalog and refuses detail pages is a real shape and this is
            # still the right answer to it.
            #
            # A shop that refuses every product page would otherwise have its
            # whole catalog walked one pointless request at a time, so after
            # MAX_DETAIL_FAILURES in a row the run stops asking.
            #
            # ctx.warn() downgrades the run to PARTIAL, so none of this is
            # silent.
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
        return list(found.values()) or self._gallery_from_json(soup, base)

    #: Gallery plugins that ship the photographs as JSON on the container
    #: rather than as ``<img>`` elements, and the key each one puts the
    #: original upload under.
    #:
    #: CO Gun Sales runs one of these. Their product pages carry nine
    #: photographs apiece and not one ``<img>`` among them — the markup has a
    #: ``woocommerce-product-gallery`` div whose ``data-wcsvi`` attribute holds
    #: the lot, and the browser builds the gallery from it. Parsed here because
    #: the alternative is a headless browser for a shop that is otherwise
    #: entirely static.
    json_gallery_attributes: tuple[str, ...] = ("data-wcsvi",)

    def _gallery_from_json(self, soup: BeautifulSoup, base: str) -> list[str]:
        """Photographs from a gallery that is JSON in an attribute."""
        found: dict[str, str] = {}
        for attribute in self.json_gallery_attributes:
            for tag in soup.select(f"[{attribute}]"):
                raw = tag.get(attribute)
                if not isinstance(raw, str):
                    continue
                try:
                    data = json.loads(raw)
                except ValueError:
                    # Someone else's attribute that happens to share the name,
                    # or markup we have not seen. Not worth failing a scan for.
                    continue
                for entry in data.get("images", []) if isinstance(data, dict) else []:
                    if not isinstance(entry, dict):
                        continue
                    # large_image is the original upload; src is the same
                    # photograph behind an image CDN, with the resize in a
                    # query string.
                    url = entry.get("large_image") or entry.get("src")
                    if isinstance(url, str) and url.strip():
                        absolute = full_size(urljoin(base, url.strip()))
                        found.setdefault(same_photograph(absolute), absolute)
            if found:
                break
        return list(found.values())

    def _sku(self, soup: BeautifulSoup) -> str:
        text = self._first_text(soup, self.detail_sku_selectors)
        # "Item Number: L2026-10918" -- the label is part of the element.
        return text.split(":", 1)[-1].strip() if ":" in text else text
