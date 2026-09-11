"""Simpson Ltd.: a vendor the roadmap had filed as needing a browser.

The recorded finding was "the catalog is in Firestore (project
simpsonltd-bfd2b) and its rules refuse an unauthenticated read; anonymous
sign-in is disabled too". All of that is true and it is the wrong door: the
React bundle does not read Firestore directly, it calls **Cloud Functions** on
the same project, and those answer a plain unauthenticated GET. Seventh vendor
filed as unreachable that had an endpoint.

The other thing worth pinning is the **scope**, because this vendor makes it
matter: 19,201 items, every one priced, pictured and in stock, against 5,600 in
this whole application. Most of it is a sporting catalog — 3,057 shotguns — and
what is read is the milsurp shelves.
"""

from __future__ import annotations

import json

import pytest

from app.scrapers import get_scraper
from app.scrapers.simpson_ltd import (
    _AMBIGUOUS_SUBCATEGORIES,
    NOT_READ,
    PAGE_SIZE,
    SOURCES,
    SimpsonLtdScraper,
    endpoint,
    full_size,
    item_from_record,
    label_of,
    product_url,
)

#: One record as the category endpoint returns it, trimmed. The gallery is two
#: *thumbnails*; the listing really has seven photographs.
RECORD = {
    "SKU": "C75280",
    "Title": "BRESCIA CARCANO 91/38",
    "Category": "Long Guns",
    "Subcategory": "Military Rifles",
    "Description": "F.N.A. Brescia arsenal manufacture, dated 1940.",
    "Wants": 375,
    "OriginalPrice": 375,
    "ReducedPrice": 0,
    "PriceReduced": False,
    "Caliber": "6.5mm Carcano",
    "Action": "Bolt action",
    "Bore": "good",
    "Stock": "fair",
    "Type": "Rifle",
    "License": "CNR",
    "Sold": False,
    "imageUrls": [
        "https://images.simpsonltd.org/images/C75280/C75280AT.webp",
        "https://images.simpsonltd.org/images/C75280/C75280BT.webp",
    ],
}

GALLERY = {
    "data": {
        "imageUrls": [
            f"https://images.simpsonltd.org/images/C75280/C75280{letter}.jpg"
            for letter in "ABCDEFG"
        ]
    }
}


def _item(record=None, label="Military Rifles"):
    found = item_from_record(record or RECORD, label)
    assert found is not None
    return found


class TestOneRecordIsNearlyAWholeListing:
    def test_the_sku_is_the_key(self):
        assert _item().external_key == "C75280"

    def test_the_url_is_built_from_it(self):
        """Their React router serves /products/:SKU, so the listing has an
        address even though the catalog arrives as JSON."""
        assert _item().url == "https://www.simpsonltd.com/products/C75280"

    def test_wants_is_the_asking_price(self):
        """Not OriginalPrice: on a reduced listing `Wants` already holds the
        reduced figure and OriginalPrice keeps the old one."""
        assert _item().price == 375.0

    def test_a_reduced_listing_reports_what_it_costs_today(self):
        record = {**RECORD, "Wants": 300, "OriginalPrice": 375, "PriceReduced": True}
        assert _item(record).price == 300.0

    def test_zero_means_no_price_rather_than_free(self):
        record = {**RECORD, "Wants": 0, "OriginalPrice": 0, "ReducedPrice": 0}
        assert _item(record).price is None

    def test_the_caliber_comes_from_the_vendor(self):
        """Which is better than deriving it: they state it per listing."""
        assert _item().caliber == "6.5mm Carcano"

    def test_the_bore_grade_is_the_condition(self):
        """They grade bore and stock separately and this application has one
        condition field. The bore is what a collector asks first."""
        assert _item().condition == "good"

    def test_a_record_with_no_title_is_not_a_listing(self):
        assert item_from_record({**RECORD, "Title": ""}, "x") is None


class TestThePhotographs:
    def test_the_catalogs_thumbnails_become_full_size_names(self):
        """C75280AT.webp is the thumbnail of C75280A.jpg. Deriving it means a
        listing whose gallery request fails still has real photographs."""
        assert full_size("https://images.simpsonltd.org/images/C75280/C75280AT.webp") == (
            "https://images.simpsonltd.org/images/C75280/C75280A.jpg"
        )

    def test_a_name_that_is_not_a_thumbnail_is_left_alone(self):
        url = "https://images.simpsonltd.org/images/C75280/C75280A.jpg"
        assert full_size(url) == url

    def test_the_catalog_entry_is_not_complete(self):
        """Two of seven. Marking it complete would stop the gallery ever being
        fetched."""
        item = _item()
        assert len(item.image_urls) == 2
        assert item.images_are_complete is False

    def test_the_gallery_request_fills_it_in(self, ctx_factory):
        context = ctx_factory()
        context.get_text = lambda _url, **_k: json.dumps(GALLERY)  # type: ignore[method-assign]
        item = SimpsonLtdScraper().with_gallery(context, _item())
        assert len(item.image_urls) == 7
        assert item.images_are_complete is True

    def test_a_failed_gallery_keeps_the_two_it_had(self, ctx_factory):
        """It costs pictures and nothing else — every other field is already
        in hand from the catalog."""
        from app.scrapers.base import ScrapeError

        def refuse(_url, **_kwargs):
            raise ScrapeError("503")

        context = ctx_factory()
        context.get_text = refuse  # type: ignore[method-assign]
        item = SimpsonLtdScraper().with_gallery(context, _item())
        assert len(item.image_urls) == 2
        assert item.price == 375.0


class TestTheEndpoint:
    def test_it_pages_with_page_and_limit(self):
        """The bug this file exists to stop repeating. `currentPage` and
        `itemsPerPage` are what `searchWebItems_v3` beside it takes, and this
        endpoint *accepts* them, echoes `currentPage` back unchanged and serves
        page one every time. The first version used those names and collected
        ten listings per shelf -- 190 against 5,200 -- while making 116
        requests per shelf to do it.
        """
        url = endpoint({"category": "Lugers"}, 4)
        assert "page=4" in url
        assert f"limit={PAGE_SIZE}" in url
        assert "currentPage" not in url
        assert "itemsPerPage" not in url

    def test_it_asks_for_a_hundred_because_that_is_the_ceiling(self):
        """Asking for 250 returns 100, and asking for 10 turns one shelf into
        166 requests."""
        assert PAGE_SIZE == 100

    def test_a_whole_category_needs_no_subcategory(self):
        url = endpoint({"category": "Lugers"}, 1)
        assert "category=Lugers" in url
        assert "subcategory" not in url

    def test_a_shelf_inside_one_carries_both(self):
        url = endpoint({"category": "Long Guns", "subcategory": "Military Rifles"}, 3)
        assert "category=Long+Guns" in url
        assert "subcategory=Military+Rifles" in url
        assert "page=3" in url

    def test_the_subcategory_is_what_a_listing_is_filed_under(self):
        """ "Military Rifles" says more than "Long Guns", and the browse facet
        is the poorer for the broader name."""
        assert label_of({"category": "Long Guns", "subcategory": "Military Rifles"}) == (
            "Military Rifles"
        )
        assert label_of({"category": "Lugers"}) == "Lugers"

    def test_a_subcategory_used_twice_is_qualified(self):
        """ "Mauser" is a shelf of rifles and a shelf of pistols, and so is
        "Fabrique National". Filing both under the bare name put 440 listings
        behind one browse facet that mixed the two."""
        assert label_of({"category": "Long Guns", "subcategory": "Mauser"}) == "Long Guns / Mauser"
        assert label_of({"category": "Hand Guns", "subcategory": "Mauser"}) == "Hand Guns / Mauser"

    def test_the_ambiguous_ones_are_worked_out_rather_than_listed(self):
        """So a shelf added later cannot quietly collide with an existing one."""
        assert {"Mauser", "Fabrique National"} == _AMBIGUOUS_SUBCATEGORIES

    def test_every_shelf_ends_up_with_its_own_label(self):
        """The property the qualifying exists for."""
        labels = [label_of(source) for source in SOURCES]
        assert len(labels) == len(set(labels))


class TestWalkingAShelf:
    def _context(self, ctx_factory, pages):
        served = []

        def answer(url, **_kwargs):
            served.append(url)
            return json.dumps(pages[min(len(served), len(pages)) - 1])

        context = ctx_factory()
        context.get_text = answer  # type: ignore[method-assign]
        return context, served

    def test_it_stops_at_the_stated_total(self, ctx_factory):
        page = {"data": [RECORD], "totalPages": 2}
        context, served = self._context(ctx_factory, [page, page])
        found = list(SimpsonLtdScraper()._walk(context, {"category": "Lugers"}, "Lugers"))
        assert len(found) == 2
        assert len(served) == 2

    def test_and_on_an_empty_page_if_the_total_is_missing(self, ctx_factory):
        context, served = self._context(
            ctx_factory, [{"data": [RECORD]}, {"data": [RECORD]}, {"data": []}]
        )
        found = list(SimpsonLtdScraper()._walk(context, {"category": "Lugers"}, "Lugers"))
        assert len(found) == 2
        assert len(served) == 3

    def test_a_shelf_that_fails_does_not_lose_the_others(self, ctx_factory):
        """One of nineteen is not the catalog: the run goes PARTIAL rather
        than returning nothing."""
        from app.scrapers.base import ScrapeError

        def refuse(_url, **_kwargs):
            raise ScrapeError("500")

        context = ctx_factory()
        context.get_text = refuse  # type: ignore[method-assign]
        assert list(SimpsonLtdScraper()._walk(context, {"category": "Lugers"}, "Lugers")) == []
        assert context.warnings


class TestTheScope:
    """19,201 items, and most of them belong to a different application."""

    def test_the_luger_shelf_is_taken_whole(self):
        assert {"category": "Lugers"} in SOURCES

    def test_the_sporting_shelves_are_not_taken(self):
        """Their Long Guns is 7,806 and 3,057 of those are shotguns."""
        taken = {(s["category"], s.get("subcategory")) for s in SOURCES}
        for sporting in ("Shotguns", "Winchester", "Remington", "Ruger", "Savage", "Anschutz"):
            assert ("Long Guns", sporting) not in taken

    def test_nor_are_the_gear_and_paper_categories(self):
        taken = {s["category"] for s in SOURCES}
        for out in ("Militaria", "Printed Materials", "Firearm Accessories", "Other Items"):
            assert out not in taken

    def test_only_bayonets_are_taken_from_edged_weapons(self):
        edged = [s for s in SOURCES if s["category"] == "Edged Weapons"]
        assert [s.get("subcategory") for s in edged] == ["Bayonets"]

    def test_what_is_left_out_is_written_down(self):
        """So the decision is reviewable rather than implied by an absence."""
        assert any("Shotguns" in line for line in NOT_READ)
        assert any("Militaria" in line for line in NOT_READ)


class TestItIsRegistered:
    def test_by_slug(self):
        assert isinstance(get_scraper("simpson-ltd"), SimpsonLtdScraper)

    def test_it_needs_no_browser(self):
        """The roadmap said it did, on the strength of a 2.8 KB React shell."""
        assert SimpsonLtdScraper.requires_browser is False


@pytest.mark.parametrize(("sku", "expected"), [("C75280", "C75280"), ("K 17/00", "K%2017/00")])
def test_a_sku_with_a_space_is_escaped_in_the_url(sku, expected):
    assert product_url(sku).endswith(expected)


class TestItYieldsRatherThanReturns:
    """A scan of this vendor runs for over an hour. The scan service commits
    after every listing it is handed, so yielding means the catalog lands as it
    arrives; building a list first would write nothing until the end and lose
    all of it to one timeout in the ninetieth minute.
    """

    def test_the_first_listing_arrives_before_the_last_shelf_is_read(self, ctx_factory):
        served: list[str] = []

        def answer(url, **_kwargs):
            served.append(url)
            if "fetchSKU_Inventory" in url:
                return json.dumps(GALLERY)
            return json.dumps({"data": [RECORD], "totalPages": 1})

        context = ctx_factory()
        context.get_text = answer  # type: ignore[method-assign]
        stream = SimpsonLtdScraper().scrape(context)

        first = next(iter(stream))
        assert first.external_key == "C75280"
        # One shelf read and one gallery fetched -- not all nineteen shelves.
        assert len(served) < 4

    def test_an_empty_shop_is_still_an_error(self, ctx_factory):
        from app.scrapers.base import ScrapeError

        context = ctx_factory()
        context.get_text = lambda _url, **_k: json.dumps({"data": []})  # type: ignore[method-assign]
        with pytest.raises(ScrapeError):
            list(SimpsonLtdScraper().scrape(context))
