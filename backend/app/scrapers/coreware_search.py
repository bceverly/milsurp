"""Shared machinery for gun shops on Coreware whose catalog is a Meilisearch index.

Coreware sells a storefront to gun shops, and its newer one draws the
catalog with a search app reading a Meilisearch index at
``search.coreware.com``: the category page arrives with no products in it,
and the app queries the index with a key the page publishes in
``window.__SEARCH_APP_DATA__`` (``MEILISEARCH_SEARCH_API_KEY``,
``MEILISEARCH_INDEX_NAME``, ``MEILISEARCH_URL``). The key is a search-only key,
published to be used, as Algolia's is (see :mod:`app.scrapers.algolia`), and
the walk reads it from the page every scan rather than keeping a copy.

Measured on 2026-10-20 at Locked & Loaded and Florida Guns, asked for "for
concealed carry pistols":

* **A record is complete.** Title, description, brand, UPC, the price, stock,
  categories and a ``facets`` object of the shop's specifications -- caliber,
  capacity, barrel, frame size -- so there is no product page to fetch.
* **Most of it is a distributor's.** ``inStock`` is the shop *or* its
  distributor; ``inStockLocally`` is the shop's own shelf. Locked & Loaded had
  5,390 handguns in stock, 282 of them in the shop. Both are read, as asked
  ("build all of them including new"), and every one is a new gun unless the
  shop files it in a used category.
* **The index answers at most 1,000 hits a query**, so the walk asks one
  caliber at a time -- only the carry calibers (:func:`carry.is_carry_caliber`),
  in whatever spelling the shop gave them ("9mm Luger (9x19 Parabellum)",
  "357 Mag", ".45 ACP/Auto") -- and splits a caliber by brand when even that
  is too many.
* **GET, not POST**, as with Algolia: Meilisearch answers a search as a GET
  with its parameters in the query string, which keeps every request inside
  :meth:`ScrapeContext.get_text` with its robots check, pacing and retries.
  ``search.coreware.com`` has no robots.txt (404).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any
from urllib.parse import urlencode

from ..services import carry
from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

#: The most hits the index returns for one query.
MAX_HITS = 1000
#: Hits per request.
PAGE_SIZE = 250

_APP_DATA = re.compile(
    r'"(MEILISEARCH_URL|MEILISEARCH_INDEX_NAME|MEILISEARCH_SEARCH_API_KEY)"\s*:\s*"([^"]+)"'
)
#: Categories a shop files a used gun under.
_USED = re.compile(r"USED|PRE_OWNED|CONSIGN", re.I)


def search_settings(page: str) -> dict[str, str]:
    """The search URL, index and key the shop's page publishes."""
    found = {name: value.replace("\\/", "/") for name, value in _APP_DATA.findall(page)}
    missing = {"MEILISEARCH_URL", "MEILISEARCH_INDEX_NAME", "MEILISEARCH_SEARCH_API_KEY"} - set(
        found
    )
    if missing:
        raise ScrapeError(f"The page no longer publishes {', '.join(sorted(missing))}.")
    return found


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class CorewareSearchScraper(SiteScraper):
    """One Coreware shop's in-stock guns in the wanted calibers."""

    sells = "mixed"
    #: The shop\'s own caliber and maker, from its records.
    states_facts = True
    requires_browser = False
    min_request_delay: float = 2.0
    #: The page that carries the search settings.
    settings_path = "product-category-group/handguns"
    #: What is read: the index's category groups, and within them only these
    #: categories -- the handgun group also files barrels, grips and frames
    #: ("TACTICAL SOLUTIONS .22LR FLUTED THREADED BARREL", 2026-10-20).
    category_groups: tuple[str, ...] = ("HANDGUNS",)
    categories: tuple[str, ...] = (
        "PISTOLS",
        "REVOLVERS",
        "RIMFIRE_PISTOLS",
        "RIMFIRE_REVOLVERS",
        "TACTICAL_PISTOLS",
        "1911",
        "BREAK_ACTION_HANDGUNS",
    )
    #: The calibers read, by the shop's own spelling of each.
    wanted_caliber: Callable[[str], bool] = staticmethod(carry.is_carry_caliber)
    #: The category label a listing is filed under.
    label = "Handguns"

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        settings = search_settings(ctx.get_text(self.base_url + self.settings_path))
        endpoint = (
            settings["MEILISEARCH_URL"].rstrip("/")
            + f"/indexes/{settings['MEILISEARCH_INDEX_NAME']}/search"
        )
        headers = {"Authorization": f"Bearer {settings['MEILISEARCH_SEARCH_API_KEY']}"}
        groups = ", ".join(self.category_groups)
        kinds = ", ".join(self.categories)
        base = (
            f"departments = FIREARMS AND categoryGroups IN [{groups}] "
            f"AND categories IN [{kinds}] AND inStock = 1"
        )

        def ask(filter_: str, **params: Any) -> dict[str, Any]:
            query = urlencode({"q": "", "filter": filter_, **params})
            text = ctx.get_text(f"{endpoint}?{query}", headers=headers)
            try:
                return dict(json.loads(text))
            except (ValueError, TypeError) as exc:
                raise ScrapeError(f"{endpoint} answered with something not JSON: {exc}") from exc

        calibers = ask(base, limit=0, facets="facets.CALIBER").get("facetDistribution", {})
        seen: set[str] = set()
        for caliber, count in sorted((calibers.get("facets.CALIBER") or {}).items()):
            ctx.check_stop()
            if not self.wanted_caliber(caliber):
                continue
            narrowed = f"{base} AND facets.CALIBER = {_quoted(caliber)}"
            if count <= MAX_HITS:
                parts = [narrowed]
            else:
                brands = ask(narrowed, limit=0, facets="brand").get("facetDistribution", {})
                parts = [
                    f"{narrowed} AND brand = {_quoted(brand)}"
                    for brand in sorted(brands.get("brand") or {})
                ]
            for part in parts:
                for offset in range(0, MAX_HITS, PAGE_SIZE):
                    hits = ask(part, limit=PAGE_SIZE, offset=offset).get("hits") or []
                    for hit in hits:
                        item = self.item_from_hit(hit)
                        if item is not None and item.external_key not in seen:
                            seen.add(item.external_key)
                            yield item
                    if len(hits) < PAGE_SIZE:
                        break
            ctx.log(f"{caliber}: {count} in stock.")

    def item_from_hit(self, hit: dict[str, Any]) -> ScrapedItem | None:
        """One listing, complete: there is no product page to read."""
        product_id = hit.get("id")
        title = normalize_whitespace(str(hit.get("title") or ""))
        if product_id is None or not title:
            return None
        link = hit.get("link_name")
        url = (
            f"{self.base_url}product/{link}"
            if link
            else f"{self.base_url}product-details?id={product_id}"
        )
        pricing = (hit.get("userTypePricing") or {}).get("DEFAULT") or {}
        try:
            price = float(pricing.get("displayPrice") or 0) or None
        except (TypeError, ValueError):
            price = None
        facets = hit.get("facets") or {}
        images = [hit.get("image"), *(hit.get("alternateImages") or [])]
        categories = [str(c) for c in hit.get("categories") or []]
        return ScrapedItem(
            external_key=f"cw-{product_id}",
            url=url,
            title=title,
            price=price,
            description=normalize_whitespace(str(hit.get("description") or "")) or None,
            category=self.label,
            caliber=facets.get("CALIBER") or None,
            manufacturer=hit.get("brandDescription") or None,
            image_urls=[str(src) for src in images if isinstance(src, str) and src],
            is_new=not any(_USED.search(c) for c in categories),
            extra={"upc": hit.get("upc"), "in_store": bool(hit.get("inStockLocally"))},
        )
