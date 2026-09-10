"""AIM Surplus — a JSON API found where a browser was assumed.

The fourth site this project filed as "needs a browser" that did not, after
J&G Sales, Centerfire and SARCO. What is pinned here is the shape of the two
routes, the two decisions about which sections to read, and the one fact about
this shop that nothing on the site will tell the next person: where its images
live.
"""

from __future__ import annotations

import json

import pytest

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.aim_surplus import (
    IMAGE_BASE,
    PAGE_SIZE,
    AimSurplusScraper,
    _images,
    _price,
    _properties,
)
from app.services import classify


class TestItIsRegistered:
    def test_the_registry_knows_it(self):
        assert isinstance(get_scraper("aim-surplus"), AimSurplusScraper)

    def test_and_lists_it(self):
        assert AimSurplusScraper in SCRAPER_CLASSES

    def test_no_browser_is_needed(self):
        """The whole point. The category page is 39KB of Vue scaffolding with
        no prices in it, and the conclusion drawn from that was headless
        Chrome; it needed a look at the JSON their own front end calls."""
        assert AimSurplusScraper.requires_browser is False


class TestWhichSectionsAreRead:
    """Two of their seven firearm sections, chosen by measuring all seven."""

    def sections(self):
        return {source["category"]: source["id"] for source in AimSurplusScraper.sources}

    def test_the_two_on_subject_sections(self):
        assert self.sections() == {"Police Trade-Ins": 744, "Curio and Relics": 42}

    def test_the_police_section_reads_as_police_surplus(self):
        """Which is what puts these in their own browse bucket. The category
        name is the only thing that says so — no title does."""
        assert classify._is_police_surplus("Police Trade-Ins", is_firearm=True)

    def test_and_curio_and_relics_does_not(self):
        """It is milsurp, not a department trade-in, and belongs under Rifles
        and Handguns with the rest of the surplus."""
        assert not classify._is_police_surplus("Curio and Relics", is_firearm=True)

    def test_a_category_is_a_number_not_a_path(self):
        """`/data/search` filters on a numeric id; the path form 404s. The id
        is on the category page as `data-category-id`."""
        assert all(isinstance(source["id"], int) for source in AimSurplusScraper.sources)


class TestTheImagesAreOnCloudFront:
    """The one thing about this shop nothing server-side will tell you.

    The API returns bare filenames and no page anywhere carries a product
    image, because the site renders entirely client-side — fourteen guessed
    paths returned 404. The bucket is named in exactly one place: an inline Vue
    template binding a *category* thumbnail to
    `'https://dvjr4l3xblvos.cloudfront.net/categories/' + category.image`.
    """

    def test_the_base_is_the_products_sibling_of_that_path(self):
        assert IMAGE_BASE == "https://dvjr4l3xblvos.cloudfront.net/products/"

    def test_the_master_image_is_preferred(self):
        """`master` is the original; x40/x200/x400/x1200 beside it are resizes,
        and this catalog stores full resolution."""
        urls = _images([{"x200": "a_200.png", "x400": "a_400.png", "master": "a.png"}])
        assert urls == [f"{IMAGE_BASE}a.png"]

    def test_it_falls_back_through_the_sizes(self):
        """A grid record carries only a thumbnail, and something is better than
        nothing until the detail fetch brings the gallery."""
        assert _images([{"x200": "a_200.png"}]) == [f"{IMAGE_BASE}a_200.png"]

    def test_the_gallery_keeps_the_shop_s_order(self):
        urls = _images([{"master": "one.png"}, {"master": "two.png"}])
        assert urls == [f"{IMAGE_BASE}one.png", f"{IMAGE_BASE}two.png"]

    def test_rubbish_in_the_array_is_skipped(self):
        assert _images([None, "nope", {}, {"master": "ok.png"}]) == [f"{IMAGE_BASE}ok.png"]

    def test_a_video_in_the_gallery_is_not_a_photograph(self):
        """Their gallery mixes the two, and a video reuses `master` to carry a
        YouTube id rather than a filename. Read as a filename it becomes a
        CloudFront key that does not exist, and the bucket answers 403 rather
        than 404 — which reads as a blocked download instead of a wrong URL.
        Eight photographs were stuck that way across the police trade-ins."""
        urls = _images(
            [
                {"master": "371-66e9976e1a21c.png"},
                {"embed": "zPvfPM28-SI", "master": "zPvfPM28-SI"},
            ]
        )
        assert urls == [f"{IMAGE_BASE}371-66e9976e1a21c.png"]


class TestTheirPropertiesAreReadNotParsed:
    """Manufacturer, Caliber and Capacity arrive as named fields rather than as
    words in a title. Very little else on this list does that."""

    RECORD = {
        "properties": [
            {"name": "Product Type", "value": "Curio and Relics"},
            {"name": "Manufacturer", "value": "Swiss"},
            {"name": "Caliber", "value": "7.65 Parabellum"},
            {"name": "Capacity", "value": "8rd"},
        ]
    }

    def test_they_are_keyed_by_lower_cased_name(self):
        fields = _properties(self.RECORD)
        assert fields["manufacturer"] == "Swiss"
        assert fields["caliber"] == "7.65 Parabellum"

    def test_a_record_without_them_yields_nothing(self):
        assert _properties({}) == {}
        assert _properties({"properties": None}) == {}

    def test_the_first_value_for_a_name_wins(self):
        fields = _properties(
            {"properties": [{"name": "Caliber", "value": "9mm"}, {"name": "Caliber", "value": "x"}]}
        )
        assert fields["caliber"] == "9mm"


class TestPriceReading:
    def test_the_asking_price(self):
        assert _price({"price": "429.95"}) == 429.95

    def test_it_falls_back_to_the_lowest(self):
        assert _price({"price": "0.00", "lowest_price": 2495.0}) == 2495.0

    def test_a_record_with_no_usable_price_says_so(self):
        """None, not zero: "free" and "not published" are different claims, and
        this catalog shows the second as "Call for price"."""
        assert _price({}) is None
        assert _price({"price": None, "lowest_price": ""}) is None

    def test_nonsense_does_not_raise(self):
        assert _price({"price": "call us"}) is None


class TestTheSearchQuery:
    """Every parameter their front end sends, including the empty ones.

    The endpoint answers 500 rather than defaulting when they are missing,
    which is exactly what made it look like a route that was not there —
    `/data/search?q=glock` is a 500, and the full form is a 200.
    """

    def query_for(self, monkeypatch, ctx_factory):
        seen = {}
        context = ctx_factory()

        def fake_get_text(url, **_kwargs):
            seen["url"] = url
            return json.dumps({"products": [], "pages": 1})

        monkeypatch.setattr(context, "get_text", fake_get_text)
        AimSurplusScraper()._search(context, 744, 2)
        return seen["url"]

    def test_it_sends_the_whole_parameter_set(self, monkeypatch, ctx_factory):
        url = self.query_for(monkeypatch, ctx_factory)
        for part in ("q=", "g=", "category=744", "filter=", "sort_by=", "mode=category"):
            assert part in url, f"{part} missing from {url}"

    def test_the_page_and_size_are_carried(self, monkeypatch, ctx_factory):
        url = self.query_for(monkeypatch, ctx_factory)
        assert f"pagesize={PAGE_SIZE}" in url
        assert "page=2" in url

    def test_a_non_json_answer_is_a_scrape_error(self, monkeypatch, ctx_factory):
        from app.scrapers.base import ScrapeError

        context = ctx_factory()
        monkeypatch.setattr(context, "get_text", lambda *_a, **_k: "<html>nope</html>")
        with pytest.raises(ScrapeError, match="did not return JSON"):
            AimSurplusScraper()._search(context, 744, 1)
