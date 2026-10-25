"""Silencer Central (silencercentral.com).

A South Dakota silencer dealer that ships to the buyer's door after the ATF
approves the transfer -- its own Banish line and the other makers' cans, 358
on 2026-10-25 -- added that day with the Suppressors Type.

**The catalog is in Algolia**, as at Botach (:mod:`app.scrapers.algolia`), but
written by Magento's Algolia extension rather than BigCommerce's, so the
record is a different shape: ``name``, ``url``, ``price.USD.default``,
``in_stock`` (1 or false), ``image_url``, ``short_description``. And the key
is a *secured* search key that names its own expiry (``validUntil``, a day
or so ahead): it is read from the shop's page on every scan, never kept.

Read: the "Silencers" tree (``categories.level0``), less its "Archive" branch
of discontinued cans. Not read: "Accessories" -- mounts, thread adapters,
covers -- and the fingerprint kits and trust paperwork beside them. The
record's own short description is enough; no product page is fetched.
robots.txt rules out the shop's filtered category URLs, none of which this
asks for; the Algolia host has no robots.txt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlencode

from .base import (
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    flatten_html,
    normalize_whitespace,
)

SITE_BASE = "https://www.silencercentral.com/"
#: The page that carries the search settings.
SETTINGS_PAGE = f"{SITE_BASE}shop/silencers/"
PAGE_SIZE = 100
MAX_PAGES = 20

_SETTING = re.compile(r'"(applicationId|apiKey|indexName)":"([^"]+)"')


def search_settings(page: str) -> dict[str, str]:
    """The Algolia application, key and index prefix the page publishes."""
    found: dict[str, str] = {}
    for name, value in _SETTING.findall(page):
        found.setdefault(name, value)
    missing = {"applicationId", "apiKey", "indexName"} - set(found)
    if missing:
        raise ScrapeError(f"The page no longer publishes {', '.join(sorted(missing))}.")
    return found


def price_of(hit: dict[str, Any]) -> float | None:
    block = (hit.get("price") or {}).get("USD") or {}
    try:
        value = float(block.get("default") or 0)
    except (TypeError, ValueError):
        return None
    return value or None


def item_from_hit(hit: dict[str, Any]) -> ScrapedItem | None:
    object_id = hit.get("objectID")
    url = hit.get("url")
    title = normalize_whitespace(str(hit.get("name") or ""))
    if not object_id or not url or not title:
        return None
    image = hit.get("image_url")
    return ScrapedItem(
        external_key=f"sc-{object_id}",
        url=str(url),
        title=title,
        price=price_of(hit),
        description=flatten_html(hit.get("short_description")) or None,
        # The Silencers tree is cans only; its parts are under Accessories.
        category="NFA Suppressors",
        is_sold=not hit.get("in_stock"),
        image_urls=[image] if isinstance(image, str) and image else [],
        images_are_complete=True,
        is_new=True,
        extra={"sku": hit.get("sku"), "type": hit.get("suppressor_type")},
    )


class SilencerCentralScraper(SiteScraper):
    slug = "silencer-central"
    name = "Silencer Central"
    base_url = SITE_BASE
    description = (
        "South Dakota silencer dealer that ships to your door once the ATF approves: "
        "its Banish line and other makers' cans."
    )
    requires_browser = False
    default_interval_minutes = 1440
    sells = "new"
    newsletter_url = None
    newsletter_note = "No signup form found on the site; checked 2026-10-25"
    shipping_note = "Ships to the buyer's door after ATF approval; no rate published"
    shipping_source = f"{SITE_BASE}shop/silencers/"
    min_request_delay: float = 2.0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        settings = search_settings(ctx.get_text(SETTINGS_PAGE))
        app_id = settings["applicationId"]
        host = f"https://{app_id}-dsn.algolia.net/"
        ctx.keep_at_least(host, self.min_request_delay)
        endpoint = f"{host}1/indexes/{settings['indexName']}_products"
        filters = json.dumps(
            ["categories.level0:Silencers", "categories.level1:-Silencers /// Archive"]
        )
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            ctx.check_stop()
            query = urlencode(
                {
                    "x-algolia-application-id": app_id,
                    "x-algolia-api-key": settings["apiKey"],
                    "query": "",
                    "page": page,
                    "hitsPerPage": PAGE_SIZE,
                    "facetFilters": filters,
                }
            )
            text = ctx.get_text(f"{endpoint}?{query}")
            try:
                document = json.loads(text)
            except ValueError as exc:
                raise ScrapeError(f"Algolia answered with something not JSON: {exc}") from exc
            hits = document.get("hits") or []
            if not hits and page == 0:
                ctx.warn("The Silencers tree matched nothing; has the shop renamed it?")
            for hit in hits:
                item = item_from_hit(hit)
                if item is not None and item.external_key not in seen:
                    seen.add(item.external_key)
                    yield item
            pages = document.get("nbPages")
            if not hits or not isinstance(pages, int) or page + 1 >= pages:
                break
        ctx.log(f"Silencers: {len(seen)} listing(s).")
