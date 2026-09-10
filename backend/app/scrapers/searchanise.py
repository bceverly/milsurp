"""Shared machinery for shops whose catalog is rendered by Searchanise.

Searchanise is a hosted search and merchandising add-on. A store that installs
it stops rendering its own category pages: the grid arrives as an empty shell
and a widget fills it in from ``searchserverapi.com``. That is why SARCO's
rifles page is 236KB with zero product cards and zero prices in it, and why the
roadmap had it filed under "needs a browser".

It does not need a browser. The widget calls a public, unauthenticated JSON
endpoint with a key the page carries in plain sight, and that endpoint answers
with the whole catalog: id, title, URL, price, SKU and the full-resolution
gallery. SARCO's 509 firearms arrive in nine requests, sections and exclusions
included.

**Two things were checked before writing this**, because the equivalent
assumptions have been wrong before:

The API lives on a *different host* from the shop, so it is that host's
robots.txt that governs the request. ``searchserverapi.com`` publishes
``User-agent: * / Disallow:`` -- an empty Disallow, which allows everything.
The walk asks anyway, before each page.

And the shop's own robots.txt matters for what it says about ``/search.php``,
which SARCO disallows. This does not touch it: the endpoint is not the shop's
search page, and no request here goes to a disallowed path.

**What the API will not give you is the description.** Searchanise indexes the
first 200 characters and stops -- 508 of SARCO's 509 firearms come back ending
in an ellipsis, mid-sentence. That is the half of a listing this application
reads most closely: the caliber, the condition, the import marks, everything
the classifier and the armory work from. So a subclass that names
:attr:`~SearchaniseScraper.detail_description_selectors` fetches the product
page for the real one. That is affordable because
:meth:`ScrapeContext.needs_detail` is asked first, so it happens once per
listing ever, not once per listing per scan.

**The category filter cannot carry a pipe.** ``restrictBy[categories]`` treats
``|`` as its own separator, so a BigCommerce category named "Rifles | Military
Surplus Guns" cannot be asked for: the full name matches nothing, and so does
either half on its own -- both were tried. It does not error. It answers 200
with an empty list, which is indistinguishable from an empty shop, so the walk
warns when a section's first page is empty.

**Section order decides classification.** A listing is taken by the first
section that offers it, and that section's name becomes the ``category`` the
classifier trusts over its own reading of the title. Put the specific sections
first and the catch-all last -- see :attr:`SearchaniseScraper.sources`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    flatten_html,
    normalize_whitespace,
    text_of,
    vendors_answer,
)

#: Where every Searchanise store is served from, whatever the shop's own domain.
API = "https://searchserverapi.com/getresults"

#: Results per request. The endpoint accepts more but answers more slowly, and
#: a firearms section is a few hundred items at most.
PAGE_SIZE = 250

#: The size a BigCommerce CDN URL asks for, written into the *filename* rather
#: than the path: ``…/gun012a__51865.1755106068.386.513.jpg?c=2``. Searchanise
#: hands out the 386x513 thumbnail -- 30KB against the original's 224KB -- so
#: the two numbers are rewritten. This is not the ``/images/stencil/500x659/``
#: form that :func:`app.scrapers.bigcommerce.full_size` handles; the same CDN
#: serves both shapes and only this one comes through the API.
CDN_SIZE = re.compile(r"\.(\d+)\.(\d+)(\.[a-z]{3,4})(\?|$)", re.I)

#: What to ask for instead. A size the CDN actually has -- "original" and a
#: bare extension both 404 on this URL shape.
#:
#: Some galleries already end with a 1280 copy of their own first photograph,
#: which after the rewrite is character-for-character the URL the first entry
#: became. ScrapedItem de-duplicates image URLs, so that lands as one image.
FULL_SIZE = "1280.1280"


def full_size(url: str) -> str:
    """The full-resolution photograph behind a Searchanise thumbnail URL."""
    return CDN_SIZE.sub(rf".{FULL_SIZE}\g<3>\g<4>", url, count=1)


def html_to_text(markup: str | None) -> str | None:
    """A description as prose. The field may carry markup; readers want text."""
    return flatten_html(markup) or None


def price_now(product: dict[str, Any]) -> float | None:
    """What the shop is asking, which on a sale is not the list price.

    ``price`` is already the live figure: on a reduced item it equals
    ``sale_price`` and ``list_price`` holds what it was. Reading ``list_price``
    would quietly hide every discount -- which is the one event this
    application exists to notice -- and reading ``sale_price`` would report
    nothing at all for the 90% of the catalog that is not on sale, where it is
    the string ``"0"``.
    """
    raw = product.get("price")
    if raw in (None, "", "0", 0):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


class SearchaniseScraper(SiteScraper):
    """One Searchanise-backed shop. Subclasses supply the key and the sections."""

    #: The shop's Searchanise key, which its own pages carry in the widget
    #: script tag: ``…/init.js?api_key=XXXXXXXXXX``.
    api_key: str = ""

    #: One entry per category to read: ``{"category": "Shop All Firearms"}``,
    #: optionally with a ``"label"`` to file the listings under instead. The
    #: category must not contain a pipe -- see the module docstring.
    #:
    #: **Order is load-bearing here in a way it is not elsewhere.** A listing is
    #: taken by the first section that offers it, and its section name becomes
    #: the ``category`` the classifier trusts over its own reading of the
    #: title. So the specific sections go first and the catch-all last: naming
    #: SARCO's "Pistols" section rather than letting its 283 handguns arrive
    #: under "Shop All Firearms" is the difference between 200 of them being
    #: recognized as handguns and 281.
    sources: tuple[dict[str, str], ...] = ()

    #: Categories whose products are not wanted at all, read first and skipped
    #: everywhere. For a shop whose "firearms" tree includes bare frames and
    #: stripped receivers: those are components, and the standing rule here is
    #: that the only non-firearm category worth ingesting is a parts *kit*.
    #:
    #: Suppression rather than filtering, because the exclusion has to outrank
    #: the section that would otherwise claim the listing -- fifteen of SARCO's
    #: fifty frames are also filed under "Pistols".
    exclude_categories: tuple[str, ...] = ()

    #: Where the real description lives on the shop's own product page. Empty
    #: means the truncated one from the API is all this shop gets, and no
    #: product page is ever fetched.
    detail_description_selectors: tuple[str, ...] = ()

    #: A third party's API rather than the shop's own server, but the same
    #: courtesy applies -- and the product pages, when they are fetched, do go
    #: to the shop.
    min_request_delay: float = 2.0

    #: Bounded for the reason every walk here is bounded: a shop that answers
    #: a page of results forever must not scan forever.
    max_pages_per_source = 40

    #: Give up on product pages after this many in a row fail, so a shop that
    #: serves its catalog and refuses its details does not get walked one
    #: pointless request at a time. Same reasoning as the storefront classes.
    MAX_DETAIL_FAILURES = 3

    requires_browser = False

    _detail_failures = 0
    _gave_up_on_details = False

    # -- the scan -----------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if not self.api_key:  # pragma: no cover - a subclass that forgot
            raise ScrapeError(f"{self.slug}: no Searchanise api_key configured.")
        if self.min_request_delay:
            ctx.keep_at_least(API, self.min_request_delay)
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._detail_failures = 0
        self._gave_up_on_details = False
        # Across sections. A shop's "new arrivals" is a slice of its main
        # catalog rather than a separate one, so without this the same rifle
        # arrives twice under two labels. Pre-loaded with everything that is
        # not wanted, which is why the exclusion needs no second test in the
        # loop and cannot be undone by a section that also lists the product.
        seen: set[str] = self._excluded(ctx)
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    def _excluded(self, ctx: ScrapeContext) -> set[str]:
        """Every key in :attr:`exclude_categories`, read before anything else."""
        keys: set[str] = set()
        for category in self.exclude_categories:
            try:
                found = self._keys_in(ctx, category)
            except (Disallowed, ScrapeError) as exc:
                # Not fatal. Failing here means some components come through
                # and get filed as accessories, which is untidy; failing the
                # scan over it would cost the whole catalog, which is worse.
                ctx.warn(
                    f"Could not read the {category!r} section to skip it ({exc}); "
                    "its products will be scanned like any other."
                )
                continue
            ctx.log(f"Skipping {len(found)} listing(s) in {category!r}.")
            keys |= found
        return keys

    def _keys_in(self, ctx: ScrapeContext, category: str) -> set[str]:
        keys: set[str] = set()
        for page in range(self.max_pages_per_source):
            ctx.check_stop()
            url = self.endpoint(page * PAGE_SIZE, category)
            products = self._page(ctx, url).get("items") or []
            keys |= {self.key_for(p) for p in products if p.get("product_id")}
            if len(products) < PAGE_SIZE:
                break
        return keys

    def endpoint(self, start: int, category: str) -> str:
        query = {
            "api_key": self.api_key,
            "q": "",
            "maxResults": PAGE_SIZE,
            "startIndex": start,
            "items": "true",
            "output": "json",
        }
        if category:
            query["restrictBy[categories]"] = category
        return f"{API}?{urlencode(query)}"

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, str], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        category = source.get("category") or ""
        label = source.get("label") or category

        for page in range(self.max_pages_per_source):
            ctx.check_stop()
            url = self.endpoint(page * PAGE_SIZE, category)

            try:
                document = self._page(ctx, url)
            except Disallowed as exc:
                # Its own wording, not ours. The two reasons a fetch is refused
                # read very differently -- a rule that forbids this, or a
                # robots.txt we could not read at all -- and inventing the
                # message here is how a scan came to report "robots.txt
                # disallows" about a file that had never been fetched.
                ctx.warn(f"{exc}; stopping this section there.")
                return
            except ScrapeError as exc:
                # The pages already read are worth keeping. Only the first is
                # fatal, because a section that could not be opened at all
                # yielded nothing, and nothing is not a partial result.
                if page == 0:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {page}.")
                return

            products = document.get("items") or []
            if not products:
                if page == 0:
                    # Zero results for a category asked for by name is almost
                    # always the pipe problem, and it is otherwise silent: the
                    # endpoint answers 200 with an empty list and no error.
                    ctx.warn(
                        f"{label or 'catalog'!r} matched nothing. If its name contains a '|', "
                        "Searchanise splits on it -- name a category without one."
                    )
                return

            ctx.log(f"{label or 'catalog'}: {len(products)} listing(s) from {page * PAGE_SIZE}.")
            for product in products:
                item = self.item_from_product(product, label)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield self.with_detail(ctx, item)

            # A short page is the last page.
            if len(products) < PAGE_SIZE:
                return

    def _page(self, ctx: ScrapeContext, url: str) -> dict[str, Any]:
        raw = ctx.get_text(url)
        try:
            document = json.loads(raw)
        except ValueError as exc:
            # A wrong key, or a shop that has dropped the add-on, answers with
            # something that is not JSON. That is a scrape failure, not a crash.
            raise ScrapeError(f"GET {url}: expected JSON, got something else ({exc})") from exc
        if not isinstance(document, dict):
            raise ScrapeError(f"GET {url}: expected an object, got {type(document).__name__}")
        return document

    # -- one product --------------------------------------------------------
    def key_for(self, product: dict[str, Any]) -> str:
        """This listing's stable identity.

        ``bc-`` and the shop's own product id, which is exactly the key
        :mod:`app.scrapers.bigcommerce` builds from ``data-entity-id``. Every
        Searchanise shop met so far is a BigCommerce shop -- the widget is a
        BigCommerce app -- so the numbering is the same one, and a store that
        went back to rendering its catalog server-side could move to that class
        without its listings arriving as a duplicate catalog.
        """
        return f"bc-{product['product_id']}"

    def product_url(self, url: str) -> str:
        """The URL to store and to fetch, for a shop whose feed is not canonical.

        Searchanise repeats whatever the shop indexed, which is not always the
        host the shop actually serves. SARCO's links are all bare
        ``sarcoinc.com`` and every one of them 301s to ``www``; left alone that
        is a wasted redirect on every product page and a stored link that does
        not match the site's own. Subclasses fix it here.
        """
        return url

    def item_from_product(self, product: dict[str, Any], label: str) -> ScrapedItem | None:
        product_id = product.get("product_id")
        url = product.get("link")
        title = normalize_whitespace(html_to_text(product.get("title")) or "")
        if not product_id or not url or not title:
            return None

        gallery = product.get("bigcommerce_images")
        images = (
            [src for src in gallery if isinstance(src, str)] if isinstance(gallery, list) else []
        )
        if not images and isinstance(product.get("image_link"), str):
            images = [product["image_link"]]

        sku = normalize_whitespace(str(product.get("product_code") or ""))

        return ScrapedItem(
            external_key=self.key_for(product),
            url=self.product_url(str(url)),
            title=title,
            price=price_now(product),
            description=html_to_text(product.get("description")),
            category=label or None,
            # Not inferred, deliberately. Neither stock field means what it
            # looks like: `quantity` is 0 on live, purchasable pistols (157 of
            # SARCO's 509, alongside a present Add to Cart), and
            # `inventory_level` is an empty string on 151 of them and was never
            # once observed as zero. Searchanise drops a sold item from its
            # results instead, and the scan's own de-listing handles a listing
            # that stops arriving -- which is the signal that is actually
            # there.
            is_sold=False,
            image_urls=[full_size(src) for src in images],
            # The API lists every photograph the shop holds, not the one
            # thumbnail a catalog grid would show.
            images_are_complete=True,
            extra={"sku": sku} if sku else {},
        )

    # -- the product page ---------------------------------------------------
    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """Replace the API's truncated description with the shop's own.

        Only for a listing that has not been described before, and only for a
        subclass that says where to look. Everything else on the item already
        came through complete.
        """
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
            # A product page that cannot be read costs this listing the tail of
            # its description. It does not cost the scan: the title, price,
            # gallery and first 200 characters are already in hand, which is
            # most of what price watching needs.
            self._detail_failures += 1
            if self._detail_failures >= self.MAX_DETAIL_FAILURES:
                self._gave_up_on_details = True
                ctx.warn(
                    f"{self._detail_failures} product pages in a row could not be read; "
                    f"taking the rest of this scan from the API only. Last error: {exc}"
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
        return replace(item, description=description or item.description)

    @staticmethod
    def _first_text(soup: BeautifulSoup, selectors: Iterable[str]) -> str | None:
        for selector in selectors:
            found = soup.select_one(selector)
            if found is None:
                continue
            text = text_of(found)
            if text:
                return text
        return None
