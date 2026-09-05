"""Royal Tiger Imports (royaltigerimports.com).

The hard one. It is WooCommerce behind Elementor and JetEngine, and each section
of the catalog uses a different pagination mechanism:

* **Infinite scroll** (Antiques, C&R, Deal of the Day) -- items append as you
  scroll, and the handler only fires on actual scroll *movement*, so reaching
  the bottom twice in a row loads nothing. The browser helper nudges up before
  going back down for exactly this reason.
* **"Load More" button** (Shop All) -- a control that is missing from the DOM
  until scrolled near, is sometimes an ``<a>`` and sometimes a ``<button>``, and
  is often overlapped by a sticky header so a real click throws and a scripted
  click is needed.
* **Classic pagination** (Hand Select, Parts Kits, M1 Carbines) -- ``page/2/``
  URLs, which need no browser at all beyond rendering.

Item markup is equally inconsistent: titles live in ``h1`` or ``h2`` with an
Elementor class, in a WooCommerce loop-title class, in the link's ``title``
attribute, or only in an image's ``alt`` text. Prices are the same story: a sale
puts the real price inside ``<ins>`` and the struck-through original inside
``<del>``, so the ``<ins>`` price must win whenever one is present.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..services import classify
from .base import (
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    normalize_whitespace,
    parse_price,
)
from .browser import chrome, load_more_until_stable, scroll_until_stable, wait_for_any

SITE_BASE = "https://royaltigerimports.com/"

# Every container class the site uses for a product tile, in the order to try.
PRODUCT_SELECTORS = (
    "div.jet-listing-grid__item",
    "div.e-loop-item",
    "li.product",
    "div.product",
)
PRODUCT_CSS = ", ".join(PRODUCT_SELECTORS)

#: Listings cheaper than this are consumables and accessories, not inventory.
MIN_PRICE = 100.0

#: Titles that are site furniture rather than products.
SKIP_TITLES = {"certificate of authenticity", "filter", ""}


class Section:
    """One catalog section and the strategy needed to page through it."""

    def __init__(
        self,
        name: str,
        url: str,
        mode: str,
        *,
        max_pages: int = 10,
        title_filter: str | None = None,
    ) -> None:
        self.name = name
        self.url = url
        # "scroll" | "load_more" | "paged"
        self.mode = mode
        self.max_pages = max_pages
        # Some sections are search results that also return unrelated products.
        self.title_filter = title_filter


SECTIONS = (
    Section("Antique", "https://royaltigerimports.com/antiques/", "scroll"),
    Section("C&R", "https://royaltigerimports.com/cr-firearms-2/", "scroll"),
    Section("Deal of the Day", "https://royaltigerimports.com/deal-of-the-day/", "scroll"),
    Section(
        "Hand Select",
        "https://royaltigerimports.com/product-category/crhand-select-cr-firearms-listings/",
        "paged",
        max_pages=8,
    ),
    Section(
        "Parts Kit",
        "https://royaltigerimports.com/product-category/parts-kits/",
        "paged",
        max_pages=6,
    ),
    Section(
        "M1 Carbine",
        "https://royaltigerimports.com/shop/?s=M1%20Carbine&post_type=product"
        "&product_cat=hand-select-cr-firearms-listings,united-states-of-america",
        "paged",
        max_pages=4,
        title_filter="m1 carbine",
    ),
    Section("Shop All", "https://royaltigerimports.com/shop/", "load_more"),
)


def _find_products(soup: BeautifulSoup) -> list:
    """Return the product tiles, trying each container class in turn."""
    for selector in PRODUCT_SELECTORS:
        found = soup.select(selector)
        if found:
            return found
    return []


def _extract_title(tile, link) -> str | None:
    """Titles appear in five different places depending on the template."""
    # 1. The link's own title attribute (Shop All grid).
    if link is not None and link.get("title"):
        return normalize_whitespace(link["title"])

    # 2/3. Elementor headings, h1 on loop items and h2 on listing grids.
    for tag in ("h1", "h2"):
        heading = tile.find(tag, class_="elementor-heading-title")
        if heading:
            inner = heading.find("a")
            text = normalize_whitespace((inner or heading).get_text(strip=True))
            # These headings are reused for the price on some templates.
            if text and not text.startswith("$"):
                return text

    # 4. Stock WooCommerce loop title.
    heading = tile.find("h2", class_="woocommerce-loop-product__title")
    if heading:
        return normalize_whitespace(heading.get_text(strip=True))

    # 5. The image alt text, which usually carries the product name.
    img = tile.find("img")
    if img and img.get("alt"):
        return normalize_whitespace(img["alt"])

    # Last resort: any heading long enough not to be a price or a badge.
    for heading in tile.find_all(["h1", "h2", "h3"]):
        text = normalize_whitespace(heading.get_text(strip=True))
        if text and not text.startswith("$") and len(text) > 10:
            return text
    return None


def _extract_price(tile) -> float | None:
    """Take the *effective* price: <ins> when on sale, otherwise the plain one.

    On a sale the original price sits in <del> with a strikethrough. Grabbing
    the first ``woocommerce-Price-amount`` unconditionally would record that
    struck-through price and report a phantom price drop on the next scan.
    """
    sale = tile.find("ins")
    price_span = None
    if sale:
        price_span = sale.find("span", class_="woocommerce-Price-amount")
    if price_span is None:
        # Skip anything inside a <del>: that is the superseded price.
        for span in tile.find_all("span", class_="woocommerce-Price-amount"):
            if span.find_parent("del") is None:
                price_span = span
                break
    if price_span is None:
        return None
    return parse_price(price_span.get_text(strip=True))


def _extract_image(tile) -> str | None:
    img = tile.find("img")
    if not img:
        return None
    # Lazy-loaded grids leave src as a placeholder and put the real URL in
    # data-src / data-lazy-src.
    for attribute in ("data-src", "data-lazy-src", "src"):
        value = img.get(attribute)
        # A multi-valued attribute would come back as a list; these are all
        # single-valued, so anything else is ignored.
        if isinstance(value, str) and value and not value.startswith("data:"):
            return urljoin(SITE_BASE, value)
    return None


def parse_products(html_text: str, section: Section) -> dict[str, ScrapedItem]:
    """Parse every product tile on a rendered page, keyed by product URL."""
    soup = BeautifulSoup(html_text, "html.parser")
    found: dict[str, ScrapedItem] = {}

    for tile in _find_products(soup):
        link = tile.find("a", href=re.compile(r"/shop/"))
        if not link or not link.get("href"):
            continue
        url = urljoin(SITE_BASE, link["href"])

        title = _extract_title(tile, link)
        if not title or title.lower() in SKIP_TITLES:
            continue
        if section.title_filter and section.title_filter not in title.lower():
            continue

        price = _extract_price(tile)
        if price is None or price < MIN_PRICE:
            continue

        image = _extract_image(tile)
        derived = classify.enrich(title, None, price)

        found[url] = ScrapedItem(
            external_key=url,
            url=url,
            title=title,
            price=price,
            category=section.name,
            image_urls=[image] if image else [],
            caliber=derived["caliber"],
            country=derived["country"],
            manufacturer=derived["manufacturer"],
            is_sold=False,
        )
    return found


# WordPress renders every uploaded image at several sizes and encodes the size
# into the filename ("IMG_2619-1024x346.jpeg"). Stripping that suffix yields the
# original upload, which is what we want to keep.
WP_SIZE_SUFFIX = re.compile(r"-\d{2,4}x\d{2,4}(?=\.[A-Za-z]{3,4}$)")
# WordPress renames oversized uploads to "<name>-scaled.jpg" and keeps that as
# the canonical file, so "breda-no-mag.jpg" and "breda-no-mag-scaled.jpg" are
# the same photograph reached by two different URLs.
WP_SCALED_SUFFIX = re.compile(r"-scaled(?=\.[A-Za-z]{3,4}$)")
# Site chrome that lives in the uploads directory alongside product photos.
CHROME_IMAGE_HINTS = ("rti-logo", "logo", "banner", "placeholder", "icon")


def _full_size(url: str) -> str:
    """Turn a WordPress resized URL back into the original upload."""
    return WP_SIZE_SUFFIX.sub("", url)


def _photo_identity(url: str) -> str:
    """Key that collapses every URL form of the same photograph."""
    return WP_SCALED_SUFFIX.sub("", _full_size(url)).lower()


def _is_product_image(url: str) -> bool:
    lowered = url.lower()
    if "/wp-content/uploads/" not in lowered:
        return False
    filename = lowered.rsplit("/", 1)[-1]
    return not any(hint in filename for hint in CHROME_IMAGE_HINTS)


def extract_gallery(soup: BeautifulSoup) -> list[str]:
    """Every photo for one product, best resolution first.

    RTI does not use the stock WooCommerce gallery. The extra photos live in an
    **Elementor gallery widget**, where each ``a.e-gallery-item`` href is the
    full-size image and the nested div carries only a 300x300 thumbnail. The
    single "featured" image is a separate Elementor image widget above it.

    Everything else on the page that lives in the uploads directory is either
    site chrome or the related-products carousel -- those are other listings'
    photos and must not be attached to this item.
    """
    urls: list[str] = []
    seen: set[str] = set()

    def add(candidate: object) -> None:
        # BeautifulSoup types attribute access as possibly multi-valued; every
        # attribute read here is single-valued, so non-strings are discarded.
        if not isinstance(candidate, str) or not candidate:
            return
        absolute = _full_size(urljoin(SITE_BASE, candidate))
        if not _is_product_image(absolute):
            return
        identity = _photo_identity(absolute)
        if identity in seen:
            return
        seen.add(identity)
        urls.append(absolute)

    # Gallery first: those hrefs are the exact files WordPress serves, so when
    # the same photo also appears as the featured image the reliable URL wins.
    for anchor in soup.select("a.e-gallery-item[href]"):
        add(anchor.get("href"))

    # Fallback for the stock WooCommerce gallery, in case a product page or a
    # future theme change uses it.
    for image in soup.select(".woocommerce-product-gallery img"):
        add(image.get("data-large_image") or image.get("data-src") or image.get("src"))

    # The featured image, rendered as a plain Elementor image widget. Usually a
    # duplicate of a gallery entry; it is the only photo when there is no
    # gallery at all.
    for widget in soup.select(".elementor-widget-image img"):
        classes = " ".join(widget.get("class") or [])
        if "attachment-large" in classes or "attachment-full" in classes:
            add(widget.get("data-src") or widget.get("src"))

    return urls


def scrape_product_detail(ctx: ScrapeContext, url: str) -> tuple[str | None, list[str]]:
    """Fetch a product page for its long description and full photo gallery.

    Plain HTTP: the detail pages render server-side, so no browser is needed
    here even though the listing pages require one.
    """
    try:
        html_text = ctx.get_text(url)
    except Exception as exc:
        ctx.warn(f"detail fetch failed for {url}: {exc}")
        return None, []

    soup = BeautifulSoup(html_text, "html.parser")

    description = None
    for finder in (
        lambda: soup.find("div", class_="prod_desc"),
        lambda: soup.find("div", class_="elementor-widget-woocommerce-product-content"),
        lambda: soup.find("div", class_="woocommerce-Tabs-panel--description"),
        lambda: soup.find("div", id="tab-description"),
        lambda: soup.find("div", class_="product-description"),
        lambda: soup.find("div", class_=lambda c: bool(c) and "description" in str(c).lower()),
    ):
        block = finder()
        if block:
            text = block.get_text(separator="\n", strip=True)
            if text:
                description = text
                break

    return description, extract_gallery(soup)


class RoyalTigerScraper(SiteScraper):
    slug = "royal-tiger"
    name = "Royal Tiger Imports"
    base_url = SITE_BASE
    description = (
        "Large importer catalog. Needs a headless browser: sections use infinite "
        "scroll, Load More buttons and classic pagination interchangeably."
    )
    requires_browser = True
    default_interval_minutes = 1440

    #: Fetch each new listing's product page for its description and the full
    #: photo gallery. The grid only ever exposes one image per product.
    deep_scrape: bool = True
    #: Cap on detail fetches per run so a first-ever scan cannot take hours;
    #: whatever is left over is picked up by the next scan.
    max_detail_fetches: int = 250

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        found: dict[str, ScrapedItem] = {}

        with chrome(ctx.scraping) as driver:
            for section in SECTIONS:
                ctx.check_stop()
                ctx.log(f"--- {section.name} ({section.mode}) ---")
                try:
                    self._scrape_section(ctx, driver, section, found)
                except ScrapeError:
                    raise
                except Exception as exc:
                    # A single broken section should not lose the whole run.
                    ctx.warn(f"section '{section.name}' failed: {exc}")

        items = list(found.values())
        if not items:
            raise ScrapeError("no products found on any Royal Tiger section")
        ctx.log(f"Collected {len(items)} unique listings across {len(SECTIONS)} sections.")

        if self.deep_scrape:
            self._fetch_details(ctx, items)
        return items

    # -- per-section strategies ---------------------------------------------
    def _scrape_section(
        self, ctx: ScrapeContext, driver, section: Section, found: dict[str, ScrapedItem]
    ) -> None:
        if section.mode == "paged":
            self._scrape_paged(ctx, driver, section, found)
            return

        driver.get(section.url)
        if wait_for_any(driver, PRODUCT_SELECTORS, timeout=20) is None:
            ctx.warn(f"no products rendered on {section.url}")
            return

        # Sections share a single dict keyed by product URL, so an item that
        # appears in two sections is stored once. The first section to claim it
        # keeps its category, which is why the specific sections are listed
        # ahead of the catch-all "Shop All".
        def harvest(page_source: str) -> int:
            for url, item in parse_products(page_source, section).items():
                found.setdefault(url, item)
            return len(found)

        if section.mode == "load_more":
            load_more_until_stable(
                driver,
                harvest,
                max_clicks=ctx.scraping.max_pages,
                check_stop=ctx.check_stop,
                log=ctx.log,
            )
        else:
            scroll_until_stable(
                driver,
                harvest,
                max_iterations=ctx.scraping.max_pages,
                check_stop=ctx.check_stop,
                log=ctx.log,
            )

    def _scrape_paged(
        self, ctx: ScrapeContext, driver, section: Section, found: dict[str, ScrapedItem]
    ) -> None:
        for page in range(1, min(section.max_pages, ctx.scraping.max_pages) + 1):
            ctx.check_stop()
            url = section.url if page == 1 else self._page_url(section.url, page)
            driver.get(url)
            if wait_for_any(driver, PRODUCT_SELECTORS, timeout=15) is None:
                ctx.log(f"Page {page} has no products; end of section.")
                return
            page_items = parse_products(driver.page_source, section)
            if not page_items:
                ctx.log(f"Page {page} matched nothing; end of section.")
                return
            for item_url, item in page_items.items():
                found.setdefault(item_url, item)
            ctx.log(f"Page {page}: {len(page_items)} products ({len(found)} unique so far).")

    @staticmethod
    def _page_url(base: str, page: int) -> str:
        """Search URLs paginate with ``&paged=``, categories with ``page/N/``."""
        if "?" in base:
            return f"{base}&paged={page}"
        return f"{base.rstrip('/')}/page/{page}/"

    # -- detail pass ---------------------------------------------------------
    def _fetch_details(self, ctx: ScrapeContext, items: list[ScrapedItem]) -> None:
        """Fetch each new listing's description and full photo gallery.

        The listing grid shows only one photo per product; a firearm normally
        has several, and they are only on the product page. Listings already
        stored with a description and gallery are skipped, so the cost is paid
        once per listing rather than on every scan.
        """
        pending = [item for item in items if ctx.needs_detail(item.external_key)]
        if not pending:
            ctx.log("No new listings need detail pages.")
            return

        budget = min(self.max_detail_fetches, len(pending))
        skipped = len(pending) - budget
        ctx.log(
            f"Fetching detail pages for {budget} new listing(s)"
            + (f" ({skipped} deferred to the next scan)" if skipped else "")
            + "…"
        )

        photos_found = 0
        for index, item in enumerate(pending[:budget]):
            ctx.check_stop()
            description, gallery = scrape_product_detail(ctx, item.url)

            if gallery:
                # Gallery images are full resolution and in display order, so
                # they replace the low-resolution grid thumbnail entirely.
                item.image_urls = gallery
                photos_found += len(gallery)

            if description:
                item.description = normalize_whitespace(description)
                # The long text is far richer than the title, so re-run the
                # heuristics now that there is something to work with.
                derived = classify.enrich(item.title, item.description, item.price, caliber=None)
                item.caliber = derived["caliber"]
                item.country = derived["country"] or item.country
                item.manufacturer = derived["manufacturer"] or item.manufacturer
                item.condition = derived["condition"]

            if (index + 1) % 10 == 0:
                ctx.log(f"  …{index + 1}/{budget} detail pages ({photos_found} photos).")

        ctx.log(f"Detail pass complete: {photos_found} photo(s) across {budget} listing(s).")
