"""Silencer Shop (silencershop.com).

The largest suppressor-only dealer, added on 2026-10-28 with the second batch
of suppressor shops: 836 cans in its Silencers tree that day.

**Its grid is Magento's Algolia extension**, as at Silencer Central
(:mod:`app.scrapers.silencer_central`), and the category page's own product
loading is the route robots.txt rules out (``?ajax``, ``?cat=``,
``?*product_list_*``) -- so, as there, the Algolia index is read directly,
which the shop's robots.txt does not govern (that host has none) and which
is the same catalog every visitor's browser reads. The settings are in
``window.algoliaConfig = JSON.parse('...')``, escaped twice; the key is a
secured key that names its own expiry, so it is read from the page on every
scan.

Read: ``categories.level0:Silencers`` -- cans only; the shop's SBRs and its
parts are other trees, so the section is "NFA Suppressors"
(app/services/suppressors.py). A record carries the name, the price, the
maker, the caliber and ``stock_data``: "In Stock" and "Backorder" are both
orderable (``stock_status`` "in_stock"); "Out of Stock" is read as sold.
``is_resale`` marks a used can.
"""

from __future__ import annotations

import codecs
import json
import re
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlencode

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

SITE_BASE = "https://www.silencershop.com/"
SETTINGS_PAGE = f"{SITE_BASE}silencers.html"
PAGE_SIZE = 100
MAX_PAGES = 30

_CONFIG = re.compile(r"window\.algoliaConfig\s*=\s*JSON\.parse\('(.*?)'\);", re.S)
_SETTING = re.compile(r'"(applicationId|apiKey|indexName)":"([^"]+)"')


def search_settings(page: str) -> dict[str, str]:
    """The Algolia application, key and index prefix the page publishes."""
    found = _CONFIG.search(page)
    if not found:
        raise ScrapeError("The page no longer carries window.algoliaConfig.")
    text = codecs.decode(found.group(1).replace("\\/", "/"), "unicode_escape")
    settings: dict[str, str] = {}
    for name, value in _SETTING.findall(text):
        settings.setdefault(name, value)
    missing = {"applicationId", "apiKey", "indexName"} - set(settings)
    if missing:
        raise ScrapeError(f"algoliaConfig no longer names {', '.join(sorted(missing))}.")
    return settings


def item_from_hit(hit: dict[str, Any]) -> ScrapedItem | None:
    object_id = hit.get("objectID")
    url = hit.get("url")
    title = normalize_whitespace(str(hit.get("name") or ""))
    if not object_id or not isinstance(url, str) or not title:
        return None
    try:
        price = float(((hit.get("price") or {}).get("USD") or {}).get("default") or 0) or None
    except (TypeError, ValueError):
        price = None
    stock = hit.get("stock_data") or {}
    image = hit.get("image_url")
    caliber = hit.get("caliber")
    return ScrapedItem(
        external_key=f"ss-{object_id}",
        url=url,
        title=title,
        price=price,
        category="NFA Suppressors",
        caliber=caliber if isinstance(caliber, str) and caliber else None,
        manufacturer=normalize_whitespace(str(hit.get("manufacturer") or "")) or None,
        is_sold=stock.get("stock_status") != "in_stock",
        is_new=not hit.get("is_resale"),
        image_urls=[image] if isinstance(image, str) and image else [],
        images_are_complete=True,
        extra={"stock": stock.get("stock_message")},
    )


class SilencerShopScraper(SiteScraper):
    slug = "silencer-shop"
    name = "Silencer Shop"
    base_url = SITE_BASE
    description = "The largest suppressor-only dealer: over 800 cans from every maker."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "mixed"
    #: The maker and caliber come from the shop's own fields.
    states_facts = True
    newsletter_url = SITE_BASE
    newsletter_note = '"Sign up for exclusive deals & offers!" form in the footer'
    shipping_note = "Cans transfer through a Silencer Shop Powered dealer; no rate published"
    shipping_source = SETTINGS_PAGE
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
                    "facetFilters": json.dumps(["categories.level0:Silencers"]),
                }
            )
            try:
                document = json.loads(ctx.get_text(f"{endpoint}?{query}"))
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
