"""eBayonet: five Word-exported pages and no storefront behind them.

The shape that matters is that **a listing is a run of paragraphs**, not one
paragraph. Reading only the paragraph that opens a listing finds a price on 11%
of them; walking to the next stock number finds one on 100%. That was the first
measurement taken here and it was wrong, which is why it is the first thing
pinned.
"""

from __future__ import annotations

from app.scrapers import get_scraper
from app.scrapers.ebayonet import EBayonetScraper, parse_page

#: The real markup's shape, trimmed. Word writes &nbsp;, splits runs mid-word
#: with <span>, and types photo URLs into the prose as both a link and its own
#: text -- which is why the same URL appears twice in one paragraph.
PAGE = """
<html><body>
<p class=MsoNormal><span>Some prose about the collection.</span></p>

<p class=MsoNormal>18782 Afghan issued P1903 bayonet with scabbard.
   WILKINSON-LONDON. Dari marking on both upper and lower tang.</p>
<p class=MsoNormal><a href="https://ebayonet.com/18700/18782.jpg">
   https://ebayonet.com/18700/18782.jpg</a></p>
<p class=MsoNormal><a href="https://ebayonet.com/18700/18782a.jpg">
   https://ebayonet.com/18700/18782a.jpg</a></p>
<p class=MsoNormal>$110</p>

<p class=MsoNormal>12063 Argentine M1909/Spanish M1943 bayonet lug adapters,
   a long enough description to count as one.</p>
<p class=MsoNormal>http://ebayonet.com/12000/12063EXAMPLE.jpg</p>
<p class=MsoNormal>$7 each or 3 for $20</p>
<p class=MsoNormal>I have a scant few of these with the original locking pin $10 each</p>

<p class=MsoNormal>15450 Mukden Mauser bayonet. SEE LISTING UNDER MANCHUKUO.</p>

<p class=MsoNormal>16601 M1950? Hakim bayonet with scabbard. Scabbard does not
   match but has an Arabic serial number.&nbsp; SOLD</p>
<p class=MsoNormal>$275</p>
</body></html>
"""


def _by_key(page=PAGE, name="bayonetsa_f.htm"):
    return {item.external_key: item for item in parse_page(page, name)}


class TestReadingAListing:
    def test_the_stock_number_is_the_key(self):
        assert set(_by_key()) == {"18782", "12063", "16601"}

    def test_the_price_comes_from_a_later_paragraph(self):
        """The whole shape of this site. In its own paragraph, after the
        photographs, and with nothing tying it to the listing but order."""
        assert _by_key()["18782"].price == 110.0

    def test_photographs_are_read_out_of_the_prose(self):
        """There is not one <img> tag in a megabyte of this site's HTML."""
        item = _by_key()["18782"]
        assert item.image_urls == [
            "https://ebayonet.com/18700/18782.jpg",
            "https://ebayonet.com/18700/18782a.jpg",
        ]

    def test_a_photo_written_twice_is_stored_once(self):
        """Word writes the URL as the link *and* as its text."""
        assert len(_by_key()["18782"].image_urls) == 2

    def test_everything_is_a_bayonet(self):
        assert {item.category for item in parse_page(PAGE, "x.htm")} == {"Bayonet"}

    def test_sold_is_noticed(self):
        assert _by_key()["16601"].is_sold is True

    def test_the_url_says_which_page_to_look_on(self):
        """There are no product pages, so this is the only address a listing
        has."""
        assert _by_key()["18782"].url.endswith("/bayonetsa_f.htm#18782")


class TestThePriceOfTheWrongThing:
    """A listing's prose quotes prices of other things -- "with the original
    locking pin $10 each" -- so a dollar sign anywhere is not the asking price.
    """

    def test_the_listings_own_price_wins(self):
        assert _by_key()["12063"].price == 7.0

    def test_a_long_paragraph_is_prose_and_not_a_price(self):
        item = _by_key()["12063"]
        assert item.price != 10.0
        assert "locking pin" in (item.description or "")


class TestCrossReferences:
    """A bayonet carried by two countries is written out on both of their
    pages: once in full, once as a pointer. Eleven stock numbers are duplicated
    that way across the live catalog, and the external key is the stock number
    -- so keeping both means one overwrites the other on upsert, and which one
    depends on the order the pages were read in.
    """

    def test_a_pointer_is_not_a_listing(self):
        assert "15450" not in _by_key()

    def test_the_richer_row_wins_when_neither_says_so(self):
        """Three copies of one stock number sit on a single page with no
        marker between them. A real listing has a price and photographs; a
        stub has neither."""
        page = """
        <p>15379 Post WWI Belgian Made Ersatz bayonet with a full description here.</p>
        <p>https://ebayonet.com/15300/15379.jpg</p>
        <p>$200</p>
        <p>15379 Post WWI Belgian Made Ersatz bayonet with a full description here.</p>
        """
        found = parse_page(page, "x.htm")
        assert len(found) == 1
        assert found[0].price == 200.0


class TestItIsRegistered:
    def test_by_slug(self):
        assert isinstance(get_scraper("ebayonet"), EBayonetScraper)

    def test_it_needs_no_browser(self):
        """Five static files. The roadmap filed this as needing one."""
        assert EBayonetScraper.requires_browser is False


class TestRereadingOneListingsPrice:
    """The watchlist poller's single-page check, on a shop with no pages.

    A listing here is a paragraph on a shared country page, so its URL is that
    page plus a fragment and the fragment is the only thing that says which
    bayonet. There is nothing generic to read: no schema.org, no meta tag, no
    storefront.
    """

    @staticmethod
    def _serving(ctx_factory, html_text, seen=None):
        context = ctx_factory()

        def fake_get_text(url, **_kwargs):
            if seen is not None:
                seen.append(url)
            return html_text

        context.get_text = fake_get_text  # type: ignore[method-assign]
        return context

    URL = "https://www.ebayonet.com/bayonetsa_f.htm#18782"

    def test_it_finds_the_listing_the_fragment_names(self, ctx_factory):
        found = EBayonetScraper().check_price(self._serving(ctx_factory, PAGE), self.URL)
        assert found is not None
        assert found.price == 110.0

    def test_the_key_wins_over_the_fragment(self, ctx_factory):
        found = EBayonetScraper().check_price(
            self._serving(ctx_factory, PAGE), self.URL, key="16601"
        )
        assert found is not None
        assert found.price == 275.0

    def test_a_sold_bayonet_says_so(self, ctx_factory):
        found = EBayonetScraper().check_price(
            self._serving(ctx_factory, PAGE), self.URL, key="16601"
        )
        assert found is not None
        assert found.sold_out

    def test_the_fragment_is_not_sent_to_the_shop(self, ctx_factory):
        """It is a position in a document, not part of the address."""
        seen: list[str] = []
        EBayonetScraper().check_price(self._serving(ctx_factory, PAGE, seen), self.URL)
        assert seen == ["https://www.ebayonet.com/bayonetsa_f.htm"]

    def test_a_listing_no_longer_on_the_page_is_silence(self, ctx_factory):
        found = EBayonetScraper().check_price(
            self._serving(ctx_factory, PAGE), self.URL, key="00000"
        )
        assert found is None

    def test_a_url_naming_nothing_is_refused(self, ctx_factory):
        found = EBayonetScraper().check_price(
            self._serving(ctx_factory, PAGE), "https://www.ebayonet.com/bayonetsa_f.htm"
        )
        assert found is None

    def test_it_agrees_with_what_a_scan_would_store(self, ctx_factory):
        """The point of reusing parse_page. Flattening this page and taking the
        price nearest an item number matched the stored value on four of
        sixteen real listings, and twice gave two neighbours each other's."""
        scanned = {item.external_key: item.price for item in parse_page(PAGE, "bayonetsa_f.htm")}
        for key, expected in scanned.items():
            if expected is None:
                continue
            found = EBayonetScraper().check_price(
                self._serving(ctx_factory, PAGE), self.URL, key=key
            )
            assert found is not None, key
            assert found.price == expected, key
