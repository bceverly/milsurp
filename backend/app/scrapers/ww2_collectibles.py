"""WW2 Collectibles (ww2collectibles.com).

A Jacksonville, Florida militaria dealer whose firearms are genuine collector
pieces: K98 snipers, G43s, SVT-40s, Garands, M1 Carbines, Lugers, P.38s and
Nambus, each with a long description and a dozen photographs. The site runs on
AppSoft CMS, which no other shop here uses, so this parser is its own.

**Three sections are read**, measured 2026-09-27:

* Rifles (89 listings, carbines and snipers included) and Pistols (64);
* Machine Guns Semi-Auto, for the three guns in it that are nowhere else: a
  PPS-43, a Tantal and a 1919A4, semi-autos built on original kits. The rest
  of that section is magazines, loaders and a stock, so only a title that
  says "Semi-Auto" is read there.

Machine Guns, Submachine Guns, Shotguns and Class 3 add nothing else: their
listings are display pieces, magazines, pouches and shotgun-shell sets, or
guns already on the Rifles and Pistols pages.

**Two kinds of listing on those shelves are not surplus and are left out:**
DK Production Group's new-made semi-auto MP38s and STG44s, which the shop
labels "(Authentic Reproduction)", and a blank-firing "PPK style" pistol. Flare
pistols stay, because the classifier files them as handguns everywhere else.

**Sold stock stays up**, badged SOLD with its last price, as at Recoil Gun
Works: 72 of the 153 were sold when this was written. They are read as sold,
because a price somebody paid for a G43 is worth keeping.

**Everything a card needs is in its attributes**: the shop's own product id
(``data-id``), the name and the price. The product page is read once per
listing, for the description (the shop writes one per gun, with labeled
fields: maker, date, caliber, condition, bore) and the full-size gallery.

The pages are 250 KB each and there is no page-size option, so a section is
walked 50 listings at a time (``?pagenum=N``). robots.txt disallows nothing.
The site offers no mailing list; the only form on it is "Contact Us".
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
    normalize_whitespace,
    vendors_answer,
)
from .storefront import parse_price

SITE_BASE = "https://ww2collectibles.com/"
LIST_BASE = f"{SITE_BASE}products/products_list/"

SEMI_AUTO_MACHINE_GUNS = "Machine Guns Semi-Auto"

SOURCES = (
    {"category": "Rifles", "url": f"{LIST_BASE}rifles/"},
    {"category": "Pistols", "url": f"{LIST_BASE}pistols/"},
    {"category": SEMI_AUTO_MACHINE_GUNS, "url": f"{LIST_BASE}machine_guns_semi_auto/"},
)

#: Far more than any section needs (Rifles is two pages); a ceiling, not a plan.
MAX_PAGES = 20

#: Product pages that fail in a row before the rest come from the cards.
MAX_DETAIL_FAILURES = 5

_NOT_SURPLUS = re.compile(r"\breproduction\b|\bblank[\s-]*firing\b", re.I)
_SEMI_AUTO = re.compile(r"\bsemi[\s-]*auto", re.I)

#: A card's thumbnail, and the original it was cut from:
#: ``thumbnails/868_6a87…_proimg_500_450.png`` is ``868_6a87…_proimg.png``.
_THUMBNAIL = re.compile(r"/thumbnails/([^/]+?_proimg)_\d+_\d+(\.\w+)$")
_PLACEHOLDER = "product-preview"


def wanted(title: str, category: str) -> bool:
    """Whether a listing on one of the sections read is a surplus gun."""
    if _NOT_SURPLUS.search(title):
        return False
    return category != SEMI_AUTO_MACHINE_GUNS or bool(_SEMI_AUTO.search(title))


def full_size(url: str) -> str:
    """The original photograph behind a card's thumbnail."""
    return _THUMBNAIL.sub(r"/\1\2", url)


def parse_cards(html_text: str) -> Iterator[tuple[str, Tag]]:
    """``(product id, card)`` for each listing on a section page, once each.

    Every card repeats its product link three times (the photo, the name and
    the "Buy Product" button), all with the same ``data-id``.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    seen: set[str] = set()
    for card in soup.select(".shop-product-item"):
        link = card.select_one("a[data-id]")
        if link is None:
            continue
        product_id = str(link.get("data-id") or "").strip()
        if not product_id.isdigit() or product_id in seen:
            continue
        seen.add(product_id)
        yield product_id, card


def item_from_card(product_id: str, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
    link = card.select_one("a[data-id][href]")
    if link is None:
        return None
    title = normalize_whitespace(str(link.get("data-name") or ""))
    if not title:
        return None
    image = card.select_one("img.cat-thumbnail-container[src]")
    src = str(image.get("src")) if image is not None else ""
    return ScrapedItem(
        external_key=product_id,
        url=urljoin(page_url, str(link.get("href"))),
        title=title,
        # A sold card shows "SOLD" where the price was; the attribute keeps
        # the last asking price, which is the one worth recording.
        price=parse_price(str(link.get("data-price") or "")),
        category=category,
        is_sold=card.select_one(".sold-out") is not None,
        image_urls=[full_size(urljoin(page_url, src))] if src and _PLACEHOLDER not in src else [],
        images_are_complete=False,
    )


def description_of(soup: BeautifulSoup) -> str | None:
    """The shop's description, with each "Label:" on one line with its value."""
    box = soup.select_one("#description")
    if box is None:
        return None
    text = box.get_text("\n", strip=True)
    text = re.sub(r"^DESCRIPTION\n", "", text)
    text = re.sub(r":\n", ": ", text)
    return text.strip() or None


def gallery(html_text: str, product_id: str, page_url: str) -> list[str]:
    """This listing's full-size photographs, in page order.

    Named for the product (``<id>_<hash>_proimg``), which keeps out the other
    products the page shows and the thumbnails of its own.
    """
    pattern = re.compile(
        rf"/media/products/images/products/{product_id}_[0-9a-f]+_proimg\.(?:png|jpe?g|webp)",
        re.I,
    )
    found: list[str] = []
    for path in pattern.findall(html_text):
        url = urljoin(page_url, path)
        if url not in found:
            found.append(url)
    return found


class Ww2CollectiblesScraper(SiteScraper):
    slug = "ww2-collectibles"
    shipping_note = "USPS priority preferred, adult signature; no firearm shipping cost stated"
    shipping_source = "https://ww2collectibles.com/about/shipping_policy/"
    name = "WW2 Collectibles"
    base_url = SITE_BASE
    newsletter_url = None
    newsletter_note = "No signup found on the site; the only form is Contact Us. Checked 2026-09-27"
    description = (
        "Militaria dealer with collector-grade WWI and WWII rifles and pistols: "
        "K98 snipers, G43s, SVT-40s, Garands, Lugers, Nambus. New-made "
        "reproductions are not read."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def __init__(self) -> None:
        self._detail_failures = 0
        self._gave_up_on_details = False

    def scrape(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        """Each listing as it is read, product page included."""
        self._detail_failures = 0
        self._gave_up_on_details = False
        seen: set[str] = set()
        read = left_out = 0
        for source in SOURCES:
            ctx.check_stop()
            ctx.log(f"Reading {source['category']}…")
            for product_id, card, page_url in self._walk(ctx, source["url"]):
                if product_id in seen:
                    continue
                seen.add(product_id)
                item = item_from_card(product_id, card, page_url, source["category"])
                if item is None:
                    continue
                if not wanted(item.title, source["category"]):
                    left_out += 1
                    continue
                read += 1
                yield self.with_detail(ctx, item)
        ctx.log(f"{read} listing(s) read; {left_out} reproduction(s) and accessories left out.")
        if not read:
            raise ScrapeError("no listings were found in any section")

    def _walk(self, ctx: ScrapeContext, url: str) -> Iterator[tuple[str, Tag, str]]:
        """Every page of one section, until a page has no link to the next."""
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            page_url = url if page == 1 else f"{url}?pagenum={page}"
            try:
                html_text = ctx.get_text(page_url)
            except ScrapeError as exc:
                if page == 1:
                    raise
                ctx.warn(f"Could not read {page_url}: {exc}. Stopping this section there.")
                return
            cards = list(parse_cards(html_text))
            for product_id, card in cards:
                yield product_id, card, page_url
            if not cards or f"pagenum={page + 1}" not in html_text:
                return
        ctx.warn(f"{url} stopped at the {MAX_PAGES}-page ceiling.")

    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """The product page, once: the description and the whole gallery.

        A page that cannot be read keeps the card's record.
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
        item.description = description_of(soup) or item.description
        photos = gallery(html_text, item.external_key, item.url)
        if photos:
            item.image_urls = photos
            item.images_are_complete = True
        return item
