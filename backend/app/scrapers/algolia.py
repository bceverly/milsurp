"""Shared machinery for shops whose catalog is drawn by Algolia InstantSearch.

The same shape as :mod:`app.scrapers.searchanise`, with a different vendor
behind it: the shop's category page arrives with no products in it, a widget
fills the grid after load, and the widget reads a public search API with a
key the page carries in plain sight. Botach's firearms page is 336 KB and holds
zero BigCommerce cards; the roadmap filed it as "the grid is built in the
browser", which is true, and "so it needs a browser", which is not.

**The key is a search-only key, published to be used.** Algolia issues a
separate key for exactly this -- a browser-side, read-only key that can query
and do nothing else -- and a shop puts it in every page it serves. Reading it
here is reading the same catalog, through the same door, that every visitor's
browser reads.

**GET, not POST.** Algolia's own client POSTs a JSON body, but the REST API
answers the same query as a GET with the credentials and parameters in the
query string. That keeps every request inside :meth:`ScrapeContext.get`, with
its robots check, pacing and retries, rather than beside it. The API host's
robots.txt is a 404 -- no stated rules -- and the walk asks anyway.

**Records are variants, and ``distinct`` folds them.** Each hit is one variant
of a product; the index is configured with ``distinct`` on the product, and the
query asks for it explicitly so a shop that turns it off does not start
arriving as one listing per size and color of the same rifle.

**A hidden product is skipped.** ``is_visible: false`` is a product the shop
has unpublished: its page is a 404, and at Botach it is where placeholder
records live -- eight different police trade-ins all at exactly $1,000. The
query filters on it and :meth:`AlgoliaScraper.item_from_hit` refuses one
anyway, because a record that is not for sale must not be counted as a listing
whatever the facet configuration does.

**The record has no description**, so a subclass that names
:attr:`~AlgoliaScraper.detail_description_selectors` fetches the product page
for it -- once per listing, because :meth:`ScrapeContext.needs_detail` is asked
first.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import replace
from typing import Any
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
    text_of,
    vendors_answer,
)
from .searchanise import full_size

#: Results per request. Algolia allows up to 1,000; a section is far smaller.
PAGE_SIZE = 100


def price_now(hit: dict[str, Any], currency: str = "USD") -> float | None:
    """What the shop is charging today.

    ``calculated_prices`` is the figure after any sale, which is the one this
    application exists to watch; ``prices`` is the list price and
    ``sales_prices`` is 0 on everything not reduced. A zero or a missing
    figure is no price rather than a free rifle.
    """
    block = hit.get("calculated_prices")
    raw = block.get(currency) if isinstance(block, dict) else None
    try:
        value = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    return value if value and value > 0 else None


class AlgoliaScraper(SiteScraper):
    """One Algolia-backed shop. Subclasses supply the credentials and sections."""

    #: From the shop's own page: ``"appId":"…","publicApiKey":"…","indexName":"…"``.
    app_id: str = ""
    api_key: str = ""
    index: str = ""

    #: One entry per section: ``{"category": "Used Guns", "facet": "categories.lvl1:…"}``.
    #: ``facet`` is an Algolia facet filter, exactly as the widget sends it.
    sources: tuple[dict[str, str], ...] = ()

    #: Where the description lives on the product page. Empty means no product
    #: page is ever fetched and listings carry no description.
    detail_description_selectors: tuple[str, ...] = ()

    #: The record's own words for the heading a description begins with, cut
    #: off the front so the prose starts with the prose.
    description_heading: str = "Description"

    min_request_delay: float = 2.0
    max_pages_per_source = 20

    #: Same reasoning as the Searchanise class: a shop that serves its catalog
    #: and refuses its product pages is not walked one refusal at a time.
    MAX_DETAIL_FAILURES = 3

    requires_browser = False

    _detail_failures = 0
    _gave_up_on_details = False

    # -- the scan -----------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if not (self.app_id and self.api_key and self.index):  # pragma: no cover
            raise ScrapeError(f"{self.slug}: no Algolia credentials configured.")
        if self.min_request_delay:
            ctx.keep_at_least(self.api_host, self.min_request_delay)
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._detail_failures = 0
        self._gave_up_on_details = False
        seen: set[str] = set()
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    @property
    def api_host(self) -> str:
        return f"https://{self.app_id}-dsn.algolia.net/"

    def endpoint(self, page: int, facet: str) -> str:
        query = {
            "x-algolia-application-id": self.app_id,
            "x-algolia-api-key": self.api_key,
            "query": "",
            "page": page,
            "hitsPerPage": PAGE_SIZE,
            "distinct": "true",
            "facetFilters": json.dumps([facet, "is_visible:true"]),
        }
        return f"{self.api_host}1/indexes/{self.index}?{urlencode(query)}"

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, str], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        label = source["category"]
        for page in range(self.max_pages_per_source):
            ctx.check_stop()
            url = self.endpoint(page, source["facet"])
            try:
                document = self._page(ctx, url)
            except Disallowed as exc:
                ctx.warn(f"{exc}; stopping this section there.")
                return
            except ScrapeError as exc:
                if page == 0:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {page}.")
                return

            hits = document.get("hits") or []
            if not hits:
                if page == 0:
                    # A facet value that matches nothing answers 200 with an
                    # empty list -- which is also what a renamed section looks
                    # like, so it is said out loud.
                    ctx.warn(f"{label!r} matched nothing; has the shop renamed the section?")
                return

            fresh = 0
            for hit in hits:
                item = self.item_from_hit(hit, label)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                fresh += 1
                yield self.with_detail(ctx, item)
            ctx.log(f"{label} page {page + 1}: {fresh} listing(s).")

            pages = document.get("nbPages")
            if not isinstance(pages, int) or page + 1 >= pages:
                return

    def _page(self, ctx: ScrapeContext, url: str) -> dict[str, Any]:
        raw = ctx.get_text(url)
        try:
            document = json.loads(raw)
        except ValueError as exc:
            raise ScrapeError(f"GET {url}: expected JSON, got something else ({exc})") from exc
        if not isinstance(document, dict):
            raise ScrapeError(f"GET {url}: expected an object, got {type(document).__name__}")
        return document

    # -- one record ---------------------------------------------------------
    def label_for(self, hit: dict[str, Any], label: str) -> str:  # noqa: ARG002 - for overrides
        """The category to file this listing under. The section's, by default."""
        return label

    def item_from_hit(self, hit: dict[str, Any], label: str) -> ScrapedItem | None:
        product_id = hit.get("product_id")
        path = hit.get("url")
        title = normalize_whitespace(str(hit.get("name") or ""))
        if not product_id or not path or not title:
            return None
        if hit.get("is_visible") is False:
            return None

        images: list[str] = []
        if isinstance(hit.get("image_url"), str):
            images.append(hit["image_url"])
        gallery = hit.get("product_images")
        if isinstance(gallery, list):
            # The thumbnail is flagged, and is usually also the main image.
            ordered = sorted(
                (g for g in gallery if isinstance(g, dict)),
                key=lambda g: not g.get("is_thumbnail"),
            )
            images += [full_size(g["url_thumbnail"]) for g in ordered if g.get("url_thumbnail")]

        sku = normalize_whitespace(str(hit.get("sku") or ""))
        return ScrapedItem(
            # Every Algolia shop met so far is a BigCommerce shop, and this is
            # the key app.scrapers.bigcommerce builds from the same product id.
            external_key=f"bc-{product_id}",
            url=urljoin(self.base_url, str(path)),
            title=title,
            price=price_now(hit),
            category=self.label_for(hit, label),
            # The shop's own flag, and the one its product page agrees with:
            # every in_stock false checked was OutOfStock there.
            is_sold=hit.get("in_stock") is False,
            image_urls=images,
            images_are_complete=True,
            extra={"sku": sku} if sku else {},
        )

    # -- the product page ---------------------------------------------------
    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """The description, from the shop's own product page."""
        if not self.detail_description_selectors or self._gave_up_on_details:
            return item
        if not ctx.needs_detail(item.external_key):
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
                    f"taking the rest of this scan from the API only. Last error: {exc}"
                )
            else:
                say = ctx.log if vendors_answer(exc) else ctx.warn
                say(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item

        self._detail_failures = 0
        for selector in self.detail_description_selectors:
            found = soup.select_one(selector)
            text = text_of(found) if found is not None else None
            if text:
                heading = self.description_heading
                if heading and text.startswith(heading):
                    text = text[len(heading) :].strip()
                return replace(item, description=text or None)
        return item
