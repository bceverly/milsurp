"""A host cooldown must not turn a scan into a failure.

The cooldown register is keyed by **host**, and the evidence that fills it is
often path-specific: a shop whose catalog answers 200 and whose product pages
refuse publishes a host-wide pause, and then the *next* section's first catalog
page is refused by our own register before any request goes out.

Treating that as the vendor refusing a catalog page is a category error, and an
expensive one — it is how Checkpoint Charlie's produced **9 failed scans
against 1 partial** while the detail-page fallback worked exactly as designed.
A cooldown is our decision not to ask, which is the same shape as robots.txt
telling us not to, and it is handled the same way: the section is a gap rather
than a failure.

What must not be lost in the fix is the de-listing guard. A scraper is supposed
to return the shop's complete inventory, so anything it omits looks sold — and
a section nobody opened has to be declared unread or its listings vanish.
"""

from __future__ import annotations

import pytest

from app.scrapers.base import HostResting, ScrapeError


class FakeContext:
    """Enough of a ScrapeContext for the walk, recording what it was told."""

    def __init__(self, resting: set[str], pages: dict[str, str]):
        self._resting = resting
        self._pages = pages
        self.warnings: list[str] = []
        self.unread: list[str] = []
        self.requested: list[str] = []
        self.scraping = type("S", (), {"max_pages": 10})()

    def check_stop(self) -> None: ...

    def log(self, _message: str) -> None: ...

    def allowed(self, _url: str) -> bool:
        return True

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def not_read(self, category: str | None) -> None:
        if category:
            self.unread.append(category)

    def needs_detail(self, _key: str) -> bool:
        return False

    def keep_at_least(self, *_args) -> None: ...

    def get_text(self, url: str) -> str:
        self.requested.append(url)
        if url in self._resting:
            raise HostResting(url, 900.0)
        if url not in self._pages:
            raise ScrapeError(f"GET {url}: 500")
        return self._pages[url]


#: A WooCommerce loop card as the themes actually render one. The `post-N`
#: class is not decoration: it is where the external key comes from, and a card
#: without it is read as a promotional tile and skipped.
CARD = (
    '<li class="post-{n} product type-product">'
    '<a class="woocommerce-loop-product__link" href="https://shop.test/product/p{n}/">'
    '<h2 class="woocommerce-loop-product__title">Rifle {n}</h2></a>'
    '<span class="price"><bdi>$100</bdi></span></li>'
)


def page(*numbers: int) -> str:
    return "<ul>" + "".join(CARD.format(n=n) for n in numbers) + "</ul>"


@pytest.fixture
def scraper():
    from app.scrapers.woocommerce import WooCommerceScraper

    class Shop(WooCommerceScraper):
        slug = "shop"
        name = "Shop"
        base_url = "https://shop.test/"
        sources = (
            {"category": "Rifles", "url": "https://shop.test/c/rifles/"},
            {"category": "Pistols", "url": "https://shop.test/c/pistols/"},
        )

    return Shop()


class TestASectionThatCannotBeAsked:
    def test_it_does_not_fail_the_scan(self, scraper):
        """The first section reads, the second is resting. One section of
        listings is worth keeping."""
        ctx = FakeContext(
            resting={"https://shop.test/c/pistols/"},
            pages={"https://shop.test/c/rifles/": page(1, 2)},
        )
        items = list(scraper.scrape(ctx))
        assert [item.external_key for item in items] == ["post-1", "post-2"]

    def test_and_says_so(self, scraper):
        ctx = FakeContext(
            resting={"https://shop.test/c/pistols/"},
            pages={"https://shop.test/c/rifles/": page(1)},
        )
        list(scraper.scrape(ctx))
        assert any("Not asking" in warning for warning in ctx.warnings)

    def test_and_protects_its_listings_from_being_de_listed(self, scraper):
        """The important half. A scraper is supposed to return the complete
        inventory, so a section nobody opened has to be declared unread or its
        listings look sold."""
        ctx = FakeContext(
            resting={"https://shop.test/c/pistols/"},
            pages={"https://shop.test/c/rifles/": page(1)},
        )
        list(scraper.scrape(ctx))
        assert ctx.unread == ["Pistols"]

    def test_it_does_not_keep_asking(self, scraper):
        """One refusal per section, not one per page."""
        ctx = FakeContext(
            resting={"https://shop.test/c/pistols/"},
            pages={"https://shop.test/c/rifles/": page(1)},
        )
        list(scraper.scrape(ctx))
        assert ctx.requested.count("https://shop.test/c/pistols/") == 1


class TestWhenNothingCanBeAsked:
    def test_a_scan_that_read_nothing_is_a_failure(self, scraper):
        """Loud, because a run that asked for nothing and found nothing is not
        the same as a shop that has sold out — and the difference is invisible
        in the item count."""
        ctx = FakeContext(
            resting={"https://shop.test/c/rifles/", "https://shop.test/c/pistols/"},
            pages={},
        )
        with pytest.raises(ScrapeError, match="Every section was skipped"):
            list(scraper.scrape(ctx))

    def test_but_nothing_is_de_listed_on_the_way_out(self, scraper):
        """The run fails; the catalog is untouched. Both sections were declared
        unread before the failure was raised."""
        ctx = FakeContext(
            resting={"https://shop.test/c/rifles/", "https://shop.test/c/pistols/"},
            pages={},
        )
        with pytest.raises(ScrapeError):
            list(scraper.scrape(ctx))
        assert sorted(ctx.unread) == ["Pistols", "Rifles"]


class TestARealRefusalIsStillLoud:
    def test_a_first_page_that_errors_still_fails_the_scan(self, scraper):
        """Nothing here softens a vendor actually refusing a catalog page. A
        section that yielded nothing because the shop said no is a failure, and
        should stay one."""
        ctx = FakeContext(resting=set(), pages={})
        with pytest.raises(ScrapeError) as caught:
            list(scraper.scrape(ctx))
        assert "Every section was skipped" not in str(caught.value)

    def test_a_later_page_that_errors_keeps_what_was_read(self, scraper):
        """Unchanged behavior, asserted so the new branch above cannot quietly
        take it over."""
        ctx = FakeContext(
            resting=set(),
            pages={
                "https://shop.test/c/rifles/": page(1)
                + '<a class="next page-numbers" href="https://shop.test/c/rifles/page/2/">2</a>',
                "https://shop.test/c/pistols/": page(2),
            },
        )
        items = list(scraper.scrape(ctx))
        assert sorted(item.external_key for item in items) == ["post-1", "post-2"]
        assert any("Could not read" in warning for warning in ctx.warnings)
