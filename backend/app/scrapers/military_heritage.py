"""Military Heritage (militaryheritage.com).

Access Heritage's reproduction arms, from Quebec: matchlocks, Brown Besses,
Charlevilles, Springfields, carbines, blunderbusses and the pistols that went
with them -- 60 on 2026-10-25. Every one is "supplied in a non-firing state"
with the vent left undrilled, so it can be shipped to the door; drilling the
vent is what the buyer does. Asked for on 2026-10-24 and measured then.

**No price, and no stock.** The pages say "Price available when connected":
both come from the shop's ``api/checkout.php``, which robots.txt disallows
(``Disallow: /api/``), and the scanner honors robots.txt. So the walk takes
what the pages publish -- title, model code, summary, specifications, history
and photographs -- and nothing else. Asked for on 2026-10-25 that way: "add
the military heritage stuff without prices (mark them as 'view on site for
price')". Every listing is therefore unpriced (``unpriced_label`` says why on
the page) and reads as available: there is no way to know otherwise.

**The catalog is one page.** ``muskets.htm`` lists every gun as a card with
its model code, title, one-line summary and a link to its page; a card can
appear twice (once per collection the page groups it under), two guns can
share one page (pistol1.htm sells the 12-inch and 9-inch Sea Service
pistols), and three cards link only to a photograph. The product pages are
read once per listing, for the description and the gallery.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

SITE_BASE = "https://militaryheritage.com/"
CATALOG = f"{SITE_BASE}muskets.htm"

#: The card's kind, as the shop files it, to this application's section.
_SECTIONS = {
    "musket": "Muzzleloading Muskets",
    "blunderbuss": "Muzzleloading Muskets",
    "pistol": "Muzzleloading Pistols",
}
_PAGE = re.compile(r"\.html?$", re.I)
_SMALL = re.compile(r"_small(?=\.\w+$)", re.I)


def catalog_items(page: str) -> list[ScrapedItem]:
    """Every gun on the catalog page, once each."""
    soup = BeautifulSoup(page, "html.parser")
    found: dict[str, ScrapedItem] = {}
    for card in soup.select("tr.ah-product-card[data-product-kind]"):
        item = item_from_card(card)
        if item is not None and item.external_key not in found:
            found[item.external_key] = item
    return list(found.values())


def item_from_card(card: Tag) -> ScrapedItem | None:
    sku_node = card.select_one(".ah-card-sku")
    title_node = card.select_one("h3")
    sku = normalize_whitespace(sku_node.get_text(" ", strip=True)) if sku_node else ""
    title = normalize_whitespace(title_node.get_text(" ", strip=True)) if title_node else ""
    if not sku or not title:
        return None
    link = card.select_one("a[href]")
    href = link.get("href") if link is not None else None
    target = urljoin(CATALOG, href) if isinstance(href, str) else CATALOG
    # A card that links only to a photograph has no page of its own; the
    # catalog is where it is sold.
    url = target if _PAGE.search(urlparse(target).path) else CATALOG
    summary = card.select_one(".ah-card-summary")
    image = card.select_one("picture source:not([type]), img")
    src = image.get("srcset") or image.get("src") if image is not None else None
    photos = [_SMALL.sub("", urljoin(CATALOG, src))] if isinstance(src, str) and src else []
    return ScrapedItem(
        external_key=f"mh-{sku}",
        url=url,
        title=title,
        price=None,
        description=normalize_whitespace(summary.get_text(" ", strip=True)) if summary else None,
        category=_SECTIONS.get(str(card.get("data-product-kind")), "Muzzleloading Muskets"),
        image_urls=photos,
        images_are_complete=False,
        is_new=True,
        extra={"sku": sku, "has_page": url != CATALOG},
    )


def detail_from(page: str, page_url: str) -> tuple[str | None, list[str]]:
    """A product page's description and photographs."""
    soup = BeautifulSoup(page, "html.parser")
    main = soup.select_one("main") or soup
    parts = [
        normalize_whitespace(node.get_text(" ", strip=True))
        for node in main.select(
            ".ah-product-description, .ah-product-state, .ah-spec-list, "
            ".ah-technical-copy, .ah-story-copy"
        )
    ]
    description = "\n\n".join(part for part in parts if part) or None
    photos: list[str] = []
    gallery = main.select_one("section.ah-inspection") or main
    for anchor in gallery.select("a[href]"):
        href = anchor.get("href")
        if isinstance(href, str) and re.search(r"\.(?:jpe?g|png|webp)$", href, re.I):
            url = urljoin(page_url, href)
            if url not in photos:
                photos.append(url)
    return description, photos


class MilitaryHeritageScraper(SiteScraper):
    slug = "military-heritage"
    name = "Military Heritage"
    base_url = SITE_BASE
    description = (
        "Quebec maker of reproduction muskets, carbines, blunderbusses and pistols, "
        "shipped with the vent undrilled. No prices published: view on their site."
    )
    requires_browser = False
    default_interval_minutes = 1440
    #: Reproductions made new.
    sells = "new"
    #: What a listing with no price says instead of "Call for price".
    unpriced_label = "View on site for price"
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-25"
    shipping_note = (
        "Shipping by UPS, FedEx or post, quoted at checkout; prices and stock "
        "appear only on their site"
    )
    shipping_source = f"{SITE_BASE}ordering.htm"
    min_request_delay: float = 3.0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        items = catalog_items(ctx.get_text(CATALOG))
        if not items:
            raise ScrapeError("The catalog page listed no guns.")
        ctx.log(f"Catalog: {len(items)} gun(s).")
        pages: dict[str, tuple[str | None, list[str]]] = {}
        for item in items:
            ctx.check_stop()
            if item.extra.get("has_page") and ctx.needs_detail(item.external_key):
                page_url = item.url.split("?")[0]
                if page_url not in pages and ctx.allowed(page_url):
                    try:
                        pages[page_url] = detail_from(ctx.get_text(page_url), page_url)
                    except ScrapeError as exc:
                        ctx.warn(f"Could not read {page_url}: {exc}")
                        pages[page_url] = (None, [])
                description, photos = pages.get(page_url, (None, []))
                if description:
                    item.description = description
                if photos:
                    item.image_urls = photos
                item.images_are_complete = True
            elif not item.extra.get("has_page"):
                # Nothing more to read: the card is all there is.
                item.images_are_complete = True
            yield item
