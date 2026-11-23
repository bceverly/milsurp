"""Empire Arms — a hand-authored page, parsed by block.

There is no framework under this site: the catalog is one long HTML page whose
styling is applied by wrapping runs of characters, and the scraper cuts it into
listings at the product thumbnails. What that costs is recorded here.
"""

from __future__ import annotations

import functools
import gzip
from datetime import date
from pathlib import Path

import pytest

from app.scrapers import empire_arms
from app.scrapers.empire_arms import (
    EmpireArmsScraper,
    _clean_text,
    _item_key_from_thumb,
    _price,
    _source_for,
    is_current,
    parse_new_stuff,
    parse_page,
)


class TestThePriceIsReadAcrossTheMarkup:
    """Their styling wraps runs of characters, and it does that *inside*
    numbers. One pistol is priced

        . . . $7</span></span></font><font ...><span ...>50.&nbsp;</span>

    which reads "$750." on the page and was stored as **$7** — an Austrian
    Model 1908 Pieper listed at seven dollars.
    """

    def test_a_price_split_by_a_tag(self):
        assert _price('. . . $7</span></font><font size="3"><span>50.&nbsp;</span>') == 750.0

    def test_an_ordinary_one(self):
        assert _price("PHOTOS . . . $750. ") == 750.0

    def test_thousands(self):
        assert _price("$1,250.") == 1250.0

    def test_no_price_at_all(self):
        """Page furniture — a header, an FFL notice — has none, and the caller
        uses that to tell furniture from a listing."""
        assert _price("<b>ANTIQUE &amp; MODERN FIREARMS</b>") is None

    def test_a_space_still_separates(self):
        """The tags are stripped with no separator, which is only safe because
        two digits with nothing but markup between them really were adjacent on
        the page. Anything that renders as a space must still break the run —
        `&nbsp;` is text and survives the strip, because the strip happens
        before unescaping."""
        assert _price("$7&nbsp;50 rounds included") == 7.0

    def test_and_so_does_an_actual_space(self):
        assert _price("$7 50") == 7.0


class TestBlockText:
    def test_a_tag_between_words_becomes_a_space(self):
        """The opposite rule to the price, and both are needed: without the
        space "Excellent</b><b>condition" reads as one word."""
        assert _clean_text("<b>Excellent</b><b>condition</b>") == "Excellent condition"

    def test_entities_are_decoded(self):
        assert _clean_text("Smith &amp; Wesson&nbsp;M&amp;P") == "Smith & Wesson M&P"


class TestTheItemKey:
    @pytest.mark.parametrize(
        ("thumb", "key"),
        [
            ("images/02248-1.jpg", "02248"),
            ("40666-1.jpg", "40666"),
            ("S102719-2.JPG", "s102719"),
        ],
    )
    def test_the_serial_is_the_key(self, thumb, key):
        """Their filenames are the shop's own stock numbers, which is the only
        stable identifier this page offers — there are no product URLs."""
        assert _item_key_from_thumb(thumb) == key


#: Two listings on one inventory page, which is how this shop publishes: a
#: thumbnail opens a block, and the block runs to the next thumbnail.
PAGE = """<html><body>
<img src="210981-1.jpg"> FINN Model 39 Mosin-Nagant, VKT 1941, very good bore. $900
<a href="210981-2.jpg">PHOTOS</a>
<img src="321681-1.jpg"> GERMAN K98k, byf 44, matching. $825 SOLD
<a href="321681-2.jpg">PHOTOS</a>
</body></html>"""


class TestRereadingOneListingsPrice:
    """The watchlist poller's single-page check, where the page is shared.

    Every rifle this shop sells lives at `rifles.htm` -- the same URL, with no
    fragment. The external key is the only thing that says which one, which is
    why `check_price` refuses to answer without it.
    """

    @staticmethod
    def _serving(ctx_factory, html_text):
        context = ctx_factory()
        context.get_text = lambda _url, **_k: html_text  # type: ignore[method-assign]
        return context

    RIFLES = "https://www.empirearms.com/rifles.htm"

    def test_it_answers_for_the_key_it_was_given(self, ctx_factory):
        found = EmpireArmsScraper().check_price(
            self._serving(ctx_factory, PAGE), self.RIFLES, key="rifle:210981"
        )
        assert found is not None
        assert found.price == 900.0
        assert not found.sold_out

    def test_a_second_listing_on_the_same_url(self, ctx_factory):
        """The whole difficulty in one assertion: same URL, different gun."""
        found = EmpireArmsScraper().check_price(
            self._serving(ctx_factory, PAGE), self.RIFLES, key="rifle:321681"
        )
        assert found is not None
        assert found.price == 825.0
        assert found.sold_out

    def test_without_a_key_it_refuses_rather_than_guesses(self, ctx_factory):
        """There is no sensible fallback. "The first price on the page" would
        report one gun's price for another, and somebody acts on what the
        watchlist says."""
        found = EmpireArmsScraper().check_price(self._serving(ctx_factory, PAGE), self.RIFLES)
        assert found is None

    def test_a_key_that_is_gone_is_silence(self, ctx_factory):
        found = EmpireArmsScraper().check_price(
            self._serving(ctx_factory, PAGE), self.RIFLES, key="rifle:000000"
        )
        assert found is None

    def test_a_url_that_is_neither_page_is_refused(self, ctx_factory):
        found = EmpireArmsScraper().check_price(
            self._serving(ctx_factory, PAGE),
            "https://www.empirearms.com/about.htm",
            key="rifle:210981",
        )
        assert found is None

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.empirearms.com/pistols.htm",
            "https://www.empirearms.com/PISTOLS.HTM",
        ],
    )
    def test_the_other_page_is_recognized_too(self, ctx_factory, url):
        assert _source_for(url) is not None

    def test_it_agrees_with_what_a_scan_would_store(self, ctx_factory):
        scanned = {i.external_key: i.price for i in parse_page(PAGE, "Rifle", self.RIFLES)}
        assert scanned  # the fixture parses at all
        for key, expected in scanned.items():
            found = EmpireArmsScraper().check_price(
                self._serving(ctx_factory, PAGE), self.RIFLES, key=key
            )
            assert found is not None, key
            assert found.price == expected, key


#: The "New Stuff" list mailed on 23 November 2026, as the shop served it.
NEW_STUFF_URL = "https://www.empirearms.com/112326.htm"
NEW_STUFF = gzip.decompress(
    (Path(__file__).parent / "fixtures" / "empire-arms" / "new-stuff-112326.htm.gz").read_bytes()
).decode("cp1252")
NEW_STUFF_DAY = date(2026, 11, 23)


@functools.cache
def new_stuff_listings():
    """Parsed once: the classifier runs over every listing, which is not free."""
    return {item.external_key: item for item in parse_new_stuff(NEW_STUFF, NEW_STUFF_URL)}


class TestTheNewStuffList:
    """The dated page the shop mails out, laid out without thumbnails: every
    listing is prose ending in a PHOTOS link and a price."""

    @pytest.fixture
    def listings(self):
        return new_stuff_listings()

    def test_every_listing_is_read(self, listings):
        """The email said twenty-four; the page carries twenty-five, and the
        page is what is for sale."""
        assert len(listings) == 25

    def test_a_listing_as_the_page_has_it(self, listings):
        enfield = listings["rifle:aj12087"]
        assert enfield.title == "BRITISH Model No.4 Mk.1 Lee-Enfield"
        assert enfield.price == 850.0
        assert enfield.caliber == ".303 British"
        assert enfield.url == NEW_STUFF_URL
        assert enfield.image_urls == ["https://www.empirearms.com/AJ12087.jpg"]
        assert not enfield.is_sold
        assert "Maltby in 1943" in enfield.description

    def test_one_already_sold_says_so(self, listings):
        assert listings["rifle:zm4368"].is_sold

    def test_the_heading_above_the_first_is_not_part_of_it(self, listings):
        first = listings["rifle:aj12087"]
        assert "MILITARY RIFLES" not in first.description
        assert "Prices DO NOT include shipping" not in first.description

    def test_the_key_is_the_one_rifles_htm_gives_the_same_gun(self, listings):
        """There the thumbnail is AJ12087-1.jpg; the key drops the -1. Unsold
        after a day, the gun moves there, and its listing moves with it."""
        moved = parse_page(
            '<img src="AJ12087-1.jpg"><p><strong>BRITISH No.4</strong> ... $850.</p>',
            "Rifle",
            "https://www.empirearms.com/rifles.htm",
        )
        assert moved[0].external_key in listings

    def test_a_handgun_is_filed_as_one(self):
        page = (
            "<p>HANDGUNS</p>GERMAN Model P.38 Walther semiautomatic pistol # 1234a (9mm) "
            '<a href="1234a.jpg">PHOTOS</a> . . . $1250.<br>'
            "U.S.A. Model 1917 Smith &amp; Wesson revolver # 5678 (.45 ACP) "
            '<a href="5678.jpg">PHOTOS</a> . . . $1450. SOLD<br>'
            "SWISS Model 1911 Schmidt-Rubin rifle # 9 (7.5x55) "
            '<a href="9.jpg">PHOTOS</a> . . . $650.<br>'
        )
        keys = [item.external_key for item in parse_new_stuff(page, NEW_STUFF_URL)]
        assert keys == ["handgun:1234a", "handgun:5678", "rifle:9"]

    def test_a_photos_link_with_no_price_or_sold_is_not_a_listing(self):
        page = '<p>See the <a href="shop.jpg">PHOTOS</a> of our table.</p>'
        assert parse_new_stuff(page, NEW_STUFF_URL) == []


class TestWhichNewStuffPagesAreRead:
    """Valid "for only 24 HOURS" after their date, then archived."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.empirearms.com/112326.htm",
            "https://empirearms.com/112326.htm",
            "https://www.empirearms.com/112326.HTM",
        ],
    )
    def test_it_is_an_email_page(self, url):
        assert EmpireArmsScraper().is_email_page(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.empirearms.com/rifles.htm",
            "https://www.empirearms.com/newstuff.htm",
            "https://www.empirearms.com/993326.htm",  # no such date
            "https://www.example.com/112326.htm",
        ],
    )
    def test_these_are_not(self, url):
        assert not EmpireArmsScraper().is_email_page(url)

    @pytest.mark.parametrize(
        ("today", "current"),
        [
            (date(2026, 11, 22), False),  # not yet: a typed date, or a clock
            (date(2026, 11, 23), True),
            (date(2026, 11, 24), True),
            (date(2026, 11, 25), False),
        ],
    )
    def test_current_on_its_day_and_the_next(self, today, current):
        assert is_current(NEW_STUFF_URL, today) is current


class TestAScanReadsTheListTheEmailNamed:
    @pytest.fixture
    def served(self, ctx_factory, monkeypatch):
        monkeypatch.setattr(empire_arms, "_shop_today", lambda: NEW_STUFF_DAY)
        asked: list[str] = []

        def get_text(url, **_kwargs):
            asked.append(url)
            return NEW_STUFF if url == NEW_STUFF_URL else PAGE

        def make(pages):
            context = ctx_factory()
            context.email_pages = pages
            context.get_text = get_text  # type: ignore[method-assign]
            return context

        return make, asked

    def test_the_list_s_listings_join_the_scan(self, served):
        make, asked = served
        found = list(
            EmpireArmsScraper().scrape(
                make(["https://empirearms.com/112326.htm", "https://www.empirearms.com/rifles.htm"])
            )
        )
        keys = [item.external_key for item in found]
        assert asked[0] == NEW_STUFF_URL  # once, under the address the scan stores
        assert asked.count(NEW_STUFF_URL) == 1
        assert "rifle:aj12087" in keys
        assert "rifle:210981" in keys  # and the inventory pages as always

    def test_an_old_list_is_left_alone(self, served):
        make, asked = served
        list(EmpireArmsScraper().scrape(make(["https://www.empirearms.com/111926.htm"])))
        assert all("1119" not in url for url in asked)

    def test_a_list_that_fails_to_load_warns_and_the_rest_is_read(self, ctx_factory, monkeypatch):
        monkeypatch.setattr(empire_arms, "_shop_today", lambda: NEW_STUFF_DAY)
        context = ctx_factory()
        context.email_pages = [NEW_STUFF_URL]

        def get_text(url, **_kwargs):
            if url == NEW_STUFF_URL:
                raise OSError("connection reset")
            return PAGE

        context.get_text = get_text  # type: ignore[method-assign]
        found = list(EmpireArmsScraper().scrape(context))
        assert found
        assert any("New Stuff" in warning for warning in context.warnings)

    def test_a_listing_s_price_is_re_read_from_the_list(self, ctx_factory):
        context = ctx_factory()
        context.get_text = lambda _url, **_k: NEW_STUFF  # type: ignore[method-assign]
        found = EmpireArmsScraper().check_price(context, NEW_STUFF_URL, key="rifle:6558")
        assert found is not None
        assert found.price == 2450.0
