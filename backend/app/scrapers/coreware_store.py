"""Shared machinery for gun shops on Coreware's older storefront.

DeLeon RX Guns and Ammo, asked for on 2026-10-20 for concealed carry pistols
and revolvers. (Battlehawk Armory, on the same storefront, was added the
same day and removed on 2026-10-21: it blocked this application for good.) The same platform as
:mod:`app.scrapers.coreware_search`, without the search app: a category page
embeds twenty products as JavaScript and a "Load More" reloads the page, so
the walk asks the endpoint the page itself uses --
``/retail-store-controller?ajax=true&url_action=get_products`` with the
category and ``exclude_out_of_stock=1`` -- which answers every match at once,
as JSON with its field names alongside. robots.txt allows everything.

* **Most of it is a distributor's**, as at the other Coreware shops: 5,911
  handguns in stock at DeLeon that day, 66 in the store. Both are read.
* **A title is cut to fifty characters** ("Korth Mongoose, .357 Magnum, 4\\"
  Barrel, 6rd Cylind..."), so a listing's product page is read once, for the
  whole title (``h1#_product_description``) and the specifications table as
  its description. Until then, and on every scan after, the short title is
  marked as short (``ScrapedItem.title_truncated``) so the stored whole one is
  kept.
* **The caliber** is read from the title and the product's address, which
  carries the whole title in lower case ("naa-sw250-sidewinder-22-mag-..."),
  and only the carry calibers are kept (:func:`carry.is_carry_caliber`).
* **Used** is a used category, or "USED" in the title.

**Gently, after both shops refused us** (2026-10-21). The first scans read a
product page for every one of about 4,000 listings each, and after about two
hours both answered 403 -- DeLeon for some hours, Battlehawk to every request,
its home page included. So a scan now reads at most
:attr:`~CorewareStoreScraper.max_details_per_scan` product pages, the rest
waiting for the next scan with their short titles; it stops reading product
pages at the first refusal rather than asking each one four times; and a
category list it cannot read is a gap (``ScrapeContext.not_read``), not a
reason to throw away the others or to de-list that category.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..services import carry, classify
from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
    text_of,
)
from .storefront import parse_price

_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*$")
_USED_TITLE = re.compile(r"\b(?:used|usd|pre[\s-]*owned|demo)\b", re.I)


def product_rows(results: Any) -> list[list[Any]]:
    """The product rows, whichever way the shop's PHP encoded them: a list, or
    -- when its array's keys are not in order -- an object keyed "0", "1",
    ... (Battlehawk Armory's revolvers, 2026-10-20, which read as ten products made
    of the keys' characters before this)."""
    if isinstance(results, dict):
        return [
            results[key] for key in sorted(results, key=lambda k: int(k) if str(k).isdigit() else 0)
        ]
    return list(results or [])


class CorewareStoreScraper(SiteScraper):
    """One older-Coreware shop's in-stock handguns in the carry calibers."""

    sells = "mixed"
    #: The shop\'s own caliber and maker, from its records.
    states_facts = True
    requires_browser = False
    min_request_delay: float = 2.0
    #: One entry per category: ``{"category": "Pistols", "id": 1719}``, and
    #: ``"used": True`` for the shop's used section.
    sources: tuple[dict[str, Any], ...] = ()
    #: Where a product's own photograph lives when it is not a distributor's:
    #: ``https://{image_cdn}/cache/image-full-{filename}``.
    image_cdn = ""
    wanted_caliber: Callable[[str], bool] = staticmethod(carry.is_carry_caliber)
    #: Product pages read per scan: about 25 minutes at the shops' pace, well
    #: under the two hours that brought both refusals.
    max_details_per_scan = 400

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._details_read = 0
        self._details_refused = False
        seen: set[str] = set()
        read_any = False
        for source in self.sources:
            ctx.check_stop()
            query = urlencode(
                {
                    "ajax": "true",
                    "url_action": "get_products",
                    "product_category_id": source["id"],
                    "exclude_out_of_stock": 1,
                }
            )
            try:
                text = ctx.get_text(f"{self.base_url}retail-store-controller?{query}")
            except (Disallowed, ScrapeError) as exc:
                ctx.warn(f"{source['category']}: could not read the list ({exc}).")
                ctx.not_read(str(source["category"]))
                continue
            try:
                answer = json.loads(text)
                names = list(answer["product_field_names"])
                rows = product_rows(answer.get("product_results"))
            except (ValueError, TypeError, KeyError) as exc:
                raise ScrapeError(f"{source['category']}: not the product list ({exc})") from exc
            read_any = True
            ctx.log(f"{source['category']}: {len(rows)} in stock.")
            for row in rows:
                ctx.check_stop()
                item = self.item_from_record(dict(zip(names, row, strict=False)), source)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield self.with_detail(ctx, item)
        if not read_any:
            raise ScrapeError("No category list could be read.")

    def item_from_record(
        self, record: dict[str, Any], source: dict[str, Any]
    ) -> ScrapedItem | None:
        """One listing from the product list, or None for one not wanted."""
        product_id = record.get("product_id")
        listed = normalize_whitespace(str(record.get("description") or ""))
        link = str(record.get("product_detail_link") or "")
        if product_id is None or not listed or not link:
            return None
        truncated = bool(_ELLIPSIS.search(listed))
        title = _ELLIPSIS.sub("", listed)
        slug_words = link.rsplit("/", 1)[-1].replace("-", " ")
        caliber = classify.extract_caliber(title) or classify.extract_caliber(slug_words)
        if not caliber or not self.wanted_caliber(caliber):
            return None
        price = (
            None
            if record.get("call_price") or record.get("hide_dollar")
            else (parse_price(str(record.get("sale_price") or "")))
        )
        return ScrapedItem(
            external_key=f"cws-{product_id}",
            url=self.base_url + link.lstrip("/"),
            title=title,
            title_truncated=truncated,
            price=price,
            category=str(source["category"]),
            caliber=caliber,
            manufacturer=record.get("manufacturer_name") or None,
            image_urls=self._images(record),
            is_new=not (source.get("used") or _USED_TITLE.search(title)),
            extra={"upc": record.get("upc_code")} if record.get("upc_code") else {},
        )

    def _images(self, record: dict[str, Any]) -> list[str]:
        remote = record.get("remote_image")
        if remote:
            return [f"https://images.coreware.com/images/products/{remote}.jpg"]
        filename = record.get("image_base_filename")
        if filename and self.image_cdn:
            return [f"https://{self.image_cdn}/cache/image-full-{filename}"]
        return []

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """The whole title and the specifications, from the product page --
        once per listing."""
        if self._details_refused or self._details_read >= self.max_details_per_scan:
            return item
        if not ctx.needs_detail(item.external_key):
            return item
        self._details_read += 1
        try:
            soup = BeautifulSoup(ctx.get_text(item.url, retries=1), "html.parser")
        except (Disallowed, ScrapeError) as exc:
            if getattr(exc, "status", None) in (403, 429):
                self._details_refused = True
                ctx.warn(
                    f"{item.url} was refused ({exc}); no more product pages this scan. "
                    "The rest keep their short titles until a later scan."
                )
            else:
                ctx.log(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item
        heading = soup.select_one("h1#_product_description")
        whole = normalize_whitespace(text_of(heading)) if heading is not None else ""
        if whole:
            item.title = whole
            item.title_truncated = False
        specs = soup.select_one("#specifications_table")
        if specs is not None:
            item.description = text_of(specs) or None
        return item
