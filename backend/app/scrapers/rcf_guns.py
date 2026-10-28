"""RCF Guns -- River City Firearms, Mt. Washington, Kentucky (rcfguns.com).

Added on 2026-10-28 with the used-gun shops asked for to catch used carry
pistols: the largest used shelf found, 264 handguns and 109 long guns that
day, and the highest share of carry guns of any shop measured.

**It is a photo gallery, not a store.** The site is built with Duda: each
section is one page of gallery tiles, a photograph with the price as its
caption title ("189.99") and a sentence as its caption ("Preowned Taurus G3C
9MM with 3 mags."). There is no product page, no cart and no stock state --
a gun that sells simply leaves the gallery -- and nothing on the site about
shipping or ordering online, so it reads as an in-store shop, and each
listing links to the gallery it is in. The photograph's file name
(``IMG_2306-e8d49ce8.jpeg``) is the only thing a tile has that stays put, so
it is the key. robots.txt names a sitemap and disallows nothing.

Read: the used handguns (``/used-guns``) and the used long guns, which the
site's own menu labels "Used Long Guns" and keeps at ``/accessories``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from bs4 import BeautifulSoup, Tag

from .base import (
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
    parse_price,
)

SITE_BASE = "https://www.rcfguns.com/"
SOURCES = (
    ("Used Handguns", f"{SITE_BASE}used-guns"),
    ("Used Long Guns", f"{SITE_BASE}accessories"),
)
_FILE = re.compile(r"/([^/?#]+?)\.(?:jpe?g|png|webp)(?:$|\?)", re.I)


def item_from_tile(tile: Tag, page_url: str, category: str) -> ScrapedItem | None:
    link = tile.select_one("a[data-image-url]")
    image = link.get("data-image-url") if link is not None else None
    caption = tile.select_one(".caption-text")
    title = normalize_whitespace(caption.get_text(" ", strip=True)) if caption else ""
    if not isinstance(image, str) or not title:
        return None
    name = _FILE.search(image)
    if not name:
        return None
    price_node = tile.select_one(".caption-title")
    return ScrapedItem(
        external_key=f"rcf-{name.group(1).lower()}",
        url=page_url,
        # The caption is a sentence; its first clause is the gun.
        title=title[:200],
        price=parse_price(price_node.get_text(" ", strip=True)) if price_node else None,
        description=title if len(title) > 200 else None,
        category=category,
        is_new=False,
        image_urls=[image],
        images_are_complete=True,
    )


def tiles_on(page: str, page_url: str, category: str) -> list[ScrapedItem]:
    soup = BeautifulSoup(page, "html.parser")
    found: dict[str, ScrapedItem] = {}
    for tile in soup.select("div.photoGalleryThumbs"):
        item = item_from_tile(tile, page_url, category)
        if item is not None:
            found.setdefault(item.external_key, item)
    return list(found.values())


class RcfGunsScraper(SiteScraper):
    slug = "rcf-guns"
    name = "RCF Guns"
    base_url = SITE_BASE
    description = (
        "Kentucky shop's used guns, a third of them carry pistols. A photo gallery: "
        "in-store only, with no online ordering."
    )
    requires_browser = False
    default_interval_minutes = 1440
    sells = "used"
    newsletter_url = None
    newsletter_note = "No signup found on the site; checked 2026-10-28"
    shipping_note = "In-store only: the site shows its used guns but sells nothing online"
    shipping_source = f"{SITE_BASE}used-guns"
    min_request_delay: float = 3.0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, self.min_request_delay)
        read = 0
        for category, url in SOURCES:
            ctx.check_stop()
            try:
                found = tiles_on(ctx.get_text(url), url, category)
            except ScrapeError as exc:
                ctx.warn(f"Could not read {category}: {exc}")
                ctx.not_read(category)
                continue
            ctx.log(f"{category}: {len(found)} listing(s).")
            read += len(found)
            yield from found
        if not read:
            raise ScrapeError("Neither gallery could be read.")
