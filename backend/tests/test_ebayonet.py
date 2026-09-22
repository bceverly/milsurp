"""eBayonet, after the shop replaced five Word pages with WordPress.

The old reader walked paragraphs: a listing opened at a five-digit stock
number, and its price and photographs were whatever prose followed before the
next one. None of that exists now -- the five ``.htm`` pages redirect to the
new catalogue and the old photo URLs 404 -- and the plugin behind the new site
publishes the same facts as fields.

Two things here are worth pinning harder than the rest.

**The slug is the key, and that is what carries the price history across.** For
743 of the 825 listings the slug is the old stock number, so the series already
stored continue rather than starting again under a new name. A test that let
the key drift to the WordPress post id would pass while quietly orphaning every
chart on the site.

**A failed page declares every category unread.** The old reader could name one
category and have it cover the shop, because everything was a bayonet. This one
sells six kinds of thing and pages by id, so the page that failed could have
held any of them -- and naming only what was seen de-lists whatever was in the
gap.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.scrapers import get_scraper
from app.scrapers.base import ScrapeError
from app.scrapers.ebayonet import PAGE_SIZE, EBayonetScraper

CATEGORY_TERMS = [
    {"id": 79, "name": "Bayonets"},
    {"id": 77, "name": "Antique Guns, Stocks, Parts + Accessories"},
]
COUNTRY_TERMS = [{"id": 1, "name": "Afghanistan"}, {"id": 24, "name": "Great Britain"}]

MEDIA = [
    {"id": 72, "source_url": "https://ebayonet.com/wp-content/uploads/2026/08/18783.jpg"},
    {"id": 73, "source_url": "https://ebayonet.com/wp-content/uploads/2026/08/18783a.jpg"},
    {"id": 85, "source_url": "https://ebayonet.com/wp-content/uploads/2026/08/12063.jpg"},
]


def record(slug, **over):
    """One ``item`` record, shaped as the REST API returns it."""
    meta = {
        "_ebay_stock": slug,
        "_ebay_price": 100,
        "_ebay_price_text": "$100",
        "_ebay_status": "available",
        "_ebay_gallery": [72, 73],
        "_ebay_legacy_page": "/https://www.ebayonet.com/bayonetsa_f.htm",
    }
    meta.update(over.pop("meta", {}))
    row = {
        "id": 5000,
        "slug": slug,
        "link": f"https://ebayonet.com/item/{slug}/",
        "title": {"rendered": "Afghan issue P1907 bayonet with scabbard."},
        "content": {"rendered": "<p>Dari marking on both tangs.</p>\n"},
        "featured_media": 0,
        "item-category": [79],
        "country": [1],
        "meta": meta,
    }
    row.update(over)
    return row


class FakeApi:
    """Serves the three endpoints this reader uses, off a list of records."""

    def __init__(self, records, *, fail_page=None, media=MEDIA):
        self.records = records
        self.fail_page = fail_page
        self.media = media
        self.asked = []

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        # Parsed rather than matched on substrings: `per_page=100` contains
        # `page=`, and `_fields=...,item-category,country` contains both
        # taxonomy names, so a fake that reads the URL by eye answers the
        # wrong endpoint and every test fails for the wrong reason.
        parts = urlsplit(url)
        endpoint = parts.path.rsplit("/", 1)[-1]
        query = parse_qs(parts.query)

        if endpoint == "item-category":
            return json.dumps(CATEGORY_TERMS)
        if endpoint == "country":
            return json.dumps(COUNTRY_TERMS)
        if endpoint == "media":
            wanted = {int(one) for one in query.get("include", [""])[0].split(",") if one}
            return json.dumps([m for m in self.media if m["id"] in wanted])
        if "slug" in query:
            wanted_slug = query["slug"][0]
            return json.dumps([r for r in self.records if r["slug"] == wanted_slug])

        page = int(query.get("page", ["1"])[0])
        if self.fail_page is not None and page >= self.fail_page:
            raise RuntimeError("502 Bad Gateway")
        start = (page - 1) * PAGE_SIZE
        return json.dumps(self.records[start : start + PAGE_SIZE])


@pytest.fixture
def serving(ctx_factory):
    def build(records, **kwargs):
        api = FakeApi(records, **kwargs)
        context = ctx_factory()
        context.get_text = api.get_text  # type: ignore[method-assign]
        return context, api

    return build


def only(items):
    assert len(items) == 1
    return items[0]


class TestReadingAListing:
    def test_the_slug_is_the_key_so_the_price_history_survives(self, serving):
        """743 of the 825 slugs are the stock number the old reader used, and
        this is the assertion that keeps them that way."""
        ctx, _ = serving([record("18783")])
        assert only(list(EBayonetScraper().scrape(ctx))).external_key == "18783"

    def test_the_price_is_the_number_the_shop_already_worked_out(self, serving):
        ctx, _ = serving([record("18783")])
        assert only(list(EBayonetScraper().scrape(ctx))).price == 100.0

    def test_a_listing_priced_by_inquiry_has_no_price_rather_than_a_free_one(self, serving):
        ctx, _ = serving(
            [record("parts", meta={"_ebay_price": 0, "_ebay_price_text": "", "_ebay_stock": ""})]
        )
        assert only(list(EBayonetScraper().scrape(ctx))).price is None

    def test_the_category_and_country_are_the_shops_own_words(self, serving):
        ctx, _ = serving([record("18783")])
        item = only(list(EBayonetScraper().scrape(ctx)))
        assert item.category == "Bayonets"
        assert item.country == "Afghanistan"

    def test_photographs_come_out_in_gallery_order(self, serving):
        ctx, _ = serving([record("18783")])
        assert only(list(EBayonetScraper().scrape(ctx))).image_urls == [
            MEDIA[0]["source_url"],
            MEDIA[1]["source_url"],
        ]

    def test_the_featured_photograph_leads_when_it_is_not_already_in_the_gallery(self, serving):
        ctx, _ = serving([record("12063", featured_media=85, meta={"_ebay_gallery": [72]})])
        assert only(list(EBayonetScraper().scrape(ctx))).image_urls == [
            MEDIA[2]["source_url"],
            MEDIA[0]["source_url"],
        ]

    def test_a_listing_with_no_photographs_is_still_a_listing(self, serving):
        ctx, _ = serving([record("parts", featured_media=0, meta={"_ebay_gallery": []})])
        assert only(list(EBayonetScraper().scrape(ctx))).image_urls == []


class TestThePriceNote:
    """``$7 each or 3 for $20`` is the rest of the offer; ``$100`` beside a
    price of 100 is the same fact twice."""

    def test_a_price_text_that_says_more_than_the_number_is_kept(self, serving):
        ctx, _ = serving(
            [record("12063", meta={"_ebay_price": 7, "_ebay_price_text": "$7 each or 3 for $20"})]
        )
        item = only(list(EBayonetScraper().scrape(ctx)))
        assert item.price == 7.0
        assert item.extra["price_note"] == "$7 each or 3 for $20"

    def test_and_one_that_only_repeats_it_is_not(self, serving):
        ctx, _ = serving([record("18783")])
        assert "price_note" not in only(list(EBayonetScraper().scrape(ctx))).extra


class TestWhetherItIsStillForSale:
    def test_available_is_for_sale(self, serving):
        ctx, _ = serving([record("18783")])
        assert only(list(EBayonetScraper().scrape(ctx))).is_sold is False

    def test_anything_else_is_not(self, serving):
        """Every one of the 825 says "available" today, so any other word is
        one this reader has never seen. Of the two ways to be wrong about it,
        showing a listing as for sale when it is not sends somebody to a dead
        page; this is the other way round, and the run says so out loud."""
        ctx, _ = serving([record("18783", meta={"_ebay_status": "reserved"})])
        items = list(EBayonetScraper().scrape(ctx))
        assert only(items).is_sold is True
        assert any("reserved" in warning for warning in ctx.warnings)

    def test_a_word_it_does_know_is_not_complained_about(self, serving):
        ctx, _ = serving([record("18783")])
        list(EBayonetScraper().scrape(ctx))
        assert ctx.warnings == []


class TestPagingTheCatalog:
    def test_it_stops_on_the_first_short_page(self, serving):
        """Rather than asking for one more and reading the refusal. WordPress
        answers a page past the end with a 400, and a reader that walks into
        that every run cannot tell the end of the catalog from a broken shop."""
        ctx, api = serving([record(str(10000 + n)) for n in range(PAGE_SIZE + 5)])
        items = list(EBayonetScraper().scrape(ctx))
        assert len(items) == PAGE_SIZE + 5
        item_pages = [url for url in api.asked if urlsplit(url).path.rsplit("/", 1)[-1] == "item"]
        assert len(item_pages) == 2

    def test_an_exactly_full_last_page_costs_one_more_request_and_no_error(self, serving):
        ctx, _ = serving([record(str(10000 + n)) for n in range(PAGE_SIZE)])
        assert len(list(EBayonetScraper().scrape(ctx))) == PAGE_SIZE


class TestWhenTheCatalogBreaksPartway:
    RECORDS = [record(str(10000 + n)) for n in range(PAGE_SIZE + 5)]

    def test_what_was_read_is_kept(self, serving):
        ctx, _ = serving(self.RECORDS, fail_page=2)
        assert len(list(EBayonetScraper().scrape(ctx))) == PAGE_SIZE

    def test_and_every_category_is_declared_unread(self, serving):
        """Not only the ones seen. The API pages by id, so the page that failed
        could have held any category, and naming only what was read would
        de-list whatever was in the gap."""
        ctx, _ = serving(self.RECORDS, fail_page=2)
        list(EBayonetScraper().scrape(ctx))
        assert ctx.unread_categories == {term["name"] for term in CATEGORY_TERMS}

    def test_a_run_that_reads_everything_declares_nothing_unread(self, serving):
        ctx, _ = serving([record("18783")])
        list(EBayonetScraper().scrape(ctx))
        assert ctx.unread_categories == set()

    def test_a_catalog_that_answers_nothing_at_all_is_the_shop(self, serving):
        ctx, _ = serving(self.RECORDS, fail_page=1)
        with pytest.raises(ScrapeError, match="no eBayonet listing could be read"):
            list(EBayonetScraper().scrape(ctx))

    def test_and_records_that_yield_no_listing_are_this_reader(self, serving):
        """The shop answered, with rows, and nothing came out of them. That is
        a different repair from a shop that is down, and saying so is the whole
        reason the two messages are not one message."""
        nameless = record("18783")
        nameless["slug"] = ""
        nameless["title"] = {"rendered": ""}
        ctx, _ = serving([nameless])
        with pytest.raises(ScrapeError, match="this reader rather than the shop"):
            list(EBayonetScraper().scrape(ctx))


class TestPhotographsAreTheSkippableThing:
    def test_a_media_request_that_fails_costs_pictures_and_not_listings(self, serving):
        ctx, api = serving([record("18783")])
        original = api.get_text

        def refuse_media(url, **kwargs):
            if "/media" in url:
                raise RuntimeError("504 Gateway Timeout")
            return original(url, **kwargs)

        ctx.get_text = refuse_media  # type: ignore[method-assign]
        item = only(list(EBayonetScraper().scrape(ctx)))
        assert item.image_urls == []
        assert item.price == 100.0
        assert any("photograph" in warning for warning in ctx.warnings)


class TestRereadingOneListingsPrice:
    def test_it_asks_for_the_one_slug(self, serving):
        ctx, api = serving([record("18783")])
        found = EBayonetScraper().check_price(ctx, "https://ebayonet.com/item/18783/")
        assert found is not None
        assert found.price == 100.0
        assert found.sold_out is False
        assert len(api.asked) == 1

    def test_a_pre_migration_url_still_works_from_its_fragment(self, serving):
        """A listing stored before the new site went up has a URL of
        ``bayonetsa_f.htm#18783``, and that fragment is the stock number, which
        is now the slug. Without this its next check reads nothing and the
        watchlist goes quiet between the migration and the next full scan."""
        ctx, _ = serving([record("18783")])
        found = EBayonetScraper().check_price(ctx, "https://www.ebayonet.com/bayonetsa_f.htm#18783")
        assert found is not None
        assert found.price == 100.0

    def test_the_key_wins_over_the_url(self, serving):
        ctx, _ = serving([record("18783")])
        assert EBayonetScraper().check_price(ctx, "https://ebayonet.com/item/nope/", key="18783")

    def test_a_listing_no_longer_in_the_catalog_is_silence(self, serving):
        ctx, _ = serving([record("18783")])
        assert EBayonetScraper().check_price(ctx, "https://ebayonet.com/item/19999/") is None

    def test_a_url_naming_nothing_is_refused(self, serving):
        ctx, _ = serving([record("18783")])
        assert EBayonetScraper().check_price(ctx, "https://ebayonet.com/") is None

    def test_a_listing_with_no_price_is_silence_rather_than_zero(self, serving):
        ctx, _ = serving([record("parts", meta={"_ebay_price": 0})])
        assert EBayonetScraper().check_price(ctx, "https://ebayonet.com/item/parts/") is None

    def test_it_agrees_with_what_a_scan_would_store(self, serving):
        """The two readings must not be able to drift: a watchlist that priced
        a listing differently from the scan beside it would mail somebody about
        a change that never happened."""
        rows = [record("12063", meta={"_ebay_price": 7, "_ebay_price_text": "$7 each"})]
        scan_ctx, _ = serving(rows)
        scanned = only(list(EBayonetScraper().scrape(scan_ctx)))
        check_ctx, _ = serving(rows)
        rechecked = EBayonetScraper().check_price(check_ctx, scanned.url)
        assert rechecked is not None
        assert rechecked.price == scanned.price


class TestItIsRegistered:
    def test_by_slug(self):
        assert isinstance(get_scraper("ebayonet"), EBayonetScraper)

    def test_it_needs_no_browser(self):
        assert EBayonetScraper.requires_browser is False
