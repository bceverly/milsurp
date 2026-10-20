"""James River Armory (jamesriverarmory.com).

A Baltimore builder of military-pattern rifles on new receivers with
surplus parts -- M14s, BM-59s and BM-62s, Yugoslav M72s, Galils -- and of
Civil War reproductions, asked for on 2026-10-20 "for rifles". CS-Cart; no
bot protection, and robots.txt disallows only ``/app/``.

**One section, "Available Firearms"** (``category_id=27``), lists the guns:
eleven that day. A product page carries the rest -- the price
(``#sec_discounted_price_<id>``), "In stock" or not, the description and the
gallery, whose full-size photographs are the thumbnails' paths without
``thumbnails/400/400/``. With so few, every product page is read every scan,
so a price or stock change is seen the day it happens.

Everything is built new by the shop.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from bs4 import BeautifulSoup

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

SITE_BASE = "https://www.jamesriverarmory.com/"
SECTION = f"{SITE_BASE}index.php?dispatch=categories.view&category_id=27"
_PRODUCT = re.compile(r"dispatch=products\.view&(?:amp;)?product_id=(\d+)")
_THUMBNAIL = re.compile(r"/images/thumbnails/\d+/\d+/detailed/")


def product_ids(page: str) -> list[str]:
    """The products a section page lists, in its order."""
    return list(dict.fromkeys(_PRODUCT.findall(page)))


def parse_product(page: str, product_id: str, url: str) -> ScrapedItem | None:
    """One rifle from its product page."""
    soup = BeautifulSoup(page, "html.parser")
    heading = soup.select_one("h1")
    title = normalize_whitespace(text_of(heading)) if heading is not None else ""
    if not title:
        return None
    price_tag = soup.select_one(f"#sec_discounted_price_{product_id}") or soup.select_one(
        ".ty-price-num:last-of-type"
    )
    price = parse_price(text_of(price_tag)) if price_tag is not None else None
    in_stock = soup.select_one(".ty-qty-in-stock") is not None
    description_tag = soup.select_one("#content_description")
    images: list[str] = []
    for tag in soup.select("a[href*='/images/detailed/'], img[src*='/detailed/']"):
        src = str(tag.get("href") or tag.get("src") or "")
        src = _THUMBNAIL.sub("/images/detailed/", src)
        if "/images/detailed/" in src and src not in images:
            images.append(src)
    return ScrapedItem(
        external_key=f"jra-{product_id}",
        url=url,
        title=title,
        price=price,
        description=(text_of(description_tag) or None) if description_tag is not None else None,
        category="Available Firearms",
        manufacturer="James River Armory",
        is_sold=not in_stock,
        is_new=True,
        image_urls=images,
    )


class JamesRiverArmoryScraper(SiteScraper):
    slug = "james-river-armory"
    name = "James River Armory"
    base_url = SITE_BASE
    description = (
        "Builder of M14, BM-59 and other military-pattern rifles, and Civil War reproductions."
    )
    default_interval_minutes = 1440
    sells = "new"
    #: The maker is the shop itself.
    states_facts = True
    requires_browser = False
    newsletter_url = SITE_BASE
    newsletter_note = '"Stay Connected" signup form in the footer of every page'
    shipping_note = "No firearm shipping rate published (checked 2026-10-20)"

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.keep_at_least(self.base_url, 2.0)
        ids = product_ids(ctx.get_text(SECTION))
        ctx.log(f"Available Firearms: {len(ids)} listing(s).")
        for product_id in ids:
            ctx.check_stop()
            url = f"{SITE_BASE}index.php?dispatch=products.view&product_id={product_id}"
            try:
                item = parse_product(ctx.get_text(url), product_id, url)
            except (Disallowed, ScrapeError) as exc:
                ctx.warn(f"Could not read {url}: {exc}")
                continue
            if item is not None:
                yield item
