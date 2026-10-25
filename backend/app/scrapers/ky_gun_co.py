"""KY Gun Co (kygunco.com).

The Kentucky Gun Company of Bardstown, added on 2026-10-25 with the
Suppressors Type. Measured twice before for other shelves and refused both
times for having little on them (ROADMAP.md); its suppressor wall is the
opposite -- 994 cans, 283 of them in stock that day.

**The catalog is a public Typesense collection.** The Nuxt storefront queries
``search.keenesdepot.io`` with a search-only key it publishes in the page
(``typesense:{url:...}``, ``apiKey:"..."``), and the collection's name carries a
version stamp (``kygunco_products_1773666625``) that changes when the shop
reindexes, so both are read from the page on every scan. The search host has
no robots.txt; the shop's own allows everything but the account and
checkout paths.

Read: records whose ``action`` is "Silencer" -- the shop's own word for a
suppressor -- and that are in stock. The rest are "Notify me" listings of cans
the shop does not have, and a catalog of what one cannot buy is not what this
application is for. A record is complete: name, price, condition, caliber,
maker, description and pictures, so no product page is read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlencode

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

SITE_BASE = "https://www.kygunco.com/"
#: The page that carries the search settings.
SETTINGS_PAGE = f"{SITE_BASE}category/shooting/guns/class-iii/suppressors"
PAGE_SIZE = 250
MAX_PAGES = 20

_HOST = re.compile(r'typesense:\{url:"([^"]+)"')
_KEY = re.compile(r'apiKey:"([A-Za-z0-9]+)"')
_COLLECTION = re.compile(r"\b(kygunco_products_\d+)\b")


def search_settings(page: str) -> tuple[str, str, str]:
    """The Typesense host, key and collection the page publishes."""
    host, key, collection = _HOST.search(page), _KEY.search(page), _COLLECTION.search(page)
    if not (host and key and collection):
        raise ScrapeError("The page no longer publishes its Typesense settings.")
    return host.group(1).rstrip("/"), key.group(1), collection.group(1)


def item_from_document(doc: dict[str, Any]) -> ScrapedItem | None:
    product_id = doc.get("id")
    slug = doc.get("slug")
    title = normalize_whitespace(str(doc.get("name") or ""))
    if not product_id or not slug or not title:
        return None
    try:
        price = float(doc.get("price") or 0) or None
    except (TypeError, ValueError):
        price = None
    calibers = doc.get("caliber") or []
    maker = (doc.get("manufacturer") or {}).get("name")
    images = [doc.get("imageUrl")]
    return ScrapedItem(
        external_key=f"kyg-{product_id}",
        url=f"{SITE_BASE}product/{slug}",
        title=title,
        price=price,
        description=normalize_whitespace(str(doc.get("longDescription") or "")) or None,
        # The shop's "Silencer" is an NFA item, never a part: the section
        # says so for app/services/suppressors.py.
        category="NFA Suppressors",
        caliber=calibers[0] if isinstance(calibers, list) and len(calibers) == 1 else None,
        manufacturer=maker or None,
        is_sold=not doc.get("isInStock"),
        is_new=str(doc.get("condition") or "New").lower() == "new",
        image_urls=[url for url in images if isinstance(url, str) and url],
        images_are_complete=True,
        extra={"mpn": doc.get("mpn")},
    )


class KyGunCoScraper(SiteScraper):
    slug = "ky-gun-co"
    name = "KY Gun Co"
    base_url = SITE_BASE
    description = (
        "The Kentucky Gun Company's suppressor wall: the in-stock cans of nearly a thousand."
    )
    requires_browser = False
    default_interval_minutes = 1440
    sells = "mixed"
    #: The maker and caliber come from the shop's own fields.
    states_facts = True
    newsletter_url = None
    newsletter_note = "No signup form found on the site; checked 2026-10-25"
    shipping_note = "NFA items transfer through your dealer; shipping at checkout"
    shipping_source = SETTINGS_PAGE
    min_request_delay: float = 2.0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        host, key, collection = search_settings(ctx.get_text(SETTINGS_PAGE))
        ctx.keep_at_least(host + "/", self.min_request_delay)
        endpoint = f"{host}/collections/{collection}/documents/search"
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            query = urlencode(
                {
                    "q": "*",
                    "filter_by": "action:=Silencer && isInStock:=true",
                    "per_page": PAGE_SIZE,
                    "page": page,
                    "x-typesense-api-key": key,
                }
            )
            text = ctx.get_text(f"{endpoint}?{query}")
            try:
                document = json.loads(text)
            except ValueError as exc:
                raise ScrapeError(f"Typesense answered with something not JSON: {exc}") from exc
            hits = document.get("hits") or []
            for hit in hits:
                item = item_from_document(hit.get("document") or {})
                if item is not None and item.external_key not in seen:
                    seen.add(item.external_key)
                    yield item
            found = document.get("found")
            if not hits or not isinstance(found, int) or page * PAGE_SIZE >= found:
                break
        ctx.log(f"Suppressors: {len(seen)} in stock.")
