"""Shared machinery for WooCommerce shops that publish the Store API.

WooCommerce ships a public, read-only JSON API at ``/wp-json/wc/store/v1/`` —
the one its own block-based storefront calls — and where it is switched on it
carries everything :mod:`app.scrapers.woocommerce` reconstructs from markup: a
numeric product id, the name, the price in minor units, the stock state, the
SKU, the categories, the whole gallery at original resolution, and the
description. Same bargain as Shopify's ``products.json``: **no detail fetch at
all**, which is where a scan's time actually goes.

**This is not a replacement for the HTML base class.** Plenty of shops have the
endpoint disabled, and at least one — Collectors Firearms — disallows ``/*?*``
in robots.txt, which rules out an API whose paging is a query string. That is
why :mod:`app.scrapers.shopify` says the Store API was considered and dropped.
It is offered here for the shops where it *is* available, and the walk asks
robots.txt before every request rather than assuming.

It also settles a site the roadmap had filed under "needs a browser". J&G Sales
renders its catalog client-side — sixteen empty ``li.product`` elements and
fifteen dollar signs in 394KB of HTML — and the conclusion drawn from that was
that it needed headless Chrome. It does not. It needed a look at the API the
same WordPress install was already serving.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    flatten_html,
    normalize_whitespace,
)

#: Products per request. The endpoint caps this at 100 and rejects more.
PAGE_SIZE = 100


def html_to_text(markup: str | None) -> str | None:
    """A description as prose.

    ``description`` is a rich-text field and arrives as markup. The classifier
    reads prose and the detail view renders text, so it is flattened once here
    rather than in both.
    """
    return flatten_html(markup) or None


def price_now(product: dict[str, Any]) -> float | None:
    """What the shop is asking, in whole currency units.

    The Store API reports money in *minor units* with the scale alongside it:
    ``{"price": "82995", "currency_minor_unit": 2}`` is $829.95. Reading that
    field as a float without dividing would have filed a $829.95 revolver at
    eighty-two thousand dollars, and it would have looked entirely plausible
    next to the four-figure listings around it.
    """
    prices = product.get("prices")
    if not isinstance(prices, dict):
        return None
    raw = prices.get("price")
    if raw in (None, ""):
        return None
    try:
        scale = int(prices.get("currency_minor_unit", 2))
        return float(float(raw) / (10**scale))
    except (TypeError, ValueError):
        return None


def is_sold(product: dict[str, Any]) -> bool:
    """True when the shop cannot sell it.

    On a dealer of one-off collectible firearms, out of stock means gone. A
    backorder does not: that is a thing they will still take money for.
    """
    if product.get("is_on_backorder"):
        return False
    return product.get("is_in_stock") is False


class WooStoreApiScraper(SiteScraper):
    """One WooCommerce shop, read through its Store API.

    Subclasses supply the slug, the name, and one ``sources`` entry per
    category to read. A category is named by its numeric id because that is
    what the endpoint filters on, and by a label because that is what the
    listing is filed under here.
    """

    #: One entry per category: ``{"category": "Label", "id": 3689}``. The
    #: numeric id comes from ``/wp-json/wc/store/v1/products/categories``.
    sources: tuple[dict[str, Any], ...] = ()

    #: JSON, so there is no markup to be gentle about — but these are small
    #: dealers and a whole scan is a handful of requests, so there is nothing
    #: to be gained by hurrying either.
    min_request_delay: float = 2.0

    #: Bounded for the reason every walk here is bounded: a shop that answers
    #: a page of results forever must not scan forever.
    max_pages_per_source = 40

    requires_browser = False

    # -- the scan -----------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        # Across sections, not within one: WooCommerce categories nest, so a
        # product in "Collector's Corner" is often also in a child of it, and
        # without this the same rifle arrives twice under two labels.
        seen: set[str] = set()
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    def endpoint(self, page: int, category: Any) -> str:
        base = self.base_url.rstrip("/")
        query = f"per_page={PAGE_SIZE}&page={page}&orderby=date&order=desc"
        if category is not None:
            query += f"&category={category}"
        return f"{base}/wp-json/wc/store/v1/products?{query}"

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, Any], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        label = str(source.get("category") or "")
        category = source.get("id")

        for page in range(1, self.max_pages_per_source + 1):
            ctx.check_stop()
            url = self.endpoint(page, category)

            if not ctx.allowed(url):
                # Not a failure. A shop is entitled to disallow query strings,
                # and this whole module depends on one — so say so plainly and
                # stop, rather than failing a scan over a rule we were told.
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                return

            try:
                products = self._products(ctx, url)
            except Disallowed:
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                return
            except ScrapeError as exc:
                # The pages already read are worth keeping. Only the first is
                # fatal, because a section that could not be opened at all
                # yielded nothing, and nothing is not a partial result.
                if page == 1:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {page - 1}.")
                return

            if not products:
                return

            ctx.log(f"{label or 'catalog'} page {page}: {len(products)} listing(s).")
            for product in products:
                item = self.item_from_product(product, label)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield item

            # A short page is the last page. The endpoint reports its totals in
            # response headers, which this fetcher does not surface, so the
            # count is the only signal there is.
            if len(products) < PAGE_SIZE:
                return

    def _products(self, ctx: ScrapeContext, url: str) -> list[dict[str, Any]]:
        """The products on one page, or an empty list past the end."""
        raw = ctx.get_text(url)
        try:
            document = json.loads(raw)
        except ValueError as exc:
            # A shop with the endpoint switched off answers with its HTML error
            # page — or, behind a challenge, with an interstitial. Either is a
            # scrape failure rather than a crash.
            raise ScrapeError(f"GET {url}: expected JSON, got something else ({exc})") from exc
        if isinstance(document, dict):
            # An error body is a dict; a page of products is a list.
            message = document.get("message") or document.get("code")
            raise ScrapeError(f"GET {url}: {message or 'unexpected object'}")
        return document if isinstance(document, list) else []

    # -- one product --------------------------------------------------------
    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        """One listing, complete. There is no second request for this one."""
        product_id = product.get("id")
        url = product.get("permalink")
        title = normalize_whitespace(html_to_text(product.get("name")) or "")
        if product_id is None or not url or not title:
            return None

        return ScrapedItem(
            # The shop's own primary key, which survives a rename. Prefixed so
            # it cannot collide with another platform's numbering if a vendor
            # ever moves house.
            external_key=f"woo-{product_id}",
            url=str(url),
            title=title,
            price=price_now(product),
            description=html_to_text(product.get("description"))
            or html_to_text(product.get("short_description")),
            category=label or self._category_of(product),
            is_sold=is_sold(product),
            image_urls=[
                image["src"]
                for image in product.get("images") or []
                if isinstance(image, dict) and isinstance(image.get("src"), str)
            ],
            # Unlike the HTML base classes this really is the whole gallery:
            # the feed lists every photograph the shop holds for the product.
            images_are_complete=True,
        )

    @staticmethod
    def _category_of(product: dict[str, Any]) -> str | None:
        """The shop's own first category, for a source that named none."""
        for category in product.get("categories") or []:
            name = html_to_text(category.get("name")) if isinstance(category, dict) else None
            if name:
                return name
        return None
