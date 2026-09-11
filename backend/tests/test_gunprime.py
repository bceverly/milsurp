"""GunPrime: a Spree storefront where the vendor's taxonomy does the filtering.

Two things shaped this scraper, and both are decisions rather than parsing.

**The scope is the two tags, not the six categories.** ``/categories/firearms/*``
is ~1,300 Del-Ton AR pistols, Kahr P9s and suppressors -- a modern gun shop,
and reading it would repeat the mistake Arms Unlimited and Century Arms were
backed out for. ``/tags/collectible`` and ``/tags/police-trade-in`` are ~100
listings and are what this catalog is for.

**The police tag is 35% not-a-firearm** -- ammunition, magazines, duty
holsters, a weapon light -- and the vendor already says which is which. Every
product page carries its own taxons, so nothing here has to be guessed from a
title, which is how bayonets ended up in Rifles elsewhere.
"""

from __future__ import annotations

import dataclasses

from app.config import RobotsException
from app.robots import Robots
from app.scrapers import get_scraper
from app.scrapers.gunprime import (
    SOURCES,
    GunPrimeScraper,
    is_a_firearm,
    maker_of,
    parse_catalog,
    taxons,
)

#: Two tiles as Spree writes them: one in stock, one not.
PAGE = """<html><body>
<div class='col-md-3 product-list-item' data-hook='products_list_item' id='product_91350'>
  <div class='panel-body text-center product-body'>
    <a href="/products/used-glock-22-gen-3-40-s-w-police-trade"><div class='product-image-container'>
    <img alt='Used Glock 22' class='lazy' data-src='https://gunprime.com/rails/active_storage/x.jpg'>
    </div>
    <span class="info" title="Used Glock 22 Gen 3 40 S&amp;W One Mag G22 Police Trade Night Sights">
      Used Glock 22 Gen 3 40 S&amp;W One Mag...</span>
  </a></div>
  <div class='panel-footer text-center'><span>
    <span class='price selling lead' content='349.0'>
      <span class='product-price price-toggle black'>$349.00</span>
      <span class='product-cart-link'><a class="green" href="/orders/populate">Add</a></span>
  </span></span></div>
</div>
<div class='col-md-3 product-list-item' data-hook='products_list_item' id='product_501411'>
  <div class='panel-body text-center product-body'>
    <a href="/products/panzer-han9-9mm-brace"><span class="info" title="Panzer Han9 9mm Brace">
      Panzer Han9</span></a></div>
  <div class='panel-footer text-center'>
    <span class='price selling lead' content='499.0'>
      <span class='product-price price-toggle gray'>$499.00</span>
      <span class='product-cart-link red'><i class="fa fa-frown-o"></i> Out of Stock </span>
  </span></div>
</div>
</body></html>"""

#: A product page's own taxon block, which is not the six category links the
#: site navigation puts on every page.
DETAIL = """<html><body>
<div id="nav"><a href="/categories/firearms/pistols">Pistols</a>
              <a href="/categories/firearms/rifles">Rifles</a></div>
<meta itemprop="description" content="&lt;p&gt;A Gen 3 Glock 22 with &amp;quot;night&amp;quot; sights.&lt;/p&gt;" />
<img data-src='https://gunprime.s3.us-east-2.amazonaws.com/variants/aaa/one.jpg?X-Amz-Signature=1'>
<img data-src='https://gunprime.com/rails/active_storage/blobs/bbb/one.jpg'>
<div id="taxon-crumbs" class=" five " data-hook="product_taxons">
  <div class="list-group" id="similar_items_by_taxon" data-hook>
    <span class="product-section-title">Categories:</span>
    <a class="gp-taxon-link" href="/t/manufacturer/glock">Glock</a>,
    <a class="gp-taxon-link" href="/t/manufacturer/glock/22">22</a>,
    <a class="gp-taxon-link" href="/t/categories/firearms/pistols/semi-auto-pistols">Semi-Auto</a>
  </div>
</div>
</body></html>"""

#: Their robots.txt, in full apart from the crawl-delay-free preamble.
ROBOTS = "User-agent: *\nDisallow: /checkout\nDisallow: /api\nDisallow: /rails/active_storage/*\n"


def _obeying(config, *exceptions):
    """The suite runs with obey_robots off, so a test about it must say so."""
    return dataclasses.replace(
        config,
        scraping=dataclasses.replace(
            config.scraping, obey_robots=True, robots_exceptions=exceptions
        ),
    )


def _permitting(config):
    return _obeying(
        config,
        RobotsException(
            host="gunprime.com",
            prefixes=("/rails/active_storage/",),
            reason="vendor agreed in writing",
        ),
    )


AMMO_TAXONS = [
    "categories/ammunition",
    "manufacturer/remington",
    "manufacturer/remington/golden-saber",
]
HOLSTER_TAXONS = ["categories/accessories/firearm", "manufacturer/blackhawk"]


def _by_key(page=PAGE):
    return {item.external_key: item for item in parse_catalog(page, "Police Trade-In")}


class TestReadingATile:
    def test_spree_gives_every_product_a_number(self):
        """``id='product_91350'``: stable across a re-title, and the one
        identifier the URL slug does not carry."""
        assert set(_by_key()) == {"91350", "501411"}

    def test_the_price_is_machine_readable(self):
        """``content='349.0'`` rather than parsing "$349.00"."""
        assert _by_key()["91350"].price == 349.0

    def test_the_title_is_the_untruncated_one(self):
        """The visible text ends in an ellipsis; the ``title`` attribute does
        not."""
        title = _by_key()["91350"].title
        assert title.endswith("Police Trade Night Sights")
        assert "&amp;" not in title and "S&W" in title

    def test_stock_is_on_the_tile(self):
        """So availability costs no product-page fetch."""
        assert _by_key()["91350"].is_sold is False
        assert _by_key()["501411"].is_sold is True

    def test_the_url_is_absolute(self):
        assert _by_key()["91350"].url.startswith("https://gunprime.com/products/")


class TestTheVendorSaysWhatEachThingIs:
    """The police tag mixes guns with ammunition, magazines and holsters, and
    every product page states its own taxons. Nothing is guessed from a title.
    """

    def test_only_this_products_taxons_are_read(self):
        """Every page carries the six category links in its navigation; the
        product's own are in the block Spree hooks as ``product_taxons``."""
        assert taxons(DETAIL) == [
            "manufacturer/glock",
            "manufacturer/glock/22",
            "categories/firearms/pistols/semi-auto-pistols",
        ]

    def test_a_pistol_is_a_firearm(self):
        assert is_a_firearm(taxons(DETAIL)) is True

    def test_ammunition_is_not(self):
        assert is_a_firearm(AMMO_TAXONS) is False

    def test_nor_is_a_holster(self):
        """ "categories/accessories/firearm" contains the word and is a duty
        holster. The test is on the start of the path, not a substring."""
        assert is_a_firearm(HOLSTER_TAXONS) is False

    def test_the_maker_comes_free_with_it(self):
        """A product carries both "manufacturer/glock" and
        "manufacturer/glock/22"; the shallower one is the maker."""
        assert maker_of(taxons(DETAIL)) == "Glock"

    def test_a_product_with_no_taxons_yields_no_maker(self):
        assert maker_of([]) is None


class TestTheProductPage:
    def test_the_description_is_unescaped_twice(self, ctx_factory):
        """Spree keeps it as escaped HTML inside a meta attribute -- the
        rendered copy is behind a JavaScript tab and never reaches us."""
        context = ctx_factory()
        context.get_text = lambda _url, **_k: DETAIL  # type: ignore[method-assign]
        item = GunPrimeScraper().with_detail(context, _by_key()["91350"])
        assert item is not None
        assert item.description == 'A Gen 3 Glock 22 with "night" sights.'

    def test_a_listing_the_vendor_does_not_call_a_firearm_is_dropped(self, ctx_factory):
        page = DETAIL.replace(
            "/t/categories/firearms/pistols/semi-auto-pistols", "/t/categories/ammunition"
        )
        context = ctx_factory()
        context.get_text = lambda _url, **_k: page  # type: ignore[method-assign]
        assert GunPrimeScraper().with_detail(context, _by_key()["91350"]) is None

    def test_a_page_that_cannot_be_read_keeps_the_listing(self, ctx_factory):
        """Failing to fetch is not evidence that something is ammunition, and
        the tile is already a whole record apart from its prose."""
        from app.scrapers.base import ScrapeError

        def refuse(_url, **_kwargs):
            raise ScrapeError("503")

        context = ctx_factory()
        context.get_text = refuse  # type: ignore[method-assign]
        assert GunPrimeScraper().with_detail(context, _by_key()["91350"]) is not None


class TestThePhotographs:
    """Their robots.txt disallows ``/rails/active_storage/*``, where every
    product image lives, so this vendor ships without pictures until a
    deployment configures an exception.

    The page also carries a presigned S3 URL for each photo, on a host with no
    robots.txt of its own. Fetching those to sidestep the rule on the vendor's
    own domain would be circumventing it, so the S3 form is not read.
    """

    def _item(self, ctx_factory, config=None):
        context = ctx_factory(config=config)
        context.robots.for_url = lambda _u: Robots.parse(ROBOTS)  # type: ignore[method-assign]
        context.get_text = lambda _url, **_k: DETAIL  # type: ignore[method-assign]
        return GunPrimeScraper().with_detail(context, _by_key()["91350"])

    def test_by_default_there_are_none(self, ctx_factory, app_config):
        item = self._item(ctx_factory, _obeying(app_config))
        assert item is not None
        assert item.image_urls == []

    def test_an_exception_lets_the_gallery_through(self, ctx_factory, app_config):
        item = self._item(ctx_factory, _permitting(app_config))
        assert item is not None
        assert item.image_urls == ["https://gunprime.com/rails/active_storage/blobs/bbb/one.jpg"]

    def test_the_s3_url_is_never_used(self, ctx_factory, app_config):
        """It is the same picture on a host that states no rules, and taking
        it would be working around the rule the vendor did state."""
        item = self._item(ctx_factory, _permitting(app_config))
        assert item is not None
        assert not any("gunprime.s3" in url for url in item.image_urls)


class TestTheScope:
    def test_the_categories_are_not_read(self):
        """~1,300 listings of modern commercial stock. See the module
        docstring, and the Arms Unlimited entry in ROADMAP.md."""
        assert not any("/categories/" in source["url"] for source in SOURCES)

    def test_the_two_tags_are(self):
        assert {source["category"] for source in SOURCES} == {"Collectible", "Police Trade-In"}


class TestItIsRegistered:
    def test_by_slug(self):
        assert isinstance(get_scraper("gunprime"), GunPrimeScraper)

    def test_it_needs_no_browser(self):
        assert GunPrimeScraper.requires_browser is False
