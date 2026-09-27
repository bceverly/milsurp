"""The Civilian Marksmanship Program: the grades it offers, never its auctions.

Markup below is CMP's, trimmed, from September 2026.
"""

from __future__ import annotations

import pytest

from app.scrapers import get_scraper
from app.scrapers.base import ScrapeError
from app.scrapers.cmp import PAGES, CmpScraper, grade_of
from app.services import classify

GARAND = """<html><head>
<meta property="og:image" content="https://thecmp.org/wp-content/uploads/M1-Ping.jpg" />
</head><body>
<h3>RACK Grade M1 Garand</h3>
<table><tr><td>ITEM #</td><td>DESCRIPTION</td><td>PRICE</td></tr>
<tr><td>RM1RACKRC</td><td>The RM1RACKRC will be built with a reclaimed receiver.</td>
<td>SOLD OUT 01/07/25</td></tr></table>
<h3>Expert Grade M1 Garand</h3>
<table><tr><td>ITEM #</td><td>DESCRIPTION</td><td>PRICE</td></tr>
<tr><td>RM1EXPERTRC</td><td>Commercial barrel chambered for .30-06 Springfield.</td>
<td>$1150</td></tr>
<tr><td>RM1308EXPERTRC</td><td>Commercial barrel chambered for .308 Winchester.</td>
<td>$1150</td></tr>
<tr><td>RM1EXPERTIHCRC</td><td>Built using reclaimed receivers.</td>
<td>SOLD OUT 12/06/25</td></tr></table>
<h3>Custom Shop Special M1 Garand</h3>
<table><tr><td>DESCRIPTION</td><td>PRICE</td></tr>
<tr><td>This Custom Shop Special M1 rifle is meticulously hand crafted</td>
<td>Available $1650 $35 S&amp;H</td></tr></table>
<h3>7.62 NATO VERSION OF THE M1 GARAND</h3>
<table><tr><td>ITEM #</td><td>DESCRIPTION</td><td>PRICE</td></tr>
<tr><td>RM1MK2MOD0</td><td>7.62 NATO version of the M1 Garand</td>
<td>SOLD OUT 02/26/25</td></tr></table>
</body></html>"""

ENFIELD = """<html><body><h2>CMP Sales of the M1917 Enfield</h2>
<table><tr><td>ITEM #</td><td>DESCRIPTION</td><td>PRICE</td></tr>
<tr><td>RM1917SG</td><td>M1917 SERVICE GRADE SERVICE GRADE: Barrel may be dark</td>
<td>Available at Stores</td></tr>
<tr><td>RM1917FCHR</td><td>M1917 &#8211; CHROME 1917 Chrome Rifles were used for ceremonial
purposes. Rifle has been checked with a FIELD gauge.</td><td>Available at Stores</td></tr>
</table></body></html>"""

SPRINGFIELD = """<html><body><h2>CMP SALES OF THE M1903/M1903A3 SPRINGFIELD RIFLES</h2>
<table><tr><td>ITEM #</td><td>DESCRIPTION</td><td>PRICE</td></tr>
<tr><td>RMA3EXPERTRC</td><td>1903A3 reclaimed rifle. Parts meet service grade or higher
criteria. Checked with a FIELD gauge.</td><td>$1050 plus $35 S&amp;H Note: Hot Item!</td></tr>
</table></body></html>"""

KRAG = """<html><body><table><tr><td>ITEM #</td><td>DESCRIPTION</td><td>PRICE</td></tr>
<tr><td>RKRAGXSHORT</td><td>Rifles have had barrels cut to a shorter length</td>
<td>SOLD OUT 12/17/24</td></tr></table></body></html>"""

PISTOLS = """<html><head>
<meta property="og:image" content="https://thecmp.org/wp-content/uploads/1911.jpg" />
</head><body><p>Of the pistols received from the army, 98% are mix-masters.</p>
<p><strong>Service Grade $1300</strong>. Pistol may exhibit minor pitting.</p>
<p><strong>Field Grade $1200</strong>. Pistol may exhibit minor rust.</p>
<p><strong>SOLD OUT &#8211; Range Grade &#8211; $1150</strong>. These are 1911 pistols...</p>
</body></html>"""

EMPTY = "<html><body><h2>M1 Carbine Information</h2><p>None available.</p></body></html>"


def pages(**overrides):
    found = {
        PAGES[0].url: GARAND,
        PAGES[1].url: SPRINGFIELD,
        PAGES[2].url: ENFIELD,
        PAGES[3].url: KRAG,
        PAGES[4].url: EMPTY,
        PAGES[5].url: PISTOLS,
    }
    found.update(overrides)
    return found


@pytest.fixture
def cmp(ctx_factory):
    def build(served):
        context = ctx_factory()

        def fetch(url, **_kwargs):
            if url not in served:
                raise ScrapeError(f"404 {url}")
            return served[url]

        context.get_text = fetch  # type: ignore[method-assign]
        return context

    return build


def scrape(context):
    return {item.external_key: item for item in CmpScraper().scrape(context)}


class TestTheGarandPage:
    def test_each_grade_row_is_a_listing(self, cmp):
        items = scrape(cmp(pages()))
        expert = items["RM1308EXPERTRC"]
        assert expert.title == "CMP Expert Grade M1 Garand, .308 (RM1308EXPERTRC)"
        assert (expert.price, expert.is_sold) == (1150.0, False)
        assert expert.condition == "Expert Grade"

    def test_sold_out_is_sold_and_keeps_no_price(self, cmp):
        """No price is handed over, so the stored one stays."""
        rack = scrape(cmp(pages()))["RM1RACKRC"]
        assert rack.title == "CMP Rack Grade M1 Garand, .30-06 (RM1RACKRC)"
        assert (rack.price, rack.is_sold) == (None, True)

    def test_the_receiver_the_code_names_is_in_the_title(self, cmp):
        ihc = scrape(cmp(pages()))["RM1EXPERTIHCRC"]
        assert "with an International Harvester receiver" in ihc.title

    def test_a_shouted_heading_is_a_title(self, cmp):
        mod0 = scrape(cmp(pages()))["RM1MK2MOD0"]
        assert mod0.title.startswith("CMP 7.62 NATO Version of the M1 Garand")

    def test_the_custom_shop_build_is_not_a_surplus_grade(self, cmp):
        items = scrape(cmp(pages()))
        assert not any("Custom Shop" in item.title for item in items.values())

    def test_the_photo_is_the_page_s_own(self, cmp):
        assert scrape(cmp(pages()))["RM1EXPERTRC"].image_urls == [
            "https://thecmp.org/wp-content/uploads/M1-Ping.jpg"
        ]


class TestTheOtherRifles:
    def test_available_at_stores_is_available_with_no_price(self, cmp):
        service = scrape(cmp(pages()))["RM1917SG"]
        assert service.title == "CMP M1917 Enfield Service Grade (RM1917SG)"
        assert (service.price, service.is_sold) == (None, False)
        assert "CMP's stores only" in service.description

    def test_a_chrome_rifle_has_no_grade_and_a_field_gauge_is_not_one(self, cmp):
        chrome = scrape(cmp(pages()))["RM1917FCHR"]
        assert chrome.title == "CMP M1917 Enfield with a chrome finish (RM1917FCHR)"
        assert chrome.condition is None

    def test_the_code_names_the_grade_before_the_prose_does(self, cmp):
        """ "Service grade or higher criteria" and "a FIELD gauge" are not the
        grade; the code's EXPERT is."""
        springfield = scrape(cmp(pages()))["RMA3EXPERTRC"]
        assert springfield.title == "CMP M1903/M1903A3 Springfield Expert Grade (RMA3EXPERTRC)"
        assert springfield.price == 1050.0

    def test_a_shortened_barrel_is_a_rifle_not_a_barrel(self, cmp):
        krag = scrape(cmp(pages()))["RKRAGXSHORT"]
        found = classify.enrich(krag.title, None, None, category=krag.category)
        assert found["is_rifle"] is True

    def test_a_page_with_nothing_offered_is_fine(self, cmp):
        items = scrape(cmp(pages()))
        assert not any("Carbine" in item.title for item in items.values())


class TestThePistols:
    def test_grades_are_read_from_the_prose(self, cmp):
        items = scrape(cmp(pages()))
        assert items["1911-SERVICE"].price == 1300.0
        assert items["1911-FIELD"].title == "CMP M1911A1 pistol, Field Grade"
        assert (items["1911-RANGE"].price, items["1911-RANGE"].is_sold) == (1150.0, True)


class TestWhatIsNeverDone:
    def test_every_listing_says_eligibility_is_required(self, cmp):
        assert all(
            "cmp_sales/eligibility-requirements" in item.description
            for item in scrape(cmp(pages())).values()
        )

    def test_a_garand_page_with_no_grades_fails_the_scan(self, cmp):
        """It always lists grades. Empty means the layout changed, and carrying
        on would de-list every Garand."""
        with pytest.raises(ScrapeError, match="layout"):
            scrape(cmp(pages(**{PAGES[0].url: EMPTY})))

    def test_a_page_that_will_not_load_fails_the_scan(self, cmp):
        served = pages()
        del served[PAGES[2].url]
        with pytest.raises(ScrapeError):
            scrape(cmp(served))

    def test_only_the_sales_pages_are_read(self):
        """Never the auctions (on GunBroker) or the forums."""
        for page in PAGES:
            assert page.url.startswith("https://thecmp.org/sales-and-service/")


@pytest.mark.parametrize(
    ("code", "grade"),
    [
        ("RM1FIELDRC", "Field"),
        ("RM1308EXPIHCRC", "Expert"),
        ("RM1917SG", "Service"),
        ("RM1CFB", "Field"),
        ("RKRAGXCHR", None),
        ("RKRAGX", None),
    ],
)
def test_grades_from_codes(code, grade):
    assert grade_of(code, "") == grade


def test_it_is_registered():
    assert isinstance(get_scraper("cmp"), CmpScraper)
