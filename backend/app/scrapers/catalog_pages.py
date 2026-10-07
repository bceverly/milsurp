"""A shop with its own hand-made catalog: section pages of listings, and a
product page behind each.

The four shops added on 2026-10-06 that run no storefront platform -- David
Condon, OldGuns.net, Horse Soldier and Cherry's -- share a shape: a few
sections, each one page, each listing a card with a name, a price
and a link; and for some, a product page with the description and the
gallery. WW2 Collectibles wrote that walk and that product-page guard out by
hand; this is the same, once, so each shop is only its parser.

A subclass supplies ``sources`` and :meth:`parse_page`, and, where the product
page is worth reading, :meth:`read_detail`. Everything else -- the walk, the
de-duplication across sections, reading each product page *once* (see
``ctx.needs_detail``), and giving up on product pages after a run of failures
rather than failing the scan -- is here.
"""

from __future__ import annotations

from collections.abc import Iterator

from .base import (
    Disallowed,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
    vendors_answer,
)

#: Product pages that may fail in a row before the rest of a scan is taken
#: from the cards alone.
MAX_DETAIL_FAILURES = 5


class CatalogPagesScraper(SiteScraper):
    """Section pages of cards, each card perhaps with a product page behind it."""

    #: One entry per section: ``{"category": "Label", "url": "https://..."}``.
    sources: tuple[dict[str, str], ...] = ()

    #: Whether :meth:`read_detail` has anything to add. Off, a scan reads the
    #: section pages and nothing else.
    reads_details: bool = False

    requires_browser = False

    def __init__(self) -> None:
        self._detail_failures = 0
        self._gave_up_on_details = False

    # -- what a subclass supplies -------------------------------------------
    def parse_page(self, html_text: str, page_url: str, category: str) -> list[ScrapedItem]:
        """The listings on one section page."""
        raise NotImplementedError

    def read_detail(self, item: ScrapedItem, html_text: str) -> None:
        """Fill *item* in from its product page. Called once per listing."""

    # -- the scan -------------------------------------------------------------
    def scrape(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        self._detail_failures = 0
        self._gave_up_on_details = False
        seen: set[str] = set()
        read = 0
        for source in self.sources:
            ctx.check_stop()
            ctx.log(f"Reading {source['category']}…")
            for item in self._walk(ctx, source):
                if item.external_key in seen:
                    continue
                seen.add(item.external_key)
                read += 1
                yield self._with_detail(ctx, item)
        ctx.log(f"{read} listing(s) read.")
        if not read:
            raise ScrapeError("no listings were found in any section")

    def _walk(self, ctx: ScrapeContext, source: dict[str, str]) -> Iterator[ScrapedItem]:
        """One section: a single page, which is what each of these shops
        publishes (Horse Soldier's with ``?show=all``). A section that cannot be
        read fails the scan rather than reading as an empty shelf."""
        ctx.check_stop()
        yield from self.parse_page(ctx.get_text(source["url"]), source["url"], source["category"])

    def _with_detail(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """The product page, once. A page that cannot be read keeps the card."""
        if (
            not self.reads_details
            or self._gave_up_on_details
            or not ctx.needs_detail(item.external_key)
        ):
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
        self.read_detail(item, html_text)
        return item
