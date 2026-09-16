"""Empire Arms — a hand-authored page, parsed by block.

There is no framework under this site: the catalog is one long HTML page whose
styling is applied by wrapping runs of characters, and the scraper cuts it into
listings at the product thumbnails. What that costs is recorded here.
"""

from __future__ import annotations

import pytest

from app.scrapers.empire_arms import (
    EmpireArmsScraper,
    _clean_text,
    _item_key_from_thumb,
    _price,
    _source_for,
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
