"""Empire Arms — a hand-authored page, parsed by block.

There is no framework under this site: the catalog is one long HTML page whose
styling is applied by wrapping runs of characters, and the scraper cuts it into
listings at the product thumbnails. What that costs is recorded here.
"""

from __future__ import annotations

import pytest

from app.scrapers.empire_arms import _clean_text, _item_key_from_thumb, _price


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
