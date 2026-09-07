"""Shared machinery for Shopify shops.

The third storefront platform, and by some distance the cheapest: Shopify
publishes every collection as JSON at ``/collections/<handle>/products.json``,
and that document carries everything the HTML scrapers reconstruct by hand — a
numeric product id, the title, the price, whether it is in stock, the SKU, the
full gallery at original resolution, and the description.

**So there is no detail fetch here at all.** That is the whole point of this
module. Every other base class reads a catalog page for the cheap facts and
then spends one request per listing to get the description and the gallery,
which is where a scan's time actually goes — Checkpoint Charlie's spent
fifty-six minutes on twenty-four listings doing exactly that. A Shopify
collection of two hundred products is one request.

**Two things were checked before writing this, because both have bitten before.**

Pagination is ``?limit=250&page=N``, which needs a query string — and a query
string is precisely what ruled out the WooCommerce Store API, since Collectors
Firearms disallows ``/*?*``. Both shops here allow it, and the walk asks
robots.txt before each page rather than assuming.

The catalog has to be *scoped to a collection*. Centerfire Systems' top-level
``/products.json`` opens with Browning hunting ammunition; unscoped it would
land four hundred AR-15s in a military surplus catalog, which is the mistake
already made once with Arms Unlimited and again with Legacy Collectibles'
"Modern" sections.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
)

#: Shopify's own cap. Asking for more is not an error; it just returns 250.
PAGE_SIZE = 250

#: Shopify serves every upload through its CDN with the requested size in the
#: query string. Stripping it asks for the original the shop uploaded, which is
#: what the image store wants — it makes its own thumbnails.
_SIZE_PARAMS = ("width", "height", "crop")


def original_image(src: str) -> str:
    """The full-resolution image behind a Shopify CDN URL.

    The ``?v=`` cache-buster is *kept*. It is part of how the shop identifies
    that version of the photograph, and dropping it would make a re-uploaded
    image look like the same file to anything keying on the URL.
    """
    if "?" not in src:
        return src
    base, _, query = src.partition("?")
    kept = [
        pair for pair in query.split("&") if pair and pair.split("=")[0].lower() not in _SIZE_PARAMS
    ]
    return f"{base}?{'&'.join(kept)}" if kept else base


def html_to_text(body_html: str | None) -> str | None:
    """A product description as prose.

    ``body_html`` is a rich-text field, so it arrives as markup — paragraphs,
    bold, the occasional table. The classifier reads prose, and the detail page
    renders text, so it is flattened once here rather than in both.
    """
    if not body_html:
        return None
    text = normalize_whitespace(BeautifulSoup(body_html, "html.parser").get_text(" ", strip=True))
    return text or None


def price_now(product: dict[str, Any]) -> float | None:
    """What the shop is asking.

    A firearm is one variant — "Default Title" — but ammunition and accessories
    come in several, so this takes the cheapest, which is the number a shop
    shows as "from $X". An unavailable variant still carries its price and is
    still worth reporting: a sold listing with no price reads as "call for
    price", which is a different thing from "sold".
    """
    prices = []
    for variant in product.get("variants") or []:
        try:
            prices.append(float(variant["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return min(prices) if prices else None


def is_sold_out(product: dict[str, Any]) -> bool:
    """True when no variant can be bought.

    A product with no variants at all is not treated as sold: that is a shape
    this code has not seen, and guessing "sold" about it would quietly retire a
    live listing.
    """
    variants = product.get("variants") or []
    return bool(variants) and not any(variant.get("available") for variant in variants)


class ShopifyScraper(SiteScraper):
    """One Shopify shop. Subclasses supply the slug, name and collections."""

    #: One entry per collection to read. ``url`` is the collection page, not the
    #: JSON endpoint — the ``.json`` is appended here so the roadmap and the
    #: subclass both name a URL a person can open in a browser.
    sources: tuple[dict[str, str], ...] = ()

    #: JSON, so there is no markup to be gentle about — but these are still
    #: small dealers and the whole scan is a handful of requests, so there is
    #: nothing to gain by hurrying it either.
    min_request_delay: float = 2.0

    #: Bounded for the same reason every other walk is: a shop that answers a
    #: page of results forever should not scan forever.
    max_pages_per_source = 40

    requires_browser = False

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
        collection = source["url"].rstrip("/")

        for page in range(1, self.max_pages_per_source + 1):
            ctx.check_stop()
            url = f"{collection}/products.json?limit={PAGE_SIZE}&page={page}"

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
                # The pages already read are worth keeping; only the first is
                # fatal, because a collection that could not be opened at all
                # yielded nothing and nothing is not a partial result.
                if page == 1:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {page - 1}.")
                return

            if not products:
                return

            ctx.log(f"{category or 'catalog'} page {page}: {len(products)} listing(s).")
            for product in products:
                item = self.item_from_product(product, collection, category)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield item

            # A short page is the last page. Shopify has no "next" link in this
            # document, so the count is the only signal there is.
            if len(products) < PAGE_SIZE:
                return

    def _products(self, ctx: ScrapeContext, url: str) -> list[dict[str, Any]]:
        """The products on one page, or an empty list at the end of a collection."""
        raw = ctx.get_text(url)
        try:
            document = json.loads(raw)
        except ValueError as exc:
            # A shop that has turned the endpoint off answers with its HTML
            # error page, which is a scrape failure rather than a crash.
            raise ScrapeError(f"GET {url}: expected JSON, got something else ({exc})") from exc
        products = document.get("products") if isinstance(document, dict) else None
        return products if isinstance(products, list) else []

    # -- one product --------------------------------------------------------
    def item_from_product(
        self, product: dict[str, Any], collection: str, category: str
    ) -> ScrapedItem | None:
        """One listing, complete. There is no second request for this one."""
        product_id = product.get("id")
        handle = product.get("handle")
        title = normalize_whitespace(product.get("title") or "")
        if product_id is None or not handle or not title:
            return None

        return ScrapedItem(
            # The shop's own primary key, which survives a rename. Prefixed so
            # it cannot collide with another platform's numbering if a vendor
            # ever moves house.
            external_key=f"shopify-{product_id}",
            url=urljoin(f"{collection}/", f"../../products/{handle}"),
            title=title,
            price=price_now(product),
            description=html_to_text(product.get("body_html")),
            category=category or None,
            is_sold=is_sold_out(product),
            image_urls=[
                original_image(image["src"])
                for image in sorted(
                    product.get("images") or [], key=lambda i: i.get("position") or 0
                )
                if isinstance(image.get("src"), str)
            ],
            # Unlike every other base class, this really is the whole gallery:
            # the feed lists every photograph the shop has.
            images_are_complete=True,
            extra={"sku": self._sku(product), "vendor": product.get("vendor") or ""},
        )

    @staticmethod
    def _sku(product: dict[str, Any]) -> str:
        for variant in product.get("variants") or []:
            sku = variant.get("sku")
            if isinstance(sku, str) and sku.strip():
                return sku.strip()
        return ""
