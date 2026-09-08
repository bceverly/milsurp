"""Shared machinery for BigCommerce shops.

The second storefront platform on the list, and the same idea as
:mod:`app.scrapers.woocommerce`: BigCommerce's Stencil themes render a grid of
``article.card`` elements, with the title in ``.card-title``, the price in
``.price--withoutTax`` and pagination as a ``rel="next"`` link. A theme moves
things around; the loop stays put.

**The key is the hard part here.** WooCommerce puts a WordPress post id in every
card's class list, which is the shop's own primary key and cannot be edited.
BigCommerce is less consistent: some themes carry ``data-entity-id`` on the card
and some carry nothing at all. So the id is used when it is there and the
product's URL path when it is not — which is stable in practice, and is the only
other thing a card reliably has.

**Pagination is a query string** — ``?page=2`` — unlike WooCommerce's path form.
That is worth noticing rather than assuming: a shop that disallows query strings
in robots.txt cannot be walked this way at all, which is exactly the rule that
ruled out the WooCommerce Store API on the first shop of the last group. The
walk asks before each page.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    is_sold_out,
    product_json_ld,
    text_of,
)
from .storefront import image_sources, parse_price

#: The id a Stencil theme puts on a card when it puts one anywhere.
ENTITY_ID = ("data-entity-id", "data-product-id")

#: BigCommerce serves images through a CDN path that names the size it wants:
#: `/images/stencil/500x659/products/…`. Asking for the original gets the
#: photograph the shop uploaded rather than a thumbnail of it.
STENCIL_SIZE = re.compile(r"(/images/stencil/)(?:\d+x\d+|\d+w)(/)")


#: The only ScrapedItem fields a custom field may set: the four a vendor can
#: state about a firearm. A shop's own field names are its own business; what
#: they are allowed to mean here is not.
CUSTOM_FIELD_COLUMNS = frozenset({"caliber", "country", "manufacturer", "condition"})


#: The words a shop puts in that banner. ``\bsold\b`` on its own because
#: Legacy Collectibles' banner says exactly "SOLD" and nothing else -- it is
#: scoped to the banner, so a bare "sold" there can only be about this product.
_SOLD_OUT = re.compile(r"\bsold\b|out of stock|no longer available", re.I)


#: Where a Stencil *card* says the product cannot be bought.
#:
#: ``a.card-figcaption-button`` is the one that matters: on an in-stock product
#: it reads "Add to Cart" and on a sold one the theme swaps the words. All
#: three shops here use it -- Arms of America and Bowman Arms write "Out of
#: stock", Legacy Collectibles write "SOLD". Legacy also lay a badge over the
#: photograph, which is listed after it as corroboration rather than instead.
_SOLD_CARD_SELECTORS = (
    "a.card-figcaption-button",
    ".sold-out-text",
    ".sold-out-flag-sash",
)


def sold_from_card(card: Tag) -> bool:
    """Whether the grid itself says this listing is gone.

    The product page is the authority and this is not a replacement for it --
    but a scan only fetches a product page once, so without this a listing that
    sells *after* its page was read stays "available" for as long as it stays
    in the catalog. Reading the card costs no request at all.

    Scoped to the elements above and never the card's whole text: a card
    carries its own title, and "SOLD" in a title -- which is exactly how Legacy
    Collectibles rename one -- would then be the only evidence needed, on a
    shop that had merely used the word.
    """
    for selector in _SOLD_CARD_SELECTORS:
        for element in card.select(selector):
            if _SOLD_OUT.search(text_of(element)):
                return True
    return False


def sold_out(soup: BeautifulSoup) -> bool:
    """Whether this product page says the item cannot be bought.

    Two signals, because the shops here split evenly on which they publish.
    Measured over 25 product pages across the three BigCommerce vendors:

    * **schema.org availability.** Legacy Collectibles (15 of 15) and Bowman
      Arms (4 of 4) publish it, and it is exactly right -- Legacy's one
      "SOLD - ..." listing is the one ``OutOfStock``, and two of Bowman's four
      are sold with nothing else on the page to say so.
    * **Stencil's ``.alertBox--error`` banner.** Arms of America publish no
      structured data at all (0 of 6) and show this instead. Legacy show both:
      theirs reads simply "SOLD".

    Measured again with both signals in place, over 52 product pages across the
    three shops: **14 listings move from available to sold and none the other
    way.** Six of seventeen Bowman kits, five Arms of America kits, and three
    of thirteen Legacy listings -- one of which is a $5,175 Atlas Gunworks the
    shop had renamed "SOLD - ..." since it was last read, so the stored title
    gave no sign at all.

    **Scoped to that element, never a search of the page.** "Out of stock"
    appears in the theme's JSON configuration, in the option list of a product
    whose *variants* differ in stock, and on every related-product card in the
    footer -- so an in-stock PPSh-41 kit at $599.99 has the phrase on its page
    five times over. The banner is the only place it means this product.
    """
    if is_sold_out(product_json_ld(soup)):
        return True
    return any(_SOLD_OUT.search(text_of(box)) for box in soup.select(".alertBox--error"))


def custom_fields(soup: BeautifulSoup) -> dict[str, str]:
    """A product's Stencil custom-field table, as ``{label: value}``.

    BigCommerce lets a shop define its own product fields and renders them as
    ``table.productView-custom-fields``, one ``.custom-field-label`` and
    ``.custom-field-value`` per row. It is a stock platform feature rather than
    one shop's theme, which is why this lives here.

    Legacy Collectibles use it for everything: they publish no prose
    description at all, and instead

        Year: 1911-15   Maker: Mauser   Type: C96
        Caliber: 7.63mm Mauser   Bore: 9/10   Condition: ~94-95%

    on all 258 of their listings. That is not a poor substitute for a
    description -- it is better than one, because it is the vendor stating the
    facts this application otherwise has to guess at from prose.

    Labels come back lowercased and without their trailing colon, so a shop
    that writes "Caliber:" and one that writes "caliber" read the same.
    """
    found: dict[str, str] = {}
    for row in soup.select("table.productView-custom-fields tr"):
        label = row.select_one(".custom-field-label")
        value = row.select_one(".custom-field-value")
        if label is None or value is None:
            continue
        name = text_of(label).rstrip(":").strip().lower()
        text = text_of(value)
        if name and text:
            found.setdefault(name, text)
    return found


def full_size(url: str) -> str:
    """The original upload behind a Stencil thumbnail URL."""
    return STENCIL_SIZE.sub(r"\g<1>original\g<2>", url)


def price_now(card: Tag) -> float | None:
    """The price being asked, which on a sale is not the first one shown.

    Stencil renders a reduced item as a struck-through ``.price--rrp`` beside
    the live ``.price--withoutTax``. Taking the first amount in the block would
    report the price the shop is no longer asking — and hide the drop, which is
    what this application exists to notice.
    """
    for selector in (".price--withoutTax", ".price--main", ".price--sale"):
        found = card.select_one(selector)
        if found is not None:
            price = parse_price(found.get_text(" ", strip=True))
            if price is not None:
                return price

    # Some themes put the number in an attribute and format it in JavaScript.
    for attribute in ("data-product-price", "data-price"):
        value = card.get(attribute)
        if isinstance(value, str):
            price = parse_price(value)
            if price is not None:
                return price
    return None


class BigCommerceScraper(SiteScraper):
    """One BigCommerce shop. Subclasses supply the slug, name and sources."""

    #: Where to start, one entry per category page to walk.
    sources: tuple[dict[str, str], ...] = ()

    card_selector: str = "article.card, li.product article, .productGrid .card"
    title_selectors: tuple[str, ...] = (".card-title a", ".card-title", "h4.card-title", "h4")
    link_selectors: tuple[str, ...] = (".card-figure__link", ".card-title a", "a[href]")
    next_page_selectors: tuple[str, ...] = (
        "li.pagination-item--next a",
        "a.pagination-link[rel=next]",
        "a[rel=next]",
        "link[rel=next]",
    )

    detail_title_selectors: tuple[str, ...] = ("h1.productView-title", "h1")
    detail_description_selectors: tuple[str, ...] = (
        "#tab-description",
        ".productView-description",
        "[data-product-description]",
    )
    detail_gallery_selectors: tuple[str, ...] = (
        ".productView-image img",
        "[data-image-gallery-main] img",
        ".productView-imageCarousel img",
    )
    detail_sku_selectors: tuple[str, ...] = (
        "[data-product-sku]",
        ".productView-info-value--sku",
        ".sku",
    )

    #: Which of this shop's Stencil custom fields mean something here.
    #:
    #: ``((custom field label, ScrapedItem field), …)``, labels lowercased and
    #: without their colon. Empty by default and deliberately so: the labels
    #: are the shop's own words, and "Type" means the model on one site and
    #: the action on another. A shop that publishes a field this application
    #: has a column for says so here, and the value is then a **vendor-stated**
    #: one -- which outranks anything the classifier would derive.
    #:
    #: Only these four are accepted, because they are the four columns a
    #: vendor can state: caliber, country, manufacturer, condition.
    custom_field_map: tuple[tuple[str, str], ...] = ()

    #: As gentle as the WooCommerce default, and for the same reason: these are
    #: small dealers, and one request a second was enough to be refused.
    min_request_delay: float = 5.0

    max_pages_per_source = 200

    # -- the scan -----------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        if not self.sources:  # pragma: no cover - a subclass bug, not a state
            raise ScrapeError(f"{type(self).__name__} lists no sources to scan.")
        return self._stream(ctx)

    #: Give up on product pages after this many in a row fail.
    #:
    #: Some shops serve their catalog happily and refuse every product page —
    #: Checkpoint Charlie's answers 200 on a category and 429 on /product/, to
    #: any pace and any headers. Without a limit the scan works patiently
    #: through the whole catalog discovering that one listing at a time.
    MAX_DETAIL_FAILURES = 3

    #: How many product pages have failed since the last one that worked, and
    #: whether the run has stopped asking. Reset at the top of every scan.
    _detail_failures = 0
    _gave_up_on_details = False

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        if self.min_request_delay:
            ctx.keep_at_least(self.base_url, self.min_request_delay)
        self._detail_failures = 0
        self._gave_up_on_details = False
        seen: set[str] = set()
        for source in self.sources:
            yield from self._walk(ctx, source, seen)

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, str], seen: set[str]
    ) -> Iterator[ScrapedItem]:
        category = source.get("category") or ""
        url: str | None = source["url"]
        visited: set[str] = set()
        pages = 0

        while url and pages < min(self.max_pages_per_source, ctx.scraping.max_pages):
            ctx.check_stop()
            if url in visited:
                break
            visited.add(url)

            if not ctx.allowed(url):
                # Pagination here is a query string, and a shop is entitled to
                # disallow those. Stop this section rather than fail the scan.
                ctx.warn(f"robots.txt disallows {url}; stopping this section there.")
                return

            try:
                soup = BeautifulSoup(ctx.get_text(url), "html.parser")
            except ScrapeError as exc:
                # The same argument as a refused product page, one level up.
                # Two pages read and the third refused is two pages of listings
                # worth keeping, not a scan worth throwing away — which is
                # exactly what Checkpoint Charlie's cost before this existed:
                # 56 minutes, 24 listings walked, and a run that reported zero
                # because page 3 answered 429.
                #
                # The first page is the exception. A section that could not be
                # opened at all yielded nothing, and nothing is not a partial
                # result — it is a failure, and it should be loud.
                if pages == 0:
                    raise
                ctx.warn(f"Could not read {url}: {exc}. Stopping this section at page {pages}.")
                return
            pages += 1
            cards = soup.select(self.card_selector)
            ctx.log(f"{category or 'catalog'} page {pages}: {len(cards)} listing(s).")

            for card in cards:
                item = self.item_from_card(card, url, category)
                if item is None or item.external_key in seen:
                    continue
                seen.add(item.external_key)
                yield self.with_detail(ctx, item)

            url = self.next_page(soup, url)

    def next_page(self, soup: BeautifulSoup, current: str) -> str | None:
        for selector in self.next_page_selectors:
            link = soup.select_one(selector)
            href = link.get("href") if isinstance(link, Tag) else None
            if isinstance(href, str) and href.strip():
                found = urljoin(current, href.strip())
                if urlparse(found).netloc == urlparse(current).netloc:
                    return found
        return None

    # -- one card -----------------------------------------------------------
    def item_from_card(self, card: Tag, page_url: str, category: str) -> ScrapedItem | None:
        link = self._first_href(card, self.link_selectors, page_url)
        title = self._first_text(card, self.title_selectors)
        if link is None or not title:
            return None

        thumbnails = [
            full_size(urljoin(page_url, url))
            for tag in card.select("img")
            for url in image_sources(tag)[:1]
        ]

        return ScrapedItem(
            external_key=self.key_for(card, link),
            url=link,
            title=title,
            price=price_now(card),
            category=category,
            # The grid says so too, and it says so on every scan -- where the
            # product page is read once and then skipped. See sold_from_card().
            is_sold=sold_from_card(card),
            image_urls=thumbnails[:1],
            # One preview, not the gallery. Saying otherwise would let a
            # re-scan of the grid delete photographs a detail fetch collected.
            images_are_complete=False,
        )

    def key_for(self, card: Tag, link: str) -> str:
        """This shop's own id for the product, or its URL path.

        Preferring the id matters: a shop that renames a product changes its
        URL, and a key built on the URL would read the rename as one listing
        de-listed and another appearing. Not every theme offers one, so the
        path is the fallback rather than the rule.
        """
        for attribute in ENTITY_ID:
            value = card.get(attribute)
            if isinstance(value, str) and value.strip().isdigit():
                return f"bc-{value.strip()}"
        path = urlparse(link).path.strip("/")
        return f"path-{path}" if path else f"path-{link}"

    def _first_text(self, scope: Tag, selectors: Iterable[str]) -> str:
        for selector in selectors:
            found = scope.select_one(selector)
            if found is not None:
                text = text_of(found)
                if text:
                    return text
        return ""

    def _first_href(self, scope: Tag, selectors: Iterable[str], base: str) -> str | None:
        for selector in selectors:
            for found in scope.select(selector):
                href = found.get("href")
                if isinstance(href, str) and href.strip() and not href.startswith("#"):
                    absolute = urljoin(base, href.strip())
                    if "/cart.php" in absolute or "compare" in absolute:
                        continue
                    return absolute
        return None

    # -- the product page ---------------------------------------------------
    def with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """Fill in the description and the gallery, if they are still needed."""
        if not ctx.needs_detail(item.external_key) or self._gave_up_on_details:
            return item
        try:
            soup = BeautifulSoup(ctx.get_text(item.url), "html.parser")
        except Disallowed:
            ctx.warn(f"robots.txt disallows {item.url}; keeping the catalog entry only.")
            return item
        except ScrapeError as exc:
            # A product page that cannot be fetched costs this listing its
            # description and gallery. It does not cost the scan: the catalog
            # entry already carries the title, the price and a thumbnail, which
            # is what price watching actually needs.
            #
            # Checkpoint Charlie's is why this exists. Their category pages
            # answer 200 and their /product/ pages answer 429 to everything —
            # any pace, any headers — so the old behavior spent an hour backing
            # off and then threw away a perfectly good catalog read.
            #
            # A shop that refuses every product page would otherwise have its
            # whole catalog walked one pointless request at a time, so after
            # MAX_DETAIL_FAILURES in a row the run stops asking.
            #
            # ctx.warn() downgrades the run to PARTIAL, so none of this is
            # silent.
            self._detail_failures += 1
            if self._detail_failures >= self.MAX_DETAIL_FAILURES:
                self._gave_up_on_details = True
                ctx.warn(
                    f"{self._detail_failures} product pages in a row could not be read; "
                    f"taking the rest of this scan from the catalog only. Last error: {exc}"
                )
            else:
                ctx.warn(f"Could not read {item.url}: {exc}. Keeping the catalog entry only.")
            return item

        self._detail_failures = 0
        images = self.gallery(soup, item.url)
        fields = custom_fields(soup) if self.custom_field_map else {}
        stated = self._stated(fields)
        return replace(
            item,
            # The product page is the only place a sold listing says so on this
            # platform: its card in the grid looks exactly like an in-stock
            # one. Legacy Collectibles rename a sold listing "SOLD - ..." and
            # go on showing it at its price, so without this it sat in
            # Available at $1,095.
            #
            # ``or item.is_sold`` because the catalog may already have said so,
            # and a page that publishes nothing must not un-sell it.
            is_sold=sold_out(soup) or item.is_sold,
            title=self._first_text(soup, self.detail_title_selectors) or item.title,
            description=self._first_text(soup, self.detail_description_selectors)
            or self.description_from(fields)
            or item.description,
            image_urls=images or item.image_urls,
            images_are_complete=bool(images),
            extra={**item.extra, "sku": self._sku(soup)},
            # A value the shop stated in a field of its own, where it has one.
            # Named rather than splatted: these four are the whole of what a
            # custom field is allowed to set, and that should be readable here.
            caliber=stated.get("caliber") or item.caliber,
            country=stated.get("country") or item.country,
            manufacturer=stated.get("manufacturer") or item.manufacturer,
            condition=stated.get("condition") or item.condition,
        )

    def _stated(self, fields: dict[str, str]) -> dict[str, str]:
        """The custom fields this shop says are caliber, country, maker, grade."""
        stated: dict[str, str] = {}
        for label, column in self.custom_field_map:
            if column not in CUSTOM_FIELD_COLUMNS:  # pragma: no cover - a subclass bug
                raise ValueError(f"{type(self).__name__} maps {label!r} to unknown {column!r}")
            value = fields.get(label)
            if value:
                stated[column] = value
        return stated

    def description_from(self, _fields: dict[str, str]) -> str | None:
        """A description built out of the custom fields, for a shop with none.

        Off unless a subclass wants it, and worth being clear about what it is
        for: the *reader*. The fields a subclass maps are what the classifier
        should be reading; a description assembled out of the same table adds
        nothing there and was measured not to. What it adds is the fields that
        have no column -- see LegacyCollectiblesScraper, where "Year" and
        "Type" reach a detail page this way and nowhere else.
        """
        return None

    def gallery(self, soup: BeautifulSoup, base: str) -> list[str]:
        """Every photograph on the product page, de-duplicated, original size."""
        found: list[str] = []
        for selector in self.detail_gallery_selectors:
            for tag in soup.select(selector):
                for url in image_sources(tag):
                    absolute = full_size(urljoin(base, url))
                    if absolute not in found:
                        found.append(absolute)
            if found:
                break
        return found

    def _sku(self, soup: BeautifulSoup) -> str:
        text = self._first_text(soup, self.detail_sku_selectors)
        return text.split(":", 1)[-1].strip() if ":" in text else text
