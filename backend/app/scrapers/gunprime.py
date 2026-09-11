"""GunPrime (gunprime.com).

**Spree on Rails, the eighth platform here**, behind Phusion Passenger. The
markup is Spree's own -- ``data-hook='products_list_item'``, ``id='product_N'``
-- so the catalog needs no browser and no endpoint hunting.

**The scope is the two tags, not the six categories, and that is the whole
decision worth explaining.** ``/categories/firearms/*`` is about 1,300 listings
of Del-Ton AR pistols, Kahr P9s, Mossberg Shockwaves and suppressors. That is a
modern gun shop's inventory, and reading it here would repeat the mistake
Arms Unlimited and Century Arms were backed out for: 97 listings that landed
correctly and none of which belonged in this catalog. What is worth having is
``/tags/collectible`` -- a Colt Python, a matching Mauser P.08 Luger, a
Waffenamt Browning Hi-Power -- and ``/tags/police-trade-in``, the shelf four
other vendors here are already read for. Around 100 listings, every one priced.

**The vendor's own taxonomy does the filtering.** The police tag is 35%
not-a-firearm: ammunition, magazines, duty holsters, a weapon light. Guessing
that from titles is what put bayonets in Rifles elsewhere, and there is no need
to guess -- every product page states its own taxons::

    categories/firearms/pistols/semi-auto-pistols   <- a gun
    categories/ammunition                           <- a box of cartridges
    categories/accessories/firearm                  <- a holster

So a listing is kept when its own categories put it under firearms, and the
same block hands over ``manufacturer/glock`` for the maker at no extra cost.

**The photographs need a configured exception, like Joe Salter's.** Their
robots.txt disallows ``/rails/active_storage/*``, which is where every product
image is served from, so out of the box this vendor ships without pictures.

The product page does also carry a presigned
``gunprime.s3.us-east-2.amazonaws.com`` URL for each photo, and that host has
no robots.txt of its own -- it answers 403, which this crawler reads as "off
limits" rather than as permission. Fetching those to sidestep the rule on the
vendor's own domain would be circumventing it, so this does not: it reads the
``/rails/active_storage/`` URLs, asks ``ctx.allowed()``, and believes the
answer. A deployment that has settled the question with the vendor grants the
exception in ``config.yaml`` -- see ``RobotsException`` in ``app/config.py``.

Those URLs redirect to the same signed S3 object, which is the other reason to
prefer them: the signature expires after seven days and the redirect issues a
fresh one, so a photo that sits in the queue over a weekend still downloads.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    vendors_answer,
)

SITE_BASE = "https://gunprime.com/"

#: The sections worth reading, and why these and not the categories. See the
#: module docstring: the categories are a modern gun shop, the tags are the
#: collector and police shelves.
SOURCES: tuple[dict[str, str], ...] = (
    {"category": "Collectible", "url": f"{SITE_BASE}tags/collectible"},
    {"category": "Police Trade-In", "url": f"{SITE_BASE}tags/police-trade-in"},
)

#: Twelve to a page, and ``per_page`` is ignored on a tag page however politely
#: it is asked. A guard against a "next" link that always points forward.
MAX_PAGES = 30

#: One product tile. Spree's stock markup: the id carries the product's own
#: number, the info span carries the untruncated title, and the price is in a
#: ``content`` attribute rather than only in the rendered "$1,234.00".
TILE_RE = re.compile(
    r"(?s)id='product_(\d+)'"
    r".*?href=\"(/products/[^\"]+)\""
    r".*?<span class=\"info\" title=\"(.*?)\""
    r".*?content='([\d.]+)'"
)

#: The tile's own stock line, so availability costs no detail fetch:
#: ``<span class='product-cart-link red'><i…></i> Out of Stock</span>``.
SOLD_RE = re.compile(r"(?i)product-cart-link[^'\"]*red|>\s*Out of Stock\s*<")

#: The product's own taxons, as opposed to the six category links every page
#: carries in its navigation. Scoped to the block Spree marks as this
#: product's: ``<div id="taxon-crumbs" data-hook="product_taxons">``.
TAXON_BLOCK_RE = re.compile(r'(?s)id="taxon-crumbs".*?</div>\s*</div>')
TAXON_RE = re.compile(r'href="/t/([^"]+)"')

#: What makes a listing a firearm here: the vendor filed it under firearms.
#: Note that "categories/accessories/firearm" -- a holster -- does not match,
#: because the test is on the start of the path.
FIREARM_TAXON = "categories/firearms/"
MAKER_TAXON = "manufacturer/"

#: The description, kept as escaped HTML inside a meta tag rather than rendered
#: into the page. Spree writes the rendered copy through a JavaScript tab, so
#: this is the only place the prose appears in the HTML the crawler receives.
DESCRIPTION_RE = re.compile(r'<meta itemprop="description" content="(.*?)"\s*/?>', re.DOTALL)

#: A product photograph. The vendor's own host, not the S3 URL beside it --
#: see the module docstring for why that distinction is the whole point here.
PHOTO_RE = re.compile(r"https://gunprime\.com/rails/active_storage/[^'\"\s]+", re.IGNORECASE)

TAG_RE = re.compile(r"<[^>]+>")

#: Detail pages that may fail before the rest of the scan gives up on them.
MAX_DETAIL_FAILURES = 5


def text_of(fragment: str) -> str:
    stripped = TAG_RE.sub(" ", fragment)
    return " ".join(html_lib.unescape(stripped).replace("\xa0", " ").split())


def parse_catalog(html_text: str, category: str) -> list[ScrapedItem]:
    """The listings on one page of one tag.

    Everything except the description and the scope decision is here, which is
    what makes a failed product page cost a description rather than a listing.
    """
    items: list[ScrapedItem] = []
    # Split rather than finditer so each tile's stock line is read against that
    # tile alone: the page carries an "Out of Stock" for every sold product and
    # a single scan of the whole document cannot tell which one it belongs to.
    for tile in re.split(r"(?=id='product_\d+')", html_text)[1:]:
        found = TILE_RE.search(tile)
        if found is None:
            continue
        number, path, title, price = found.groups()
        items.append(
            ScrapedItem(
                external_key=number,
                url=f"{SITE_BASE}{path.lstrip('/')}",
                title=html_lib.unescape(title).strip(),
                price=float(price),
                category=category,
                is_sold=SOLD_RE.search(tile) is not None,
                # Filled in from the product page, which is also where the
                # scope decision is made. See JoeSalterScraper.with_detail for
                # the same shape.
                description=None,
                image_urls=[],
                images_are_complete=False,
            )
        )
    return items


def taxons(html_text: str) -> list[str]:
    """This product's own taxons, not the site navigation's."""
    block = TAXON_BLOCK_RE.search(html_text)
    return TAXON_RE.findall(block.group(0)) if block else []


def is_a_firearm(found: Iterable[str]) -> bool:
    return any(taxon.startswith(FIREARM_TAXON) for taxon in found)


def maker_of(found: Iterable[str]) -> str | None:
    """The maker, from the shallowest ``manufacturer/…`` taxon.

    A product carries both ``manufacturer/glock`` and ``manufacturer/glock/22``;
    the first is the maker and the second is the model.
    """
    names = [t[len(MAKER_TAXON) :] for t in found if t.startswith(MAKER_TAXON)]
    if not names:
        return None
    shallowest = min(names, key=lambda name: name.count("/"))
    return shallowest.split("/")[0].replace("-", " ").title() or None


def kind_of(found: Iterable[str]) -> str | None:
    """The firearm type, from the taxon that already carries it.

    ``categories/firearms/pistols/semi-auto-pistols`` says pistol in the
    segment after "firearms". Six of their listings typed as neither rifle nor
    handgun on an accessory word trailing the title -- "Night Sights",
    "FACTORY CASE", "3 Mags" -- and the vendor had said what each one was.
    """
    for taxon in found:
        if not taxon.startswith(FIREARM_TAXON):
            continue
        rest = taxon[len(FIREARM_TAXON) :].split("/")
        if rest and rest[0]:
            # "pistols" -> "pistol": kind_from_category reads either, and the
            # singular is what every other vendor stores.
            return rest[0].rstrip("s").replace("-", " ").title()
    return None


def _description(html_text: str) -> str | None:
    found = DESCRIPTION_RE.search(html_text)
    if found is None:
        return None
    # Escaped HTML inside an attribute: unescape once to get the markup, strip
    # it, and unescape again for the entities that were inside it.
    return text_of(html_lib.unescape(found.group(1))) or None


class GunPrimeScraper(SiteScraper):
    slug = "gunprime"
    name = "GunPrime"
    base_url = SITE_BASE
    description = (
        "Spree storefront. The collector and police trade-in shelves are read; "
        "their six firearm categories are a modern gun shop and are left alone."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def __init__(self) -> None:
        self._detail_failures = 0
        self._gave_up_on_details = False

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        seen: set[str] = set()
        found: list[ScrapedItem] = []

        for source in SOURCES:
            ctx.check_stop()
            ctx.log(f"Reading {source['category']}…")
            for item in self._walk(ctx, source):
                if item.external_key in seen:
                    # A collectible police trade-in carries both tags.
                    continue
                seen.add(item.external_key)
                found.append(item)

        if not found:
            raise ScrapeError("no listings were found under either GunPrime tag")

        ctx.log(f"{len(found)} listing(s); reading their product pages.")
        kept = [item for item in (self.with_detail(ctx, row) for row in found) if item]
        ctx.log(f"{len(kept)} of {len(found)} are firearms; the rest are ammunition and gear.")
        if not kept:
            raise ScrapeError("every GunPrime listing was filtered out as not a firearm")
        return kept

    def _walk(self, ctx: ScrapeContext, source: dict[str, str]) -> Iterable[ScrapedItem]:
        """Every page of one tag, stopping when a page carries no tiles."""
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            url = source["url"] if page == 1 else f"{source['url']}?page={page}"
            try:
                html_text = ctx.get_text(url)
            except Exception as exc:
                ctx.warn(f"could not read {url}: {exc}")
                return
            batch = parse_catalog(html_text, source["category"])
            if not batch:
                return
            yield from batch
        ctx.warn(f"{source['category']} stopped at the {MAX_PAGES}-page ceiling.")

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem | None:
        """The product page: the scope decision, the maker, the prose, the
        gallery. ``None`` means the vendor does not file this under firearms.

        A page that cannot be read keeps the listing rather than dropping it --
        failing to fetch is not evidence that something is ammunition, and the
        catalog tile is already a whole record apart from its description.
        """
        if not ctx.needs_detail(item.external_key) or self._gave_up_on_details:
            return item
        try:
            html_text = ctx.get_text(item.url)
        except Disallowed:
            ctx.log(f"robots.txt disallows {item.url}; keeping the catalog entry only.")
            return item
        except ScrapeError as exc:
            self._detail_failures += 1
            if self._detail_failures >= MAX_DETAIL_FAILURES:
                self._gave_up_on_details = True
                ctx.warn(
                    f"{self._detail_failures} product pages in a row could not be read; "
                    f"taking the rest of this scan from the catalog only. Last error: {exc}"
                )
            else:
                say = ctx.log if vendors_answer(exc) else ctx.warn
                say(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item

        found = taxons(html_text)
        if found and not is_a_firearm(found):
            return None

        item.manufacturer = item.manufacturer or maker_of(found)
        item.stated_kind = kind_of(found)
        item.description = _description(html_text) or item.description
        item.image_urls = _photos(ctx, html_text)
        item.images_are_complete = True
        return item


def _photos(ctx: ScrapeContext, html_text: str) -> list[str]:
    """The gallery, or nothing.

    Asked of the context rather than decided here, exactly as Joe Salter's is:
    robots.txt disallows the path, so the default is no pictures and a
    configured exception is the only thing that changes it.
    """
    found = list(dict.fromkeys(html_lib.unescape(url) for url in PHOTO_RE.findall(html_text)))
    if not found or not ctx.allowed(found[0]):
        return []
    return found
