"""Sportsman's Outdoor Superstore (sportsmansoutdoorsuperstore.com).

A licensed dealer and law-enforcement distributor, on a ColdFusion storefront
of its own. Two sections are read: "Glock Police Trade-ins" and "Used Guns",
which between them are the police Glocks, Remington 870 Police Magnums,
Mossberg 590s, Beretta M9s, Sig P22x pistols, Colt LE6920s, Smith & Wesson
Model 64s and so on, plus a little surplus (Bulgarian Makarovs, a Mosin, a
P08).

**The catalog is mostly an archive, and that decides the design.** Measured
2026-09-26: the two sections list 1,895 different products over 116 pages,
and **about 20 of them can be bought**. The rest are "No Longer Available"
pages the shop leaves up with the last price they carried and no date. Those
are not sales we saw and cannot be dated, so they are not imported: they would
bury a score of real listings under two thousand old ones and teach the price
bands a price from an unknown year.

So a card is read only when it says **In Stock**, with one exception: a
listing we already hold whose card has gone silent has sold, and is reported
sold rather than left out (left out, it would read as de-listed). Every
card's own label was checked against its product page's structured data, 12
of 12 in agreement, and the page says ``OutOfStock`` and "No Longer Available"
exactly where the card says nothing.

**Police surplus comes from the section, as everywhere else.** The Glock
section's name says so. "Used Guns" is 93% police trade-ins but also carries
ordinary used guns and the surplus pistols, so there a listing is filed under
police trade-ins only when its title says it is one ("Police Trade-In",
"Police Trades", "LE Trade"), and under used firearms otherwise. That is this
shop shelving both together, not a rule about what police surplus is.

robots.txt disallows the ``/make/``, ``/model/``, ``/under/`` and ``/order_by/``
filters and nothing that is read here; ``/currentpage/N`` paging is allowed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    is_sold_out,
    normalize_whitespace,
    product_json_ld,
    vendors_answer,
)
from .storefront import parse_price

SITE_BASE = "https://www.sportsmansoutdoorsuperstore.com/"
CATEGORY_BASE = f"{SITE_BASE}category.cfm/sportsman/"

#: The Glock section first: 190 listings appear in both, and the section that
#: names them police trade-ins should be the one that files them.
SOURCES = (
    {"category": "Police Trade-In Glocks", "url": f"{CATEGORY_BASE}police-trade-in-glocks"},
    {"category": "Used Firearms", "url": f"{CATEGORY_BASE}used-firearms"},
)

#: Where a "Used Guns" listing is a department trade-in by its own title.
POLICE_IN_USED = "Police Trade-In Firearms"
_POLICE_TITLE = re.compile(r"\bpolice\s+trade|\bLE\s+trade|\blaw\s+enforcement\s+trade", re.I)

#: 58 pages each in September 2026. The ceiling is for a loop, not a limit.
MAX_PAGES = 150

_PRODUCT_ID = re.compile(r"/products2\.cfm/ID/(\d+)/")

#: Photos on the product page: the main image and its alternates.
_PHOTO = re.compile(r"/prodimages/(?:alt_images/)?[^\"'\s<>]+\.(?:jpe?g|png|webp)", re.I)

#: A run of product pages that will not load, after which the scan takes the
#: rest of its listings from the cards alone.
MAX_DETAIL_FAILURES = 5


def parse_cards(html_text: str) -> Iterator[tuple[str, Tag]]:
    """Each product card on a category page, with its product id."""
    soup = BeautifulSoup(html_text, "html.parser")
    for card in soup.select('[itemtype="http://schema.org/Product"]'):
        link = card.select_one('a[href*="/products2.cfm/ID/"]')
        if link is None:
            continue
        found = _PRODUCT_ID.search(str(link.get("href") or ""))
        if found:
            yield found.group(1), card


def in_stock(card: Tag) -> bool:
    """The card's own label. Silent means the product page says out of stock."""
    return card.select_one(".prd-in-stk-ctn") is not None


def item_from_card(product_id: str, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
    link = card.select_one('a[href*="/products2.cfm/ID/"]')
    name = card.select_one('[itemprop="name"]')
    if link is None or name is None:
        return None
    title = normalize_whitespace(name.get_text(" ", strip=True))
    if not title:
        return None
    price_tag = card.select_one('[itemprop="price"]')
    image = card.select_one("img[src]")
    if category == "Used Firearms" and _POLICE_TITLE.search(title):
        category = POLICE_IN_USED
    brand = card.select_one('[itemprop="brand"] [itemprop="name"]')
    return ScrapedItem(
        external_key=product_id,
        url=urljoin(page_url, str(link.get("href"))),
        title=title,
        # ``itemprop="price"`` is the asking price. The struck-through
        # ``sugg-price`` beside it is their "suggested" figure, not a sale.
        price=parse_price(price_tag.get_text(" ", strip=True)) if price_tag else None,
        category=category,
        manufacturer=normalize_whitespace(brand.get_text(" ", strip=True)) if brand else None,
        image_urls=[_large(urljoin(page_url, str(image.get("src"))))] if image else [],
        images_are_complete=False,
    )


def _large(url: str) -> str:
    """The card shows the ``-m`` rendition; the product page uses ``-l``."""
    return re.sub(r"-DEFAULT-m\.", "-DEFAULT-l.", url, flags=re.I)


class SportsmansOutdoorScraper(SiteScraper):
    #: Hands over the vendor's own maker (the card's brand). See SiteScraper.
    states_facts = True
    slug = "sportsmans-outdoor"
    name = "Sportsman's Outdoor Superstore"
    base_url = SITE_BASE
    newsletter_url = f"{SITE_BASE}newsletter/"
    newsletter_note = (
        'Newsletter page; the same "Join Our Mailing List" form is on the home page '
        "(their /sms-signup/ is text messages, not email)"
    )
    description = (
        "Police trade-ins in quantity: Glocks, 870 Police Magnums, M9s, Sigs, "
        "LE6920s. Only in-stock listings are read; the rest of their catalog is "
        "an archive of guns no longer available."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def __init__(self) -> None:
        self._detail_failures = 0
        self._gave_up_on_details = False

    def scrape(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        """Each listing as it is read, product page included.

        A generator, so a scan that is stopped part-way (or a recording that
        runs out) keeps what it has already read.
        """
        seen: set[str] = set()
        read = silent_unknown = 0
        for source in SOURCES:
            ctx.check_stop()
            ctx.log(f"Reading {source['category']}…")
            for product_id, card, page_url in self._walk(ctx, source["url"]):
                if product_id in seen:
                    continue
                seen.add(product_id)
                available = in_stock(card)
                # A listing we hold has had its product page read, so this is
                # also "do we hold it". One we hold that has gone silent has
                # sold; one we never held that is silent is archive.
                held = not ctx.needs_detail(product_id)
                if not available and not held:
                    silent_unknown += 1
                    continue
                item = item_from_card(product_id, card, page_url, source["category"])
                if item is None:
                    continue
                item.is_sold = not available
                read += 1
                yield self.with_detail(ctx, item)

        ctx.log(
            f"{read} listing(s) read; {silent_unknown} no-longer-available "
            "archive listing(s) left out."
        )
        if not read and not silent_unknown:
            raise ScrapeError("no product cards were found in either section")

    def _walk(self, ctx: ScrapeContext, url: str) -> Iterator[tuple[str, Tag, str]]:
        """Every page of one section, until a page adds nothing or has no next."""
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            page_url = url if page == 1 else f"{url}/currentpage/{page}"
            try:
                html_text = ctx.get_text(page_url)
            except ScrapeError as exc:
                if page == 1:
                    raise
                ctx.warn(f"Could not read {page_url}: {exc}. Stopping this section there.")
                return
            cards = list(parse_cards(html_text))
            if not cards:
                return
            for product_id, card in cards:
                yield product_id, card, page_url
            if f"currentpage/{page + 1}" not in html_text:
                return
        ctx.warn(f"{url} stopped at the {MAX_PAGES}-page ceiling.")

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """The product page, once: the description and the whole gallery.

        A page that cannot be read keeps the card's record, which is already
        a whole listing apart from the prose.
        """
        if not ctx.needs_detail(item.external_key) or self._gave_up_on_details:
            return item
        try:
            html_text = ctx.get_text(item.url)
        except Disallowed:
            ctx.log(f"robots.txt disallows {item.url}; keeping the card only.")
            return item
        except ScrapeError as exc:
            self._detail_failures += 1
            if self._detail_failures >= MAX_DETAIL_FAILURES:
                self._gave_up_on_details = True
                ctx.warn(
                    f"{self._detail_failures} product pages in a row could not be read; "
                    f"taking the rest of this scan from the cards. Last error: {exc}"
                )
            else:
                say = ctx.log if vendors_answer(exc) else ctx.warn
                say(f"Could not read {item.url}: {exc}. Keeping the card only.")
            return item
        self._detail_failures = 0

        soup = BeautifulSoup(html_text, "html.parser")
        node = product_json_ld(soup)
        if node is not None:
            description = node.get("description")
            if isinstance(description, str) and description.strip():
                item.description = description.strip()
            if is_sold_out(node):
                item.is_sold = True
        photos = self._gallery(html_text, item.url)
        if photos:
            item.image_urls = photos
            item.images_are_complete = True
        return item

    @staticmethod
    def _gallery(html_text: str, page_url: str) -> list[str]:
        """The main photo and its alternates, large rendition, in page order.

        The page also shows thumbnails of *other* products ("you may also
        like"), all ``-DEFAULT-M``; this listing's own photos are its ``-l``
        main image and its ``alt_images``.
        """
        found: list[str] = []
        for path in _PHOTO.findall(html_text):
            if "/alt_images/" not in path and not re.search(r"-DEFAULT-l\.", path, re.I):
                continue
            url = urljoin(page_url, path)
            if url not in found:
                found.append(url)
        return found
