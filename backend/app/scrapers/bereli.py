"""Bereli (bereli.com) -- its suppressors.

A South Carolina dealer, added on 2026-10-28 with the second batch of
suppressor shops: about 150 cans that day, mostly Dead Air, SilencerCo and
AAC. Measured once before for its used guns and refused (it has none); a
suppressor shelf is a different question.

**The catalog is a Meilisearch index**, not the Algolia the theme's
InstantSearch suggests: the BigCommerce store's grid is drawn from
``bereli-instantsearch.opt7dev.com``, with a search-only key the theme's own
script bundle carries (``Authorization: "Bearer ..."`` beside the host). The
bundle's address changes with each theme release, so the walk reads it from
the category page, then the key from the bundle, on every scan. The search
host has no robots.txt; the shop's disallows only its cart, account and
tracking parameters.

Read: ``categories.lvl0 = "Suppressors"``, less the "Suppressors > Accessories"
branch, and a part still sold there is left out by name
(``suppressors.names_a_part``). A record carries the BigCommerce product id
(so the key is the one :mod:`app.scrapers.bigcommerce` would build), the
title, the price and sale price, the stock count and the maker.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlencode, urljoin

from ..services import suppressors
from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace
from .searchanise import full_size

SITE_BASE = "https://www.bereli.com/"
CATEGORY_PAGE = f"{SITE_BASE}rifle-suppressors/"
PAGE_SIZE = 100
MAX_PAGES = 20
FILTER = 'categories.lvl0 = "Suppressors" AND NOT categories.lvl1 = "Suppressors > Accessories"'

_BUNDLE = re.compile(r"https://[^\"']+/theme-bundle\.main\.js")
_SEARCH = re.compile(
    r"(https://[a-z0-9.-]+)/indexes/(\w+)/search.{0,200}?Bearer ([A-Za-z0-9]{32,})", re.S
)


def search_settings(bundle: str) -> tuple[str, str, str]:
    """The search host, index and key the theme's bundle uses."""
    found = _SEARCH.search(bundle)
    if not found:
        raise ScrapeError("The theme bundle no longer names its search host and key.")
    return found.group(1), found.group(2), found.group(3)


def item_from_hit(hit: dict[str, Any]) -> ScrapedItem | None:
    product_id = hit.get("bigcommerce_id")
    path = hit.get("url")
    title = normalize_whitespace(str(hit.get("product_name") or ""))
    if not product_id or not isinstance(path, str) or not title:
        return None
    if hit.get("is_visible") is False or suppressors.names_a_part(title):
        return None
    sale = hit.get("sale_price") or 0
    raw = sale or hit.get("calculated_price") or hit.get("price")
    try:
        price = float(raw or 0) or None
    except (TypeError, ValueError):
        price = None
    image = hit.get("primary_image_thumbnail")
    level = hit.get("inventory_level")
    return ScrapedItem(
        external_key=f"bc-{product_id}",
        url=urljoin(SITE_BASE, path),
        title=title,
        price=price,
        category="Suppressors",
        caliber=hit.get("caliber") or None,
        manufacturer=normalize_whitespace(str(hit.get("product_brand") or "")) or None,
        is_sold=isinstance(level, int) and level <= 0,
        is_new=True,
        image_urls=[full_size(image)] if isinstance(image, str) and image else [],
        images_are_complete=True,
    )


class BereliScraper(SiteScraper):
    slug = "bereli"
    name = "Bereli"
    base_url = SITE_BASE
    description = "South Carolina dealer's suppressors: Dead Air, SilencerCo, AAC and more."
    requires_browser = False
    default_interval_minutes = 1440
    sells = "new"
    #: The maker and caliber come from the shop's own fields.
    states_facts = True
    newsletter_url = SITE_BASE
    newsletter_note = "Newsletter signup form in the footer (BigCommerce)"
    shipping_note = "Suppressors transfer through your dealer; shipping at checkout"
    shipping_source = f"{SITE_BASE}shipping-returns/"
    min_request_delay: float = 2.0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        bundle_url = _BUNDLE.search(ctx.get_text(CATEGORY_PAGE))
        if not bundle_url:
            raise ScrapeError("The category page no longer links its theme bundle.")
        host, index, key = search_settings(ctx.get_text(bundle_url.group(0)))
        ctx.keep_at_least(host + "/", self.min_request_delay)
        endpoint = f"{host}/indexes/{index}/search"
        headers = {"Authorization": f"Bearer {key}"}
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            ctx.check_stop()
            query = urlencode(
                {"q": "", "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "filter": FILTER}
            )
            try:
                document = json.loads(ctx.get_text(f"{endpoint}?{query}", headers=headers))
            except ValueError as exc:
                raise ScrapeError(f"{endpoint} answered with something not JSON: {exc}") from exc
            hits = document.get("hits") or []
            for hit in hits:
                item = item_from_hit(hit)
                if item is not None and item.external_key not in seen:
                    seen.add(item.external_key)
                    yield item
            if len(hits) < PAGE_SIZE:
                break
        ctx.log(f"Suppressors: {len(seen)} listing(s).")
