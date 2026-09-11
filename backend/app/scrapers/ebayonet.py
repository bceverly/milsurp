"""eBayonet (ebayonet.com).

**No e-commerce platform at all**, and the first vendor here with none: an
Apache server, five hand-maintained pages, and no ``robots.txt`` (it 404s,
which the crawler reads as no restrictions). The pages were saved out of
Microsoft Word -- ``MsoNormal`` classes and ``<o:p>`` tags throughout -- so the
markup carries no product structure whatsoever. There is no product page for
anything: the catalog *is* these five files.

**A listing is a run of paragraphs, not one paragraph.** That is the whole
shape, and reading only the first paragraph is what makes this site look like a
catalog with no prices:

    <p>18782 Afghan issued P1903 bayonet with scabbard. WILKINSON-LONDON. …</p>
    <p>https://ebayonet.com/18700/18782.jpg</p>
    <p>https://ebayonet.com/18700/18782a.jpg</p>
    <p>$110</p>

Measured over all five pages: 736 listings, of which **725 carry a price (99%)
and 722 carry photographs (98%)**. Reading the price only from the paragraph
that opens the listing finds it on 11% of them, which was the first measurement
taken here and was wrong.

**The photographs are text, not markup.** There is not one ``<img>`` tag in a
megabyte of HTML -- the pictures are bare URLs typed into the prose, which is
why a count of image tags says this site has no photographs.

**The stock number is the key.** Five digits, first thing in the opening
paragraph, stable across edits of the description, and the only identifier the
site offers. It is also how the photo URLs are organized: ``18782`` lives under
``/18700/``.

**Bayonets only**, which is the point of the site and is why it is worth having
despite being the smallest kind of vendor here: nothing else on this list is a
specialist, and ``classify`` already has a bayonet bucket for them to land in.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper

SITE_BASE = "https://www.ebayonet.com/"

#: The catalog, split by the country initial of the bayonet's origin. There is
#: no index page listing these; they are linked from the site's own frames-era
#: navigation and are stable enough to name here.
PAGES: tuple[str, ...] = (
    "bayonetsa_f.htm",
    "bayonetsg.htm",
    "bayonetsh_m.htm",
    "bayonetsn_s.htm",
    "bayonetst_z.htm",
)

#: A paragraph that opens a listing: a stock number, then a space, then
#: something that is not another digit. The trailing lookahead matters -- a
#: measurement written "1907 15 bayonet" would otherwise read as stock 1907.
STOCK_RE = re.compile(r"^(\d{4,6})\s+(?=\D)")

#: A price. Written plainly -- "$110", "$1,250", "$7 each or 3 for $20" -- and
#: the first one is the asking price for the piece.
PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")

#: A photograph, typed into the prose as a bare URL.
PHOTO_RE = re.compile(r"https?://(?:www\.)?ebayonet\.com/\d+/[\w.-]+\.jpe?g", re.IGNORECASE)

SOLD_RE = re.compile(r"\bSOLD\b", re.IGNORECASE)

#: A pointer to the real listing rather than a listing. A bayonet used by two
#: countries appears on both of their pages -- once in full, and once as
#: "15450 Mukden Mauser bayonet. SEE LISTING UNDER MANCHUKUO." Eleven stock
#: numbers are duplicated that way, and keeping both collapses them on upsert:
#: the external key is the stock number, so the pointer would overwrite the
#: listing or the other way round depending on which page was read last.
CROSS_REFERENCE_RE = re.compile(r"(?i)\bsee\s+listing\s+under\b")
PARAGRAPH_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")

#: Below this a paragraph opening with digits is a note or a measurement rather
#: than a listing. The shortest real one measured is a little over thirty
#: characters; twenty-five leaves room without letting prose in.
MIN_TITLE = 25

#: How long a paragraph can be and still be read as *only* a price. A listing's
#: own prose mentions prices of other things ("I have a scant few of these with
#: the original locking pin $10 each"), and taking the first dollar sign
#: anywhere would price a bayonet at the cost of its locking pin.
MAX_PRICE_PARAGRAPH = 120


def text_of(fragment: str) -> str:
    """The readable text of a fragment of Word's HTML.

    Word fills these pages with ``&nbsp;`` and splits runs mid-word with
    ``<span>``, so the tags come out before the entities and the whitespace is
    collapsed afterwards.
    """
    stripped = TAG_RE.sub(" ", fragment)
    return " ".join(html_lib.unescape(stripped).replace("\xa0", " ").split())


def _price(text: str) -> float | None:
    match = PRICE_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:  # pragma: no cover - the pattern only matches numbers
        return None


def parse_page(html_text: str, page: str) -> list[ScrapedItem]:
    """Every listing on one of the five pages.

    Walks the paragraphs in order, opening a listing at each stock number and
    closing it at the next one. Everything between belongs to the listing that
    is open: its photographs, the rest of its description, and its price.
    """
    items: list[ScrapedItem] = []
    key: str | None = None
    title = ""
    description: list[str] = []
    photos: list[str] = []
    price: float | None = None
    sold = False

    def close() -> None:
        nonlocal key
        if key is None:
            return
        items.append(
            ScrapedItem(
                external_key=key,
                # No product page exists, so a listing points at the page it is
                # on. The fragment is not a real anchor -- Word wrote none --
                # but it records which of the five to look on.
                url=f"{SITE_BASE}{page}#{key}",
                title=title,
                price=price,
                description=" ".join(description) or None,
                category="Bayonet",
                is_sold=sold,
                image_urls=list(dict.fromkeys(photos)),
                images_are_complete=True,
            )
        )
        key = None

    for fragment in PARAGRAPH_RE.findall(html_text):
        text = text_of(fragment)
        if not text:
            continue
        opening = STOCK_RE.match(text)
        if opening and len(text) >= MIN_TITLE:
            close()
            key = opening.group(1)
            title = text
            description = []
            photos = PHOTO_RE.findall(fragment)
            price = _price(text)
            sold = bool(SOLD_RE.search(text))
            continue
        if key is None:
            continue
        photos += PHOTO_RE.findall(fragment)
        if price is None and len(text) <= MAX_PRICE_PARAGRAPH:
            price = _price(text)
        if SOLD_RE.search(text):
            sold = True
        # A bare photo URL is not prose worth keeping in the description.
        if not PHOTO_RE.fullmatch(text):
            description.append(text)

    close()
    return _without_cross_references(items)


def _without_cross_references(items: list[ScrapedItem]) -> list[ScrapedItem]:
    """One row per stock number, keeping the listing over the pointer.

    Marked ones go first, because the site says so itself. What is left is
    settled on evidence: a real listing carries a price and photographs and a
    pointer carries neither, so the richer row wins. Three copies of 15379 on
    one page are the same thing without the marker.
    """
    best: dict[str, ScrapedItem] = {}
    for item in items:
        if CROSS_REFERENCE_RE.search(item.title):
            continue
        seen = best.get(item.external_key)
        if seen is None or _weight(item) > _weight(seen):
            best[item.external_key] = item
    return list(best.values())


def _weight(item: ScrapedItem) -> tuple[int, int, int]:
    """How much of a listing this row is: priced, pictured, and described."""
    return (
        1 if item.price is not None else 0,
        len(item.image_urls),
        len(item.description or ""),
    )


class EBayonetScraper(SiteScraper):
    slug = "ebayonet"
    name = "eBayonet"
    base_url = SITE_BASE
    description = (
        "Bayonet specialist. Five hand-maintained pages of prose, split by the "
        "country initial, with no product pages and no storefront behind them."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        items: list[ScrapedItem] = []
        for page in PAGES:
            ctx.check_stop()
            ctx.log(f"Fetching {page}…")
            try:
                html_text = ctx.get_text(f"{SITE_BASE}{page}")
            except Exception as exc:
                # One page of five is one country range, not the catalog. The
                # run reports PARTIAL rather than losing the other four.
                ctx.warn(f"could not fetch {page}: {exc}")
                continue
            parsed = parse_page(html_text, page)
            ctx.log(f"Parsed {len(parsed)} listing(s) from {page}.")
            items.extend(parsed)

        # Again across the whole catalog, not only within a page: a bayonet
        # carried by two countries is written out on both of their pages, and
        # parse_page can only see one of them at a time.
        items = _without_cross_references(items)

        if not items:
            raise ScrapeError("every eBayonet page failed to parse")
        return items
