"""Primary Arms (primaryarms.com).

A Houston optics and AR dealer with a large NFA shelf, added on 2026-10-25 with
the Suppressors Type.

**The catalog is NetSuite SuiteCommerce**, and its suppressor page is a 9 KB
JavaScript shell. The data behind it is SuiteCommerce's item API,
``/api/items?fieldset=search&q=...``, which the shop's robots.txt allows by
name (``Allow: */api/items*``) while disallowing its HTML search pages. A
record carries the title (``pagetitle``; ``displayname`` is the SKU), the
price, ``isinstock``, the maker, the gallery and ``custitem_isnfa``.

Read: a search for "suppressor" and one for "silencer" (344 and 188 hits on
2026-10-25, overlapping), keeping only the records the shop flags as NFA
items -- the cans themselves. The rest are the mounts, covers and wipes that
match the same words. A category filter would be tidier; the API accepted the
category parameters tried and ignored them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import quote, urlencode

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

SITE_BASE = "https://www.primaryarms.com/"
API = f"{SITE_BASE}api/items"
PAGE_SIZE = 100
MAX_PAGES = 10
QUERIES = ("suppressor", "silencer")


def _image(url: str) -> str:
    """The gallery's URLs carry spaces ("SSP Applications/NetSuite Inc. - ...")."""
    return quote(url, safe=":/?=&%")


def item_from_record(record: dict[str, Any]) -> ScrapedItem | None:
    if record.get("custitem_isnfa") is not True:
        return None
    item_id = record.get("internalid")
    path = record.get("urlcomponent")
    title = normalize_whitespace(
        str(record.get("pagetitle") or record.get("storedisplayname2") or "")
    )
    if not item_id or not path or not title:
        return None
    try:
        price = float(record.get("onlinecustomerprice") or 0) or None
    except (TypeError, ValueError):
        price = None
    gallery = (record.get("itemimages_detail") or {}).get("urls") or []
    images = [
        _image(entry["url"]) for entry in gallery if isinstance(entry, dict) and entry.get("url")
    ]
    return ScrapedItem(
        external_key=f"pa-{item_id}",
        url=f"{SITE_BASE}{path}",
        title=title,
        price=price,
        # An NFA item the shop flags itself: never a part (app/services/suppressors.py).
        category="NFA Suppressors",
        manufacturer=normalize_whitespace(str(record.get("manufacturer") or "")) or None,
        is_sold=not record.get("isinstock"),
        is_new=True,
        image_urls=images,
        images_are_complete=bool(images),
        extra={"sku": record.get("itemid")},
    )


class PrimaryArmsScraper(SiteScraper):
    slug = "primary-arms"
    name = "Primary Arms"
    base_url = SITE_BASE
    description = "Houston optics and AR dealer's NFA shelf: suppressors from every major maker."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "new"
    #: The maker comes from the shop's own field.
    states_facts = True
    newsletter_url = None
    newsletter_note = "No signup form found on the site; checked 2026-10-25"
    shipping_note = "NFA items transfer through your dealer; shipping at checkout"
    shipping_source = f"{SITE_BASE}nfa/suppressors"
    min_request_delay: float = 2.0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        seen: set[str] = set()
        for term in QUERIES:
            for page in range(MAX_PAGES):
                ctx.check_stop()
                query = urlencode(
                    {
                        "fieldset": "search",
                        "q": term,
                        "limit": PAGE_SIZE,
                        "offset": page * PAGE_SIZE,
                    }
                )
                text = ctx.get_text(f"{API}?{query}")
                try:
                    document = json.loads(text)
                except ValueError as exc:
                    raise ScrapeError(
                        f"/api/items answered with something not JSON: {exc}"
                    ) from exc
                records = document.get("items") or []
                for record in records:
                    item = item_from_record(record)
                    if item is not None and item.external_key not in seen:
                        seen.add(item.external_key)
                        yield item
                total = document.get("total")
                if not records or not isinstance(total, int) or (page + 1) * PAGE_SIZE >= total:
                    break
        ctx.log(f"Suppressors: {len(seen)} NFA listing(s).")
