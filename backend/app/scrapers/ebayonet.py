"""eBayonet (ebayonet.com).

**This shop used to be five pages saved out of Microsoft Word.** No storefront,
no product pages, no ``<img>`` tags -- a listing was a run of paragraphs, the
photographs were bare URLs typed into the prose, and the only identifier was a
five-digit stock number at the head of the opening paragraph. That reader is
gone, and so is the site it read: the five ``.htm`` pages now redirect to
``/catalogue/`` and the old photo URLs 404.

What replaced it is WordPress with a bespoke plugin, and the plugin did the
hard part for us. Every listing is a post of type ``item`` whose ``meta``
carries the fields the old reader had to infer out of prose:

    _ebay_stock        "18783"                 the old stock number
    _ebay_price        100                     an integer, already the unit price
    _ebay_price_text   "$7 each or 3 for $20"  what the shop actually wrote
    _ebay_status       "available"
    _ebay_gallery      [72, 73, 74, 75, 76]    media ids, in order
    _ebay_legacy_page  ".../bayonetsa_f.htm"   which of the five it came from

So there is nothing left to parse. ``/wp-json/wp/v2/item`` is public, paginates
a hundred at a time, and answers the whole catalog in nine requests.

**The slug is the key, and that is what preserves the history.** For 743 of the
825 listings the slug *is* the old stock number -- ``/item/18783/`` -- so every
price series already stored carries straight over. It also settles two cases a
stock number cannot: 71 listings (individual gun parts) have no stock number at
all, and one number is used twice, which WordPress disambiguates as ``17093``
and ``17093-2``. One rule, no collisions, and the continuity comes free.

**It is not only bayonets any more.** 712 of them still are, but the rest is
gun parts, helmets, books, uniforms and the owner's own airborne collection --
six categories, each a term in the site's ``item-category`` taxonomy. The old
reader could declare one category and have it cover the shop; this one cannot,
which is why a failed page here declares every category unread rather than one.

There is also a ``country`` taxonomy, 66 terms of it, which is a better answer
than the classifier's guess and is passed through as one.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit

from ..services import classify
from .base import (
    PriceCheck,
    ScrapeCanceled,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
)

SITE_BASE = "https://ebayonet.com/"

#: The WordPress REST API. Public, and the whole of what this reader needs.
API = f"{SITE_BASE}wp-json/wp/v2/"
ITEMS_API = f"{API}item"
MEDIA_API = f"{API}media"
ITEM_CATEGORY_API = f"{API}item-category"
COUNTRY_API = f"{API}country"

#: WordPress's own ceiling on ``per_page``. Asking for more is a 400.
PAGE_SIZE = 100

#: A guard, not a claim: the catalog is 825 listings, or nine pages.
MAX_PAGES = 40

#: Only the fields this reader uses. The full record carries Yoast's rendered
#: ``<head>`` for every listing, which is most of the payload and none of the
#: information.
ITEM_FIELDS = "id,slug,link,title,content,meta,featured_media,item-category,country"

#: How many media ids to resolve in one request. The ids are short, so a
#: hundred of them is a query string of a few hundred characters.
MEDIA_BATCH = 100

TAG_RE = re.compile(r"<[^>]+>")

#: The status the shop uses for something it will still sell you. Anything else
#: is treated as gone -- see item_from_record for why that way round.
AVAILABLE = "available"

#: A price text that says nothing the number does not. "$100" beside a price of
#: 100 is noise; "$7 each or 3 for $20" beside a price of 7 is the rest of the
#: offer, and is kept.
PLAIN_PRICE_RE = re.compile(r"^\$\s?[\d,]+(?:\.\d{2})?$")


def text_of(fragment: str) -> str:
    """The readable text of a fragment of rendered WordPress HTML."""
    stripped = TAG_RE.sub(" ", fragment or "")
    return " ".join(html_lib.unescape(stripped).replace("\xa0", " ").split())


def _rendered(value: Any) -> str:
    """WordPress wraps its HTML fields as ``{"rendered": "..."}``."""
    if isinstance(value, dict):
        return text_of(str(value.get("rendered") or ""))
    return text_of(str(value or ""))


def _meta(record: dict[str, Any]) -> dict[str, Any]:
    """A record's meta bag. Absent rather than null when a plugin field is."""
    meta = record.get("meta")
    return meta if isinstance(meta, dict) else {}


def _price_of(meta: dict[str, Any]) -> float | None:
    """The asking price, which the shop has already reduced to a number.

    Four listings have none -- they are the "availability and pricing by
    inquiry" entries for a box of parts -- and those are priceless rather than
    free, so None it is.
    """
    raw = meta.get("_ebay_price")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw) or None


def _slug_of(url: str) -> str:
    """The slug in ``/item/<slug>/``, or the fragment of a pre-migration URL.

    The fallback is the transition: a listing stored before the new site went
    up has a URL of ``bayonetsa_f.htm#18782``, and that fragment is the stock
    number, which is now the slug. So a watchlist entry keeps working between
    the migration and the next full scan, without which its next check would
    read nothing and go quiet.
    """
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) >= 2 and segments[-2] == "item":
        return segments[-1]
    return parts.fragment


class EBayonetScraper(SiteScraper):
    #: Hands over the vendor's own caliber, country or maker. See SiteScraper.
    states_facts = True
    slug = "ebayonet"
    name = "eBayonet"
    base_url = SITE_BASE
    description = (
        "Bayonet specialist, with a sideline in antique gun parts, helmets and "
        "militaria. WordPress, read through its public REST API."
    )
    requires_browser = False
    default_interval_minutes = 1440

    # -- talking to WordPress ------------------------------------------------
    def _json(self, ctx: ScrapeContext, url: str) -> Any:
        raw = ctx.get_text(url)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ScrapeError(f"GET {url}: expected JSON, got something else ({exc})") from exc

    def _terms(self, ctx: ScrapeContext, url: str, label: str) -> dict[int, str]:
        """One taxonomy, as ``{term id: name}``.

        A taxonomy that cannot be read costs names, not listings: every item
        still has its id, and the run goes on without the word for it.
        """
        try:
            rows = self._json(
                ctx, f"{url}?{urlencode({'per_page': PAGE_SIZE, '_fields': 'id,name'})}"
            )
        except Exception as exc:
            ctx.warn(f"could not read the {label} list: {exc}")
            return {}
        if not isinstance(rows, list):
            ctx.warn(f"the {label} list was not a list; carrying on without the names.")
            return {}
        return {
            row["id"]: text_of(str(row.get("name") or ""))
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("id"), int)
        }

    def _records(self, ctx: ScrapeContext) -> Iterator[list[dict[str, Any]]]:
        """Every page of the catalog, a hundred listings at a time.

        Stops on the first short page rather than asking for one more and
        reading the refusal: WordPress answers a page past the end with a 400,
        and a reader that walks into that every single run cannot tell the
        ordinary end of the catalog from the shop being broken.
        """
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            query = urlencode(
                {
                    "per_page": PAGE_SIZE,
                    "page": page,
                    "orderby": "id",
                    "order": "asc",
                    "_fields": ITEM_FIELDS,
                }
            )
            rows = self._json(ctx, f"{ITEMS_API}?{query}")
            if not isinstance(rows, list):
                raise ScrapeError(f"page {page} of the catalog was not a list of listings.")
            if rows:
                yield [row for row in rows if isinstance(row, dict)]
            if len(rows) < PAGE_SIZE:
                return
        ctx.warn(
            f"stopped after {MAX_PAGES} pages of {PAGE_SIZE}; the catalog is larger than "
            f"this reader expects it to be."
        )

    def _media(self, ctx: ScrapeContext, wanted: list[int]) -> dict[int, str]:
        """Resolve media ids to their URLs, in batches.

        The gallery is stored as ids, so this is the one join the API does not
        do for us. Only the ids actually referenced are asked for -- the media
        library is 3,110 rows and most of a reader's politeness budget would go
        on fetching the site's own furniture.
        """
        urls: dict[int, str] = {}
        for start in range(0, len(wanted), MEDIA_BATCH):
            ctx.check_stop()
            batch = wanted[start : start + MEDIA_BATCH]
            query = urlencode(
                {
                    "include": ",".join(str(one) for one in batch),
                    "per_page": MEDIA_BATCH,
                    "_fields": "id,source_url",
                }
            )
            try:
                rows = self._json(ctx, f"{MEDIA_API}?{query}")
            except Exception as exc:
                # Photographs are the most skippable thing here: the listings
                # are already in hand and a picture short is not a listing
                # short. The run says so and keeps the rest.
                ctx.warn(f"could not resolve {len(batch)} photograph(s): {exc}")
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), int):
                    source = str(row.get("source_url") or "")
                    if source:
                        urls[row["id"]] = source
        return urls

    # -- reading one listing -------------------------------------------------
    def item_from_record(
        self,
        record: dict[str, Any],
        categories: dict[int, str],
        countries: dict[int, str],
        media: dict[int, str],
        unknown_statuses: set[str],
    ) -> ScrapedItem | None:
        key = str(record.get("slug") or "").strip()
        title = _rendered(record.get("title"))
        if not key or not title:
            return None

        meta = _meta(record)
        status = str(meta.get("_ebay_status") or "").strip().lower()
        if status and status != AVAILABLE:
            unknown_statuses.add(status)

        # **Anything that is not "available" is treated as gone**, rather than
        # only the literal word "sold". Today every one of the 825 says
        # available, so the other values are unknown -- and of the two ways to
        # be wrong about a word we have never seen, showing something as for
        # sale that is not sends somebody to a dead listing, while the reverse
        # shows it as sold on a page that says otherwise. The scan names the
        # word it did not know, so an invented one gets noticed rather than
        # silently swallowed.
        sold = bool(status) and status != AVAILABLE

        gallery = [one for one in (meta.get("_ebay_gallery") or []) if isinstance(one, int)]
        featured = record.get("featured_media")
        if isinstance(featured, int) and featured and featured not in gallery:
            gallery.insert(0, featured)
        photos = [media[one] for one in gallery if one in media]

        def first_term(field: str, names: dict[int, str]) -> str | None:
            ids = [one for one in (record.get(field) or []) if isinstance(one, int)]
            for one in ids:
                if names.get(one):
                    return names[one]
            return None

        category = first_term("item-category", categories)
        country = first_term("country", countries)
        price = _price_of(meta)

        extra: dict[str, Any] = {}
        price_text = str(meta.get("_ebay_price_text") or "").strip()
        if price_text and not PLAIN_PRICE_RE.match(price_text):
            extra["price_note"] = price_text
        stock = str(meta.get("_ebay_stock") or "").strip()
        if stock and stock != key:
            # Worth keeping where it differs from the key: it is what the shop
            # writes on the tag, and it is what somebody emailing them quotes.
            extra["stock_number"] = stock

        derived = classify.enrich(
            title,
            _rendered(record.get("content")) or None,
            price,
            country=country,
            category=category,
        )
        return ScrapedItem(
            external_key=key,
            url=str(record.get("link") or f"{SITE_BASE}item/{key}/"),
            title=title,
            price=price,
            description=_rendered(record.get("content")) or None,
            category=category,
            caliber=derived["caliber"],
            country=derived["country"],
            manufacturer=derived["manufacturer"],
            is_sold=sold,
            image_urls=photos,
            images_are_complete=True,
            extra=extra,
        )

    # -- the two entry points ------------------------------------------------
    def check_price(
        self, ctx: ScrapeContext, url: str, *, key: str | None = None
    ) -> PriceCheck | None:
        """One listing's price, asked for by slug.

        The old site had no product pages, so this used to re-fetch a whole
        country page and re-parse it to answer about one bayonet. There is an
        endpoint for it now: one request, filtered by the slug, and the price
        arrives as a number nobody has to read out of prose.
        """
        wanted = key or _slug_of(url)
        if not wanted:
            return None
        query = urlencode({"slug": wanted, "_fields": "slug,meta"})
        rows = self._json(ctx, f"{ITEMS_API}?{query}")
        if not isinstance(rows, list) or not rows:
            # Gone from the catalog. The daily scan is what marks a listing
            # de-listed; this one stays quiet rather than guessing.
            return None
        meta = _meta(rows[0])
        price = _price_of(meta)
        if price is None or price <= 0:
            return None
        status = str(meta.get("_ebay_status") or "").strip().lower()
        return PriceCheck(price=price, sold_out=bool(status) and status != AVAILABLE)

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        ctx.log("Reading the catalog…")
        categories = self._terms(ctx, ITEM_CATEGORY_API, "category")
        countries = self._terms(ctx, COUNTRY_API, "country")

        records: list[dict[str, Any]] = []
        try:
            for batch in self._records(ctx):
                records.extend(batch)
                ctx.log(f"Read {len(records)} listing(s)…")
        except ScrapeCanceled:
            # Being told to stop is not the catalog failing. Letting the
            # catch-all below turn it into a PARTIAL run would report a
            # cancellation as a fault with the shop.
            raise
        except Exception as exc:
            if not records:
                # Nothing at all: the shop, not this reader. Said plainly,
                # because the morning their certificate lapsed somebody went
                # looking for a parser bug that did not exist.
                raise ScrapeError(f"no eBayonet listing could be read: {exc}") from exc
            # Some of it. Every category is declared unread, because the API
            # pages by id and the page that failed could have held any of them
            # -- naming only the ones already seen would de-list whatever was
            # in the gap.
            ctx.warn(f"the catalog stopped partway through at {len(records)} listing(s): {exc}")
            for name in categories.values():
                ctx.not_read(name)

        if not records:
            raise ScrapeError(
                "the eBayonet catalog answered and held no listings at all, which is "
                "this reader rather than the shop."
            )

        wanted: list[int] = []
        for record in records:
            meta = _meta(record)
            wanted += [one for one in (meta.get("_ebay_gallery") or []) if isinstance(one, int)]
            featured = record.get("featured_media")
            if isinstance(featured, int) and featured:
                wanted.append(featured)
        media = self._media(ctx, list(dict.fromkeys(wanted)))
        ctx.log(f"Resolved {len(media)} photograph(s).")

        unknown_statuses: set[str] = set()
        items: list[ScrapedItem] = []
        for record in records:
            item = self.item_from_record(record, categories, countries, media, unknown_statuses)
            if item is not None:
                items.append(item)

        if unknown_statuses:
            ctx.warn(
                f"listing status(es) this reader does not know: "
                f"{', '.join(sorted(unknown_statuses))}. They have been treated as no "
                f"longer for sale."
            )
        if not items:
            raise ScrapeError(
                f"{len(records)} eBayonet record(s) were read and none of them became a "
                f"listing, which is this reader rather than the shop."
            )
        ctx.log(f"Parsed {len(items)} listing(s).")
        return items
