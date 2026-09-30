"""Target Sports USA (targetsportsusa.com).

An ammunition dealer on AspDotNetStorefront (ASP.NET) with one section of
department trade-ins, "Used Guns & Police Trade-In": Glocks, Sig P226/P229s,
M&Ps and XDs.

**The category page says nothing about price or stock.** Every card shows the
name and the same "Add To Cart" button whether or not the gun can be bought,
so each listing's own page is read on every scan. Its schema.org microdata
carries the name, price, image, maker and ``availability``. Seventeen pages a
day, a second and a half apart.

**And today it is an archive.** Measured 2026-09-26: all 17 listings were
``SoldOut``. As at Sportsman's Outdoor Superstore, only what can be bought is
imported, and a listing we hold that goes sold out is reported sold. So this
reads nothing until the shop restocks, and catches the restock the day it
lands. That is why it is worth its seventeen requests.

**Police surplus comes from the listing's title**, not only the section. The
section's name mixes "Used Guns" with "Police Trade-In", and every title of a
trade-in says so ("*Police Trade In", "Police Trade-In"). A used gun without
that stays plain used.

robots.txt disallows the cart, sign-in, search and tracking-parameter URLs;
the category and product pages read here are allowed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
    vendors_answer,
)
from .storefront import parse_price

SITE_BASE = "https://www.targetsportsusa.com/"
SECTION = f"{SITE_BASE}used-gunspolice-trade-c-998.aspx"

POLICE = "Police Trade-In Handguns"
USED = "Used Firearms"
_POLICE_TITLE = re.compile(r"\bpolice\s+trade|\bLE\s+trade|\bLEO\b", re.I)

_PRODUCT = re.compile(r"-p-(\d+)\.aspx$", re.I)

#: The category page's default page size. Its other page sizes are chosen in
#: JavaScript, which this does not run, so a section this full may have more.
PAGE_SIZE = 20

#: Availability a buyer can act on. Everything else (SoldOut, OutOfStock,
#: Discontinued) is not for sale today.
_BUYABLE = ("InStock", "LimitedAvailability", "OnlineOnly", "InStoreOnly")

#: Product pages that fail in a row before the rest of the scan gives up on them.
MAX_FAILURES = 5


def parse_section(html_text: str) -> list[tuple[str, str, str]]:
    """``(product id, url, title)`` for each listing on the category page."""
    soup = BeautifulSoup(html_text, "html.parser")
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for card in soup.select("ul.product-list li"):
        link = card.select_one("a[href]")
        heading = card.select_one("h2")
        if link is None or heading is None:
            continue
        href = str(link.get("href") or "")
        match = _PRODUCT.search(href)
        if match is None or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        found.append(
            (match.group(1), urljoin(SITE_BASE, href), normalize_whitespace(heading.get_text()))
        )
    return found


def parse_product(html_text: str) -> dict[str, object]:
    """What a product page's microdata says: price, availability, and so on."""
    soup = BeautifulSoup(html_text, "html.parser")

    def text(prop: str) -> str:
        tag = soup.select_one(f'[itemprop="{prop}"]')
        if tag is None:
            return ""
        return normalize_whitespace(str(tag.get("content") or tag.get_text(" ", strip=True)))

    availability_tag = soup.select_one('[itemprop="availability"]')
    availability = str(availability_tag.get("href") or "") if availability_tag else ""
    image_tag = soup.select_one('[itemprop="image"]')
    image = ""
    if image_tag is not None:
        image = str(image_tag.get("content") or image_tag.get("src") or image_tag.get("href") or "")
    return {
        "name": text("name"),
        "price": parse_price(text("price")),
        "available": any(state in availability for state in _BUYABLE),
        "availability": availability.rsplit("/", 1)[-1],
        "maker": text("Manufacturer") or text("manufacturer") or None,
        "description": text("description") or None,
        "image": urljoin(SITE_BASE, image) if image else None,
    }


class TargetSportsUsaScraper(SiteScraper):
    #: Hands over the vendor's own maker (the microdata's Manufacturer).
    states_facts = True
    slug = "target-sports-usa"
    shipping_long_gun = 0.0
    shipping_handgun = 0.0
    shipping_note = "Firearms ship free; handguns UPS 2nd Day Air, long guns UPS Ground"
    shipping_source = "https://www.targetsportsusa.com/t-freeshipping.aspx"
    name = "Target Sports USA"
    base_url = SITE_BASE
    newsletter_url = SITE_BASE
    newsletter_note = (
        "No form in the page itself; Klaviyo is loaded, so signup is a popup on the home page"
    )
    description = (
        "Ammunition dealer with a police trade-in handgun section: Glocks, Sigs, "
        "M&Ps. Only listings in stock are read; the section is often sold out."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def scrape(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.log("Reading Used Guns & Police Trade-In…")
        listings = parse_section(ctx.get_text(SECTION))
        if not listings:
            raise ScrapeError("the police trade-in section listed no products")
        if len(listings) >= PAGE_SIZE:
            ctx.warn(
                f"The section shows {len(listings)} listings, a full page; it may have "
                "more that are paged in JavaScript and were not read."
            )
        failures = read = archived = 0
        for product_id, url, title in listings:
            ctx.check_stop()
            try:
                page = parse_product(ctx.get_text(url))
            except Disallowed:
                ctx.log(f"robots.txt disallows {url}; skipped.")
                continue
            except ScrapeError as exc:
                failures += 1
                say = ctx.log if vendors_answer(exc) else ctx.warn
                say(f"Could not read {url}: {exc}.")
                if failures >= MAX_FAILURES:
                    ctx.warn(f"{failures} product pages in a row failed; stopping.")
                    return
                continue
            failures = 0
            held = not ctx.needs_detail(product_id)
            if not page["available"] and not held:
                archived += 1
                continue
            name = str(page["name"] or title)
            price = page["price"]
            yield ScrapedItem(
                external_key=product_id,
                url=url,
                title=name,
                price=price if isinstance(price, float) else None,
                category=POLICE if _POLICE_TITLE.search(name) else USED,
                manufacturer=str(page["maker"]) if page["maker"] else None,
                description=str(page["description"]) if page["description"] else None,
                is_sold=not page["available"],
                image_urls=[str(page["image"])] if page["image"] else [],
            )
            read += 1
        ctx.log(f"{read} listing(s) read; {archived} sold-out archive listing(s) left out.")
