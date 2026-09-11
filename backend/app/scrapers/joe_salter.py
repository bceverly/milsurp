"""Joe Salter (shop.joesalter.com).

**OpenCart, the seventh platform here**, and a long-established collector
dealer: 280-odd firearms across the five sections this reads, **every one of
them priced**, which no other vendor here manages.

**The photographs depend on a configured exception.** Their robots.txt is short
and specific::

    User-agent: *
    Disallow: /files
    Disallow: /image

Every product image OpenCart serves lives under ``/image/cache/catalog/…``, so
the whole gallery is out of bounds by default, and this crawler obeys
robots.txt (see ``app/robots.py``). Out of the box the listings therefore
arrive with prices, descriptions, calibers and no pictures.

A deployment that has settled the question with the vendor can grant a narrow
exception in ``config.yaml`` -- see ``RobotsException`` in ``app/config.py`` --
and the gallery is then read. **Which way this goes is decided entirely by
configuration, never here**: this module asks ``ctx.allowed()`` and believes
the answer, so the default stays "obey" and the exception stays visible in one
file somebody can review.

**The catalog page carries the whole listing.** A product tile holds the stock
number, the title, the price and a truncated description -- so the catalog walk
alone is a complete record, and the detail fetch exists only to replace the
truncation with the full text and to read the availability. That ordering
matters because it is what makes a failed detail page cost nothing: the listing
is already whole.

**The stock number is the key.** "Item #: 53643" on both the tile and the
product page: the dealer's own number, stable across a re-title, and the only
identifier the URLs do not carry.

**The shop's own count is higher than the shop's own pages.** "Showing 1 to 15
of 116" sits above a page carrying fourteen, and reading all eight pages of that
section yields 102, not 116. Asking for ``?limit=100`` yields the same 102 --
so the fourteen are not lost in pagination, they are counted by the storefront
and not rendered by it. This reads what is there and treats the stated total as
a remark rather than a target; believing it would either drop a page or hunt
forever for listings the shop is not serving.
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

SITE_BASE = "https://shop.joesalter.com/"

#: The sections worth reading, and why these and not the other fifty-odd.
#:
#: Joe Salter is a general collector dealer -- the catalog runs from cap guns
#: and cavalry spurs to Civil War memorabilia -- and the standing rule here is
#: firearms and parts kits, so the militaria, paper and accessory trees are
#: left alone.
#:
#: **Their sections are cut on two different axes, and only one of them is
#: safe.** Sections named for a *form* -- "Military Longarms", "Antique
#: Handguns" -- hold guns and nothing else. Sections named for a *country* or a
#: *maker* hold everything that country or maker ever touched: "British
#: Military" was read here first and it was **71% not-a-gun** -- uniforms, cap
#: badges, binoculars, riding spurs, bullet molds, books, boxes of blanks --
#: against 3-12% for the form-cut sections. Its own URL says so
#: ("...holsters-militaria-Enfield") and that should have been read as a
#: warning rather than a list of contents. "Enfield Rifles, Revolvers Etc",
#: "Webley" and "Lugers" are cut the same way and are out for the same reason:
#: the first page of Lugers is mostly magazines and holsters.
SOURCES: tuple[dict[str, str], ...] = (
    {
        "category": "Curio & Relic",
        "url": f"{SITE_BASE}CandR-Firearms-curio-and-relic-handguns-rifles",
    },
    {
        "category": "Antique Handgun",
        "url": f"{SITE_BASE}Antique-Handguns-flintlock-percussion-pre-1898-muzzleloader",
    },
    {
        "category": "Antique Long Gun",
        "url": f"{SITE_BASE}Antique-Longguns-flintlock-percussion-pre-1898-muzzleloader",
    },
    {"category": "Military Long Gun", "url": f"{SITE_BASE}Military-Longarms"},
    {"category": "Military Handgun", "url": f"{SITE_BASE}Military-Handguns"},
)

#: Listings per request. OpenCart honors ``?limit``, and the default of fifteen
#: turns a 116-listing section into eight fetches for no gain to anybody.
PAGE_SIZE = 100

#: How many catalog pages one section may have, at PAGE_SIZE each. A guard
#: against a pagination link that always points forward, not a claim about the
#: catalog's size.
MAX_PAGES = 20

#: One product tile. OpenCart's stock markup, which this shop has not themed
#: away.
TILE_RE = re.compile(r'<div class="product-thumb.*?</div>\s*</div>\s*</div>', re.DOTALL)
ITEM_NUMBER_RE = re.compile(r"(?i)item\s*#\s*:?\s*([\w-]+)")
PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
HREF_RE = re.compile(r'href="(https?://shop\.joesalter\.com/[^"?#]+)(?:[?#][^"]*)?"')
TAG_RE = re.compile(r"<[^>]+>")

#: "Showing 1 to 15 of 116" -- the shop's own count, which overstates what the
#: shop's own pages carry. Read only to report the shortfall; see the module
#: docstring for why it is not a stopping condition.
TOTAL_RE = re.compile(r"(?i)showing\s+\d+\s+to\s+\d+\s+of\s+(\d+)")

OUT_OF_STOCK_RE = re.compile(r"(?i)availability\s*:?\s*(out\s+of\s+stock|sold)")

#: The dealer's spec preamble, which every gun he lists carries and no book
#: does: "Serial #8013, .32 S&W, 3 inch round ribbed barrel" or, for a piece
#: with no number, "NSN, .54 Caliber, 8 1/4 inch barrels". It sits at the front
#: of the description, so the catalog tile carries it even truncated.
SPEC_RE = re.compile(r"(?i)\b(?:serial\s*#|serial\s+number|nsn)\b")

#: Below this, a listing with no spec preamble is a book. Joe Salter
#: cross-lists the reference works into the gun sections they are about -- "The
#: Blunderbuss History & Development" sits in Antique Long Guns -- and they are
#: the only things left in a form-cut section that are not firearms.
#:
#: Measured over the 217 listings the three original sections hold: five books
#: at $12.95-$29.95, all without the preamble, and the cheapest gun that
#: carries one at $195. Two items lack the preamble and are not books -- a
#: bronze mortar at $4,195 and a Winchester Model 1906 at $1,195 -- which is
#: why the price is half the rule rather than the whole of it, and why the
#: preamble is half rather than the whole: on its own it would drop both.
#: Either signal alone is wrong; together there is a gap from $30 to $195 to
#: put the line in.
MIN_FIREARM_PRICE = 50.0


#: What a book says about itself. Seven real guns in the catalog match one of
#: these -- a rifle "published" in a reference work, a cased revolver -- and
#: every one of them carries the spec preamble, which is why this is only ever
#: half of a decision.
PAPER_RE = re.compile(
    r"(?i)\b(?:hard\s*cover|soft\s*cover|paperback|dust\s*jacket|\d+\s+pages|"
    r"reprint|catalogue|book)\b"
)


def _is_a_gun(text: str, price: float | None) -> bool:
    """Whether a tile is a firearm rather than a book about one.

    The spec preamble decides it on its own when present: every gun he lists
    has one and no book does. Without it, a second signal has to agree --
    a price below what any gun here costs, or the listing describing itself as
    a book. Either signal alone is wrong: the preamble alone drops a bronze
    mortar at $4,195 and a Winchester at $1,195, and the paper words alone drop
    seven rifles whose claim to fame is being published in one.
    """
    if SPEC_RE.search(text):
        return True
    if price is not None and price < MIN_FIREARM_PRICE:
        return False
    return not PAPER_RE.search(text)


#: Detail pages that may fail before the rest of the scan gives up on them.
MAX_DETAIL_FAILURES = 5


def text_of(fragment: str) -> str:
    return " ".join(html_lib.unescape(TAG_RE.sub(" ", fragment)).replace("\xa0", " ").split())


def _price(text: str) -> float | None:
    match = PRICE_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:  # pragma: no cover - the pattern only matches numbers
        return None


def parse_catalog(html_text: str, category: str) -> list[ScrapedItem]:
    """The listings on one catalog page."""
    items: list[ScrapedItem] = []
    for tile in TILE_RE.findall(html_text):
        text = text_of(tile)
        number = ITEM_NUMBER_RE.search(text)
        # Without the query string. OpenCart's theme pastes the *catalog* page's
        # own parameters onto every product link, so reading a section with
        # ?limit=100 stores a hundred product URLs ending in "?limit=100" --
        # which work, but make the listing's address depend on how the page it
        # was found on happened to be fetched.
        links = HREF_RE.findall(tile)
        if number is None or not links:
            continue
        # The title is what is left once the stock number and the trailing
        # storefront furniture are taken off the front and back of the tile.
        title = ITEM_NUMBER_RE.sub("", text, count=1).strip()
        title = re.split(r"(?i)\.\.\.\s*\(\s*read more\s*\)|\bAdd To Cart\b", title)[0].strip()
        if not title:
            continue
        price = _price(text)
        if not _is_a_gun(text, price):
            continue
        items.append(
            ScrapedItem(
                external_key=number.group(1),
                url=links[0],
                title=title,
                price=price,
                category=category,
                # The tile's description is truncated at "... ( read more )".
                # The detail fetch replaces it; until then this is what there is.
                description=None,
                # Their robots.txt disallows /image, where every product
                # photograph lives. Declared complete because there is nothing
                # further to fetch, not because a gallery was read.
                image_urls=[],
                images_are_complete=True,
            )
        )
    return items


class JoeSalterScraper(SiteScraper):
    slug = "joe-salter"
    name = "Joe Salter"
    base_url = SITE_BASE
    description = (
        "Long-established collector dealer on OpenCart. Curio-and-relic, "
        "antique and British military sections are read; their photographs are "
        "disallowed by robots.txt, so listings arrive without pictures."
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
                    # A gun cross-listed in two sections is one gun.
                    continue
                seen.add(item.external_key)
                found.append(item)

        if not found:
            raise ScrapeError("no listings were found in any Joe Salter section")

        ctx.log(f"{len(found)} listing(s); reading the ones that need a detail page.")
        return [self.with_detail(ctx, item) for item in found]

    def _walk(self, ctx: ScrapeContext, source: dict[str, str]) -> Iterable[ScrapedItem]:
        """Every page of one section, stopping when a page comes back empty.

        The obvious stopping condition -- the "of 116" in the shop's own
        "Showing" line -- is the one thing on the page that is not true, so an
        empty page is the end and the total is only reported against.
        """
        taken = 0
        claimed: int | None = None
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            url = f"{source['url']}?limit={PAGE_SIZE}"
            if page > 1:
                url = f"{url}&page={page}"
            try:
                html_text = ctx.get_text(url)
            except Exception as exc:
                ctx.warn(f"could not read {url}: {exc}")
                return
            batch = parse_catalog(html_text, source["category"])
            if not batch:
                break
            yield from batch
            taken += len(batch)
            if claimed is None:
                total = TOTAL_RE.search(text_of(html_text))
                claimed = int(total.group(1)) if total else None
        else:
            ctx.warn(f"{source['category']} stopped at the {MAX_PAGES}-page ceiling.")
            return

        if claimed is not None and taken < claimed:
            # Not a fault to chase: the storefront counts listings it does not
            # render. Logged so a real parsing regression has something to look
            # unusual against.
            ctx.log(f"{source['category']}: {taken} listing(s); the shop says {claimed}.")

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """The full description, the availability, and the gallery if allowed.

        The catalog entry is already whole, so every failure here is survivable
        and none of them costs a listing.
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
                # A single 403 or 404 is the shop stating a policy, not a fault
                # worth making the site permanently PARTIAL over. See
                # base.vendors_answer.
                say = ctx.log if vendors_answer(exc) else ctx.warn
                say(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item

        item.description = _description(html_text) or item.description
        if OUT_OF_STOCK_RE.search(html_text):
            item.is_sold = True
        item.image_urls = _photos(ctx, html_text)
        # Complete either way: with the gallery because it was read, without it
        # because there is nothing further this scan is permitted to fetch. A
        # listing left incomplete would have the photo backfill retrying a path
        # robots.txt refuses, once per scan, forever.
        item.images_are_complete = True
        return item


#: The product page's own description block. OpenCart puts it in a tab pane;
#: this shop's theme leaves the id alone.
DESCRIPTION_RE = re.compile(
    r'<div[^>]+id="tab-description"[^>]*>(.*?)</div>\s*(?:<div|</div>)', re.DOTALL
)


def _description(html_text: str) -> str | None:
    match = DESCRIPTION_RE.search(html_text)
    if match is None:
        return None
    text = text_of(match.group(1))
    return text or None


#: Where this product's own gallery begins. Everything before it is the header
#: and the breadcrumb; everything after the related-products strip belongs to
#: other guns. Without the scope a listing comes back claiming fifty-three
#: photographs, two thirds of them other people's.
GALLERY_START_RE = re.compile(r"<div[^>]*class=['\"]thumbnails[^'\"]*['\"]", re.IGNORECASE)

#: Where it ends: the "you may also like" strip, which is built from the same
#: product tiles as a catalog page.
GALLERY_END_RE = re.compile(r"<div[^>]*class=['\"][^'\"]*product-thumb", re.IGNORECASE)

#: A photograph inside that block.
PHOTO_RE = re.compile(
    r"https://shop\.joesalter\.com/image/cache/catalog/[^\"'\s]+?\.jpe?g", re.IGNORECASE
)

#: The size suffix OpenCart appends: "DSC_6131-1280x720.jpg". Stripped to tell
#: two renderings of one photograph apart, so a listing with eight pictures
#: does not arrive claiming twenty-four.
SIZE_SUFFIX_RE = re.compile(r"-\d{2,4}x\d{2,4}(?=\.jpe?g$)", re.IGNORECASE)


def _photos(ctx: ScrapeContext, html_text: str) -> list[str]:
    """The gallery, largest rendering of each photograph, or nothing.

    Asks the context rather than deciding: ``allowed()`` consults robots.txt
    and then any configured exception, so the default here is no pictures and
    the exception is the only thing that changes it.
    """
    start = GALLERY_START_RE.search(html_text)
    if start is None:
        return []
    end = GALLERY_END_RE.search(html_text, start.end())
    gallery = html_text[start.end() : end.start() if end else len(html_text)]

    found = PHOTO_RE.findall(gallery)
    if not found:
        return []
    if not ctx.allowed(found[0]):
        return []

    # Largest rendering wins. "-1280x720" and "-74x74" are the same photograph
    # at thumbnail and display size, and the number in the name is the only
    # thing that says which is which.
    best: dict[str, tuple[int, str]] = {}
    for url in found:
        name = url.rsplit("/", 1)[-1]
        stem = SIZE_SUFFIX_RE.sub("", name)
        size = SIZE_SUFFIX_RE.search(name)
        width = int(size.group(0).lstrip("-").split("x")[0]) if size else 0
        if stem not in best or width > best[stem][0]:
            best[stem] = (width, url)
    return [url for _width, url in best.values()]
