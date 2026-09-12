"""AIM Surplus (aimsurplus.com).

**The fourth site this project filed as "needs a browser" that did not.** The
category page is 39KB of Vue 3 scaffolding with zero prices in it, and the
conclusion drawn from that — here and for J&G Sales, Centerfire and SARCO
before it — was headless Chrome. It needed a look at the JSON their own front
end already calls.

Two routes, both named in ``/js/store.js``:

* ``/data/search?q=&g=&category=<id>&filter=&sort_by=&pagesize=<n>&page=<n>&mode=category``
  returns ``{products, facets, total, pages, category}``. A category is a
  numeric id, not a path -- the page carries its own in ``data-category-id``.
* ``/data/products/<id>`` returns the full record: description, ``in_stock``,
  ``sku``, the whole gallery, and a ``properties`` list.

**Their properties list is better than parsing.** Manufacturer, Caliber and
Capacity arrive as named fields rather than as words in a title, so the caliber
and the maker are read rather than inferred. Very little else on this list does
that; SARCO and Shopify shops are the nearest.

**Images live on CloudFront and nothing server-side says so.** The API returns
bare filenames (``1297-62d99e350e672_400.png``) and no page anywhere carries a
product image, because the whole site renders client-side. Fourteen guessed
paths returned 404. The bucket is named in one place: an inline Vue template
binds a *category* thumbnail to
``'https://dvjr4l3xblvos.cloudfront.net/categories/' + category.image``, and
the products sibling of that path is the answer. Worth writing down because
nothing else on the site will tell you.

**Two of their seven firearm sections are read**, and the split is the usual
one for a general dealer:

* **Police Trade-Ins** (162) -- LEO trade-in Sig P229R DAK and P226, Glock 19
  and 27 Gen 4, Beretta PX4 Storm, S&W M&P40 Shield, Bushmaster XM15.
* **Curio and Relics** (18) -- and this is the milsurp: a Swiss 1906/29 Luger,
  Polish Radom TTC and P-64, a CZ70, Schmidt-Rubin 1911s, a K31, a Romanian
  TT-33, a CZ82 with holster and magazines.

Left alone: Handguns (392) and Long Guns (179) are a modern dealer's shelf --
BCM RECCE-16s, Radical Firearms, Spike's Tactical -- with the occasional Yugo
SKS among them; NFA Items (221) is suppressors and short-barreled rifles; and
Receivers (69) and Frames (30) are components, which the standing rule keeps
out. The trade-ins that appear in Long Guns are cross-listings of the section
already read, and the ``seen`` set collapses them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, flatten_html

SITE_BASE = "https://aimsurplus.com/"

#: Where the product images actually are. See the module docstring: the API
#: returns filenames, and this bucket is named nowhere except one inline Vue
#: template binding a *category* image.
IMAGE_BASE = "https://dvjr4l3xblvos.cloudfront.net/products/"

#: Products per request. Their own front end asks for far fewer; this is a
#: courtesy ceiling rather than a documented limit, and it keeps a 162-item
#: section to three requests.
PAGE_SIZE = 60


class AimSurplusScraper(SiteScraper):
    slug = "aim-surplus"
    name = "AIM Surplus"
    base_url = SITE_BASE
    description = (
        "Ohio surplus dealer. Their police trade-ins and curio-and-relic "
        "firearms are read; their modern, NFA and component sections are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: A category is a numeric id because that is what the endpoint filters on.
    #: The label is what the listing is filed under here, and it is what the
    #: classifier reads -- "Police Trade-Ins" is what makes these count as
    #: police surplus, see classify._is_police_surplus.
    sources: tuple[dict[str, Any], ...] = (
        {"category": "Police Trade-Ins", "id": 744},
        {"category": "Curio and Relics", "id": 42},
    )

    #: JSON rather than markup, but a whole scan is a few dozen requests and
    #: there is nothing to be gained by hurrying.
    min_request_delay: float = 2.0

    #: Bounded for the reason every walk here is bounded.
    max_pages_per_source = 40

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)

        # Across sections: their trade-ins are cross-listed under Long Guns and
        # Handguns, and a product in two of the sections read would otherwise
        # arrive twice.
        seen: set[str] = set()
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, Any], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        label = str(source["category"])
        page = 1
        while page <= min(self.max_pages_per_source, ctx.scraping.max_pages):
            ctx.check_stop()
            payload = self._search(ctx, int(source["id"]), page)
            products = payload.get("products") or []
            if not products:
                break

            fresh = 0
            for product in products:
                item = self._item(ctx, product, label)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                fresh += 1
                yield item

            ctx.log(f"{label} page {page}: {fresh} listing(s).")
            pages = payload.get("pages")
            if isinstance(pages, int) and page >= pages:
                break
            page += 1

    def _search(self, ctx: ScrapeContext, category_id: int, page: int) -> dict[str, Any]:
        """One page of a category.

        Every parameter their own front end sends, including the empty ones:
        the endpoint answers 500 rather than defaulting when they are missing,
        which is what made this look like a route that was not there.
        """
        query = (
            f"q=&g=&category={category_id}&filter=&sort_by="
            f"&pagesize={PAGE_SIZE}&page={page}&mode=category"
        )
        body = ctx.get_text(f"{SITE_BASE}data/search?{query}")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise ScrapeError(f"{self.slug}: /data/search did not return JSON ({exc})") from exc
        if not isinstance(payload, dict):
            raise ScrapeError(f"{self.slug}: /data/search returned {type(payload).__name__}")
        return payload

    def _item(self, ctx: ScrapeContext, product: dict[str, Any], label: str) -> ScrapedItem | None:
        product_id = product.get("id")
        handle = product.get("url") or ""
        if product_id is None or not handle:
            return None

        key = f"aim-{product_id}"
        url = f"{SITE_BASE.rstrip('/')}{handle}"
        title = (product.get("name") or "").strip()
        if not title:
            return None

        item = ScrapedItem(
            external_key=key,
            url=url,
            title=title,
            price=_price(product),
            description=flatten_html(product.get("description")) or None,
            category=label,
            # The grid's own word for it. "available" is 1/0 rather than a
            # boolean, and a sold one-off collectible is gone rather than
            # re-orderable.
            is_sold=not product.get("available"),
            image_urls=_images([{"master": product.get("thumbnail")}]),
            # Only the thumbnail so far; the detail fetch below brings the rest.
            images_are_complete=False,
        )

        if not ctx.needs_detail(key):
            return item
        return self._detailed(ctx, item, int(product_id)) or item

    def _detailed(
        self, ctx: ScrapeContext, item: ScrapedItem, product_id: int
    ) -> ScrapedItem | None:
        """The full record: the gallery, the untruncated prose, and the fields.

        A failure here is not a failure of the listing — the search response
        already carries a title, a price and a URL — so it warns and keeps what
        it has.
        """
        try:
            body = ctx.get_text(f"{SITE_BASE}data/products/{product_id}")
            product = (json.loads(body) or {}).get("product") or {}
        except Exception as exc:
            ctx.warn(f"Could not read the detail for {item.url} ({exc})")
            return None
        if not product:
            return None

        fields = _properties(product)
        return ScrapedItem(
            external_key=item.external_key,
            url=item.url,
            title=(product.get("name") or item.title).strip(),
            price=_price(product) if _price(product) is not None else item.price,
            description=flatten_html(product.get("description")) or item.description,
            category=item.category,
            # Read, not inferred. See the module docstring.
            caliber=fields.get("caliber"),
            manufacturer=fields.get("manufacturer"),
            is_sold=product.get("in_stock") is False,
            image_urls=_images(product.get("images") or []),
            images_are_complete=True,
        )


def _price(product: dict[str, Any]) -> float | None:
    for key in ("price", "lowest_price"):
        raw = product.get(key)
        if raw in (None, "", 0, "0.00"):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _images(images: Iterable[Any]) -> list[str]:
    """Full-resolution URLs, in the order the shop lists them.

    ``master`` is the original; the ``x40``/``x200``/``x400``/``x1200`` keys
    beside it are resizes. Falling back through them means a record that only
    carries a thumbnail still yields something.

    **A gallery is not all photographs.** A video sits in the same list as
    ``{"embed": "zPvfPM28-SI", "master": "zPvfPM28-SI"}`` -- a YouTube id, with
    ``master`` reused to carry it rather than naming a file. Read as a filename
    it becomes a CloudFront key that does not exist, and the bucket answers 403
    rather than 404, so it looks like a blocked download instead of a wrong
    URL. Eight of those were queued across the police trade-ins, three of them
    the one product video that several listings share.
    """
    urls: list[str] = []
    for entry in images:
        if not isinstance(entry, dict):
            continue
        if entry.get("embed"):
            continue
        for key in ("master", "x1200", "x400", "x200"):
            name = entry.get(key)
            if name:
                urls.append(f"{IMAGE_BASE}{name}")
                break
    return urls


def _properties(product: dict[str, Any]) -> dict[str, str]:
    """Their named fields, lower-cased by name.

    A list of ``{"name": "Caliber", "value": "7.65 Parabellum"}`` rather than
    an object, so it is turned into one here.
    """
    out: dict[str, str] = {}
    for entry in product.get("properties") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        value = str(entry.get("value") or "").strip()
        if name and value:
            out.setdefault(name, value)
    return out
