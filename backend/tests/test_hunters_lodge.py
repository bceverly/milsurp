"""The Hunter's Lodge scraper: finding the flyer, and knowing when not to read it.

None of these touch the network. The home page is a stub of the real Wix
markup, and the flyer is drawn here, so the tests describe the scraper rather
than the state of somebody's website this morning.
"""

from __future__ import annotations

import io

import pytest
import responses
from conftest import needs_ocr
from PIL import Image, ImageDraw

from app.scrapers import ScrapeContext, ScrapeError
from app.scrapers.hunters_lodge import HuntersLodgeScraper

FLYER_MEDIA = "10a0ff_57a8a017e5354d569d42837e8c3b4ae5~mv2"
FLYER_DISPLAY = (
    f"https://static.wixstatic.com/media/{FLYER_MEDIA}.jpg"
    "/v1/fill/w_600,h_844,al_c,q_85/July%202026%20Full%20Page_indd.jpg"
)
FLYER_ORIGINAL = f"https://static.wixstatic.com/media/{FLYER_MEDIA}.jpg"
HOME = "https://www.hunterslodge.com/"


def home_page(issue: str = "July  2026", flyer_src: str = FLYER_DISPLAY) -> str:
    """A cut-down copy of the shape the real Wix page has."""
    return f"""
    <html><body>
      <img src="https://static.wixstatic.com/media/36222f_logo~mv2.png"
           alt="logo" width="120" height="60"/>
      <div data-testid="richTextElement">
        <h6>Issue from Firearms News for&nbsp; for {issue}</h6>
      </div>
      <div class="wixui-image">
        <img src="{flyer_src}" alt="Full Page.indd.jpg" width="600" height="844"/>
      </div>
      <p>Check or money order only.</p>
    </body></html>
    """


def flyer_bytes(width: int = 1600, height: int = 2200) -> bytes:
    """A page with a ruled division and one readable listing in each column."""
    page = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(page)
    draw.rectangle([width // 2 - 5, 0, width // 2 + 5, height], fill=0)
    for left in (40, width // 2 + 40):
        for top in range(60, height - 60, 80):
            draw.rectangle([left, top, left + width // 2 - 100, top + 30], fill=0)
    buffer = io.BytesIO()
    page.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


@pytest.fixture
def ctx(app_config):
    context = ScrapeContext(app_config)
    yield context
    context.close()


class TestFindingTheFlyer:
    def test_the_largest_image_is_the_flyer_not_the_logo(self, app_config):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(home_page(), "html.parser")
        assert HuntersLodgeScraper()._find_flyer(soup) == FLYER_DISPLAY

    def test_the_issue_is_read_from_the_page(self, app_config):
        from bs4 import BeautifulSoup

        scraper = HuntersLodgeScraper()
        assert scraper._find_issue(BeautifulSoup(home_page(), "html.parser")) == "July 2026"
        assert (
            scraper._find_issue(BeautifulSoup(home_page("December 2025"), "html.parser"))
            == "December 2025"
        )

    def test_a_page_with_no_issue_line_still_works(self, app_config):
        from bs4 import BeautifulSoup

        html = '<html><body><img src="https://x/y~mv2.jpg" width="600" height="800"/></body></html>'
        assert HuntersLodgeScraper()._find_issue(BeautifulSoup(html, "html.parser")) is None


class TestFullResolution:
    """Wix serves a resize by default; OCR needs the original."""

    @responses.activate
    @needs_ocr
    def test_the_transform_is_stripped_before_downloading(self, ctx):
        responses.add(responses.GET, HOME, body=home_page(), content_type="text/html")
        responses.add(responses.GET, FLYER_ORIGINAL, body=flyer_bytes(), content_type="image/jpeg")
        list(HuntersLodgeScraper().scrape(ctx))

        requested = [call.request.url for call in responses.calls]
        assert FLYER_ORIGINAL in requested
        # The 600x844 version the page displays is far too small to read.
        assert FLYER_DISPLAY not in requested

    @responses.activate
    def test_a_flyer_too_small_to_read_is_an_error(self, ctx):
        responses.add(responses.GET, HOME, body=home_page(), content_type="text/html")
        responses.add(
            responses.GET,
            FLYER_ORIGINAL,
            body=flyer_bytes(width=300, height=400),
            content_type="image/jpeg",
        )
        with pytest.raises(ScrapeError, match="too small"):
            list(HuntersLodgeScraper().scrape(ctx))


class TestChangeDetection:
    """The property that keeps this scraper polite, and keeps the catalog alive.

    A new flyer appears every month or two. Re-deriving forty listings from an
    unchanged image would be minutes of OCR to arrive back where we started;
    returning nothing instead would de-list the entire catalog. So an unchanged
    flyer means one request and an explicit "nothing has changed".
    """

    @responses.activate
    def test_an_unchanged_flyer_reads_nothing_and_downloads_nothing(self, app_config):
        responses.add(responses.GET, HOME, body=home_page(), content_type="text/html")

        # already_seen() true means "we hold listings from this flyer".
        context = ScrapeContext(app_config, already_seen=lambda _prefix: True)
        items = list(HuntersLodgeScraper().scrape(context))
        context.close()

        assert items == []
        assert context.unchanged is True
        # One request: the home page. The flyer itself is never fetched.
        assert len(responses.calls) == 1

    @responses.activate
    @needs_ocr
    def test_a_new_flyer_is_read(self, app_config):
        responses.add(responses.GET, HOME, body=home_page(), content_type="text/html")
        responses.add(responses.GET, FLYER_ORIGINAL, body=flyer_bytes(), content_type="image/jpeg")
        context = ScrapeContext(app_config, already_seen=lambda _prefix: False)
        list(HuntersLodgeScraper().scrape(context))
        context.close()

        assert context.unchanged is False
        assert len(responses.calls) == 2

    @responses.activate
    @needs_ocr
    def test_the_issue_month_is_part_of_the_signature(self, app_config):
        """A re-scanned flyer for a new month is a new flyer.

        The media id changes when a file is uploaded, but the two signals are
        both used: a vendor who re-uploads the same image under a new issue has
        published something new.
        """
        asked: list[str] = []
        responses.add(responses.GET, HOME, body=home_page("August 2026"), content_type="text/html")
        responses.add(responses.GET, FLYER_ORIGINAL, body=flyer_bytes(), content_type="image/jpeg")

        def remember(prefix: str) -> bool:
            asked.append(prefix)
            return False

        context = ScrapeContext(app_config, already_seen=remember)
        list(HuntersLodgeScraper().scrape(context))
        context.close()

        assert asked
        assert "august-2026" in asked[0]
        assert FLYER_MEDIA in asked[0]


class TestWhenTheSiteChanges:
    @responses.activate
    def test_no_image_at_all_is_a_clear_failure(self, ctx):
        responses.add(
            responses.GET,
            HOME,
            body="<html><body><p>Under construction</p></body></html>",
            content_type="text/html",
        )
        with pytest.raises(ScrapeError, match="No flyer image"):
            list(HuntersLodgeScraper().scrape(ctx))

    @responses.activate
    @needs_ocr
    def test_an_unreadable_flyer_still_yields_the_flyer_itself(self, ctx):
        """Better one item saying "go and look" than a scan that shows nothing."""
        blank = Image.new("L", (1600, 2200), 255)
        buffer = io.BytesIO()
        blank.save(buffer, format="JPEG")
        responses.add(responses.GET, HOME, body=home_page(), content_type="text/html")
        responses.add(
            responses.GET, FLYER_ORIGINAL, body=buffer.getvalue(), content_type="image/jpeg"
        )

        items = list(HuntersLodgeScraper().scrape(ctx))
        assert len(items) == 1
        assert items[0].price is None
        assert "advertisement" in items[0].title.lower()
        assert items[0].generated_images
        assert ctx.warnings


class TestTheListingsItProduces:
    @responses.activate
    @needs_ocr
    def test_each_listing_carries_its_own_crop_and_a_stable_key(self, ctx):
        responses.add(responses.GET, HOME, body=home_page(), content_type="text/html")
        responses.add(responses.GET, FLYER_ORIGINAL, body=flyer_bytes(), content_type="image/jpeg")
        items = list(HuntersLodgeScraper().scrape(ctx))

        assert items
        for item in items:
            assert item.external_key.startswith(FLYER_MEDIA)
            assert "july-2026" in item.external_key
            assert " " not in item.external_key
            assert item.generated_images
            key, data = item.generated_images[0]
            assert key.endswith(".png")
            assert Image.open(io.BytesIO(data)).format == "PNG"
            # No per-product page exists to link to.
            assert item.url == HOME


class TestKeysFollowTheProductNotThePage:
    """Why a listing's key is derived from its name and not its position.

    It was the ordinal — "…-013" — which is stable only for as long as the
    reader is. Improving the reader by one listing shifted every key after it
    onto a different product, and the scan service read that as the whole lower
    half of the flyer changing price at once: one such change produced
    seventeen price changes and ten drops, none of which had happened.
    """

    def keys(self, titles):
        scraper = HuntersLodgeScraper()
        taken: dict[str, int] = {}
        return [scraper._key_for("sig-july-2026", title, taken) for title in titles]

    def test_removing_a_listing_does_not_move_the_others(self):
        before = self.keys(["COLT PP .38 FRAMES", "C&R/FFL", "CZ 52 ASSAULT RIFLES"])
        after = self.keys(["COLT PP .38 FRAMES", "CZ 52 ASSAULT RIFLES"])

        assert after == [before[0], before[2]]

    def test_the_same_name_keeps_the_same_key(self):
        assert self.keys(["S&W MODEL 10 PISTOLS"]) == self.keys(["s&w  model 10 pistols"])

    def test_different_names_get_different_keys(self):
        first, second = self.keys(["COLT PP .38 FRAMES", "CZ 52 ASSAULT RIFLES"])
        assert first != second

    def test_the_flyer_is_still_part_of_every_key(self):
        """So that a new flyer is a new catalog rather than a price change."""
        july = self.keys(["S&W MODEL 10 PISTOLS"])[0]
        scraper = HuntersLodgeScraper()
        august = scraper._key_for("sig-august-2026", "S&W MODEL 10 PISTOLS", {})
        assert july != august
        assert july.startswith("sig-july-2026-")

    def test_two_listings_with_one_name_are_told_apart(self):
        first, second = self.keys(["BAYONET GRAB BAG", "BAYONET GRAB BAG"])
        assert first != second
        assert second.startswith(first)

    @responses.activate
    @needs_ocr
    def test_the_keys_a_real_read_produces_are_all_distinct(self, ctx):
        responses.add(responses.GET, HOME, body=home_page(), content_type="text/html")
        responses.add(responses.GET, FLYER_ORIGINAL, body=flyer_bytes(), content_type="image/jpeg")

        items = list(HuntersLodgeScraper().scrape(ctx))

        keys = [item.external_key for item in items]
        assert len(keys) == len(set(keys))
