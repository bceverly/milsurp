"""Joe Salter: an OpenCart shop whose own count is larger than its own pages.

The measurement that shaped this scraper is that **"Showing 1 to 15 of 116"
sits above a page carrying fourteen**, and walking every page of that section
yields 102 rather than 116. Asking for ``?limit=100`` yields the same 102 --
so the fourteen are counted by the storefront and not rendered by it. The
stated total is therefore not a stopping condition, and the first version of
this scraper used it as one and stopped a page early.

The other shape worth pinning is that **the catalog tile is already a whole
listing** -- number, title, price -- so a detail page that fails costs a
description and nothing else.
"""

from __future__ import annotations

import dataclasses

from app.config import RobotsException
from app.robots import Robots
from app.scrapers import get_scraper
from app.scrapers.joe_salter import (
    PAGE_SIZE,
    SOURCES,
    JoeSalterScraper,
    parse_catalog,
)

#: One tile, the way OpenCart writes it and this shop leaves it. The price is
#: the only thing in the tile that is not also in the title.
TILE = """
<div class="product-layout">
  <div class="product-thumb">
    <div class="image"><a href="https://shop.joesalter.com/Very-Fine-Hopkins-Allen">
      <img src="https://shop.joesalter.com/image/cache/catalog/53643-228x228.jpg"></a></div>
    <div class="caption">
      <h4><a href="https://shop.joesalter.com/Very-Fine-Hopkins-Allen">Item #: 53643
        Very Fine Hopkins &amp; Allen Top Break Revolver 32 S&amp;W</a></h4>
      <p>Serial #8013, .32 S&amp;W, 3 inch round ribbed barrel with a bright
         bore... ( read more )</p>
      <p class="price">$495.00</p>
    </div>
    <div class="button-group"><button>Add To Cart</button></div>
  </div>
</div>
"""

PAGE = f"""<html><body>
<div class="row">{TILE}</div>
<div class="text-right">Showing 1 to 15 of 116 (8 Pages)</div>
</body></html>"""


#: A product page: the gallery carousel, then the related-products strip.
DETAIL = """<html><body>
  <h1>Pair of Howdah Pistols</h1>
  <div class="thumbnails digitcart-additional-carousel-wrapper">
    <a class="thumbnail" href="https://shop.joesalter.com/image/cache/catalog/a-1280x720.jpg">
      <img src="https://shop.joesalter.com/image/cache/catalog/a-400x400.jpg"></a>
    <img src="https://shop.joesalter.com/image/cache/catalog/a-74x74.jpg">
  </div>
  <div id="tab-description">The full description, not the truncated one.</div>
  <h3>You may also like</h3>
  <div class="product-layout"><div class="product-thumb">
    <img src="https://shop.joesalter.com/image/cache/catalog/related-1280x720.jpg">
  </div></div>
</body></html>"""


#: Their real robots.txt, which is all of it.
ROBOTS = "User-agent: *\nDisallow: /files\nDisallow: /image\n"


def _obeying(config, *exceptions):
    """A config that honors robots.txt. The suite's default does not, so a
    test about robots.txt has to say so."""
    return dataclasses.replace(
        config,
        scraping=dataclasses.replace(
            config.scraping, obey_robots=True, robots_exceptions=exceptions
        ),
    )


def _permitting(config):
    """...and carries the narrow exception for this host."""
    return _obeying(
        config,
        RobotsException(
            host="shop.joesalter.com",
            prefixes=("/image/",),
            reason="vendor agreed in writing",
        ),
    )


def _reading(context):
    """Serve the product page, and their real robots.txt for the rules."""
    context.robots.for_url = lambda _url: Robots.parse(ROBOTS)  # type: ignore[method-assign]
    context.get_text = lambda _url, **_k: DETAIL  # type: ignore[method-assign]
    return context


def _one(page=PAGE):
    found = parse_catalog(page, "Curio & Relic")
    assert len(found) == 1
    return found[0]


class TestReadingATile:
    def test_the_stock_number_is_the_key(self):
        """The dealer's own number. It survives a re-title, and it is the one
        identifier the product URL does not carry."""
        assert _one().external_key == "53643"

    def test_the_price_is_on_the_tile(self):
        """Which is what makes a failed detail page survivable here."""
        assert _one().price == 495.0

    def test_the_stock_number_is_not_part_of_the_title(self):
        title = _one().title
        assert title.startswith("Very Fine Hopkins & Allen")
        assert "Item #" not in title

    def test_the_storefront_furniture_is_not_part_of_the_title_either(self):
        """ "... ( read more )" and "Add To Cart" are the theme talking."""
        title = _one().title
        assert "read more" not in title
        assert "Add To Cart" not in title

    def test_a_tile_with_no_stock_number_is_not_a_listing(self):
        """The theme puts banners and category tiles in the same grid."""
        assert parse_catalog(TILE.replace("Item #: 53643", ""), "x") == []


class TestThePhotographs:
    """Their robots.txt is four lines and two of them are ``Disallow: /image``
    and ``Disallow: /files``. Every product photograph OpenCart serves lives
    under ``/image/cache/catalog/``, so the gallery is out of bounds unless a
    deployment has configured an exception for that host.

    The scraper does not decide this. It asks ``ctx.allowed()`` and believes
    the answer, so the default is no pictures and one config file is the only
    thing that changes it.
    """

    def test_the_catalog_tile_carries_none(self):
        """There is no photograph on a tile worth having anyway -- the gallery
        is on the product page."""
        assert _one().image_urls == []

    def test_by_default_the_gallery_is_not_read(self, ctx_factory, app_config):
        context = _reading(ctx_factory(config=_obeying(app_config)))
        item = JoeSalterScraper().with_detail(context, _one())
        assert item.image_urls == []

    def test_an_exception_lets_it_through(self, ctx_factory, app_config):
        """The configured, narrow override -- host plus path prefix plus a
        stated reason. See RobotsException in app/config.py."""
        context = _reading(ctx_factory(config=_permitting(app_config)))
        item = JoeSalterScraper().with_detail(context, _one())
        assert item.image_urls == ["https://shop.joesalter.com/image/cache/catalog/a-1280x720.jpg"]

    def test_only_this_listings_own_photographs(self, ctx_factory, app_config):
        """The "you may also like" strip is built from the same product tiles
        as a catalog page. Unscoped, one listing came back claiming 53
        photographs, two thirds of them other guns'."""
        context = _reading(ctx_factory(config=_permitting(app_config)))
        item = JoeSalterScraper().with_detail(context, _one())
        assert not any("related" in url for url in item.image_urls)

    def test_the_largest_rendering_of_each_wins(self, ctx_factory, app_config):
        """OpenCart writes every photograph several times over -- "-74x74",
        "-400x400", "-1280x720" -- and they are one picture, not three."""
        context = _reading(ctx_factory(config=_permitting(app_config)))
        item = JoeSalterScraper().with_detail(context, _one())
        assert len(item.image_urls) == 1
        assert "1280x720" in item.image_urls[0]

    def test_images_are_complete_either_way(self, ctx_factory, app_config):
        """Complete without them because there is nothing further this scan is
        permitted to fetch. Left incomplete, the photo backfill would retry a
        listing forever against a path robots.txt refuses."""
        context = _reading(ctx_factory(config=_obeying(app_config)))
        assert JoeSalterScraper().with_detail(context, _one()).images_are_complete is True


class TestTheStatedTotalIsNotAStoppingCondition:
    """The bug this was written for: the shop says 116, its pages carry 102,
    and pagination that trusts the total stops a page early.
    """

    def test_a_page_is_read_for_what_it_has_and_not_what_is_claimed(self):
        """The header says fifteen; the page has one."""
        assert len(parse_catalog(PAGE, "x")) == 1

    def test_the_walk_ends_on_an_empty_page_not_on_the_total(self, ctx_factory):
        served: list[str] = []

        def pages(url: str, **_kwargs) -> str:
            served.append(url)
            # Two pages of real listings, then nothing -- while the header goes
            # on claiming 116. A walk that believed the total would still be
            # fetching; one that multiplied a page number by PAGE_SIZE would
            # have stopped after the first.
            return PAGE if len(served) <= 2 else "<html><body>nothing</body></html>"

        context = ctx_factory()
        context.get_text = pages  # type: ignore[method-assign]
        scraper = JoeSalterScraper()
        found = list(scraper._walk(context, {"category": "x", "url": "https://s.test/c"}))

        assert len(found) == 2
        assert len(served) == 3

    def test_the_shortfall_is_reported_rather_than_chased(self, ctx_factory):
        """102 of a claimed 116 is the vendor's arithmetic, not a parse
        failure -- so it is logged, and does not make the site PARTIAL."""
        said: list[str] = []
        context = ctx_factory(progress=said.append)
        context.get_text = lambda url, **_k: (  # type: ignore[method-assign]
            PAGE if "page=" not in url else "<html></html>"
        )
        scraper = JoeSalterScraper()
        list(scraper._walk(context, {"category": "Curio & Relic", "url": "https://s.test/c"}))

        assert any("116" in line for line in said)
        assert context.warnings == []


class TestAskingForMoreAtOnce:
    def test_the_first_request_carries_the_limit(self, ctx_factory):
        """Fifteen at a time turns one 116-listing section into eight fetches
        for no gain to anybody."""
        served: list[str] = []
        context = ctx_factory()
        context.get_text = lambda url, **_k: (  # type: ignore[method-assign]
            served.append(url) or "<html></html>"
        )
        scraper = JoeSalterScraper()
        list(scraper._walk(context, {"category": "x", "url": "https://s.test/c"}))

        assert served == [f"https://s.test/c?limit={PAGE_SIZE}"]


class TestTheSameGunInTwoSections:
    def test_it_is_one_gun(self, ctx_factory):
        """A C&R revolver is also an antique handgun, and both sections list
        it. The stock number is the key, so keeping both would upsert one over
        the other."""
        context = ctx_factory(needs_detail=lambda _key: False)
        context.get_text = lambda url, **_k: (  # type: ignore[method-assign]
            PAGE if "page=" not in url else "<html></html>"
        )
        found = list(JoeSalterScraper().scrape(context))
        assert len(found) == 1


class TestItIsRegistered:
    def test_by_slug(self):
        assert isinstance(get_scraper("joe-salter"), JoeSalterScraper)

    def test_it_needs_no_browser(self):
        assert JoeSalterScraper.requires_browser is False


class TestTheProductAddress:
    def test_the_catalogs_own_parameters_are_not_part_of_it(self):
        """OpenCart's theme pastes the catalog page's query string onto every
        product link, so reading a section with ``?limit=100`` otherwise
        stores a hundred URLs ending in it -- making a listing's address
        depend on how the page it was found on happened to be fetched.
        """
        tile = TILE.replace(
            'href="https://shop.joesalter.com/Very-Fine-Hopkins-Allen"',
            'href="https://shop.joesalter.com/Very-Fine-Hopkins-Allen?limit=100"',
        )
        assert (
            parse_catalog(tile, "x")[0].url == "https://shop.joesalter.com/Very-Fine-Hopkins-Allen"
        )


class TestWhichSectionsAreRead:
    """The bug, and it was a scoping mistake rather than a parsing one.

    Their sections are cut on two different axes and only one is safe. A
    section named for a *form* -- "Military Longarms", "Antique Handguns" --
    holds guns. A section named for a *country* or a *maker* holds everything
    that country or maker ever touched: "British Military" was read here first
    and it was **71% not-a-gun** -- uniforms, cap badges, binoculars, riding
    spurs, bullet molds, books, boxes of blanks -- against 3-12% for the
    form-cut sections. Its own URL says "...holsters-militaria-Enfield", which
    should have been read as a warning rather than a list of contents.
    """

    def test_no_country_cut_section_is_read(self):
        for source in SOURCES:
            assert "militaria" not in source["url"].lower()

    def test_the_form_cut_military_sections_replaced_it(self):
        assert {s["category"] for s in SOURCES} == {
            "Curio & Relic",
            "Antique Handgun",
            "Antique Long Gun",
            "Military Long Gun",
            "Military Handgun",
        }


class TestTheBooksAmongTheGuns:
    """What is left once the sections are right. Joe Salter cross-lists the
    reference works into the gun sections they are about, so "The Blunderbuss
    History & Development" sits in Antique Long Guns.

    Two signals, because either alone is wrong. Every gun he lists opens its
    description with a spec preamble -- "Serial #8013, .32 S&W, 3 inch barrel"
    or "NSN, .54 Caliber" -- and no book does; but a bronze mortar at $4,195
    and a Winchester at $1,195 have no preamble either. Measured over 217
    listings: five books at $12.95-$29.95, cheapest gun with a preamble $195.
    """

    def _tile(self, title, price):
        return TILE.replace(
            "Very Fine Hopkins &amp; Allen Top Break Revolver 32 S&amp;W", title
        ).replace("$495.00", price)

    def test_a_cheap_book_is_dropped(self):
        page = self._tile("The Blunderbuss History &amp; Development", "$18.95")
        assert parse_catalog(page.replace("Serial #8013, ", ""), "x") == []

    def test_a_cheap_gun_is_kept_because_of_its_serial_number(self):
        """The preamble is what tells them apart, not the price alone."""
        page = self._tile("Some Very Cheap Revolver", "$18.95")
        assert len(parse_catalog(page, "x")) == 1

    def test_a_dear_item_with_no_preamble_is_kept(self):
        """A bronze mortar at $4,195 and a Winchester at $1,195 carry no
        serial number and are not books. The preamble alone would drop both."""
        page = self._tile("Excellent Modern Cast Bronze Replica Coehorn Mortar", "$4,195.00")
        assert len(parse_catalog(page.replace("Serial #8013, ", ""), "x")) == 1

    def test_a_listing_with_no_price_is_kept(self):
        """Call-for-price is not evidence of anything."""
        page = self._tile("Something Without A Price", "POR")
        assert len(parse_catalog(page.replace("Serial #8013, ", ""), "x")) == 1

    def test_a_dearer_book_is_dropped_for_saying_it_is_one(self):
        """Two at $99.95 sit above the price line and still are not guns.
        "Carvings from the Veldt Book ... Hard Cover ... 345 pages"."""
        page = self._tile("Carvings from the Veldt Book Hard Cover 345 pages", "$99.95")
        assert parse_catalog(page.replace("Serial #8013, ", ""), "x") == []

    def test_a_rifle_published_in_a_book_is_still_a_rifle(self):
        """Seven of them, and this is why the paper words are only half of a
        decision: "Published Boer War ZAR Model 1895 Mauser Rifle"."""
        page = self._tile("Published Boer War ZAR Model 1895 Mauser Rifle", "$4,995.00")
        assert len(parse_catalog(page, "x")) == 1
