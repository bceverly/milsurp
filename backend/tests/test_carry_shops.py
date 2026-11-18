"""The carry shops added on 2026-10-20: Coreware's search storefront, the
WooCommerce distributor catalogs, and James River Armory's rifles. (Its older
storefront went with DeLeon RX, removed on 2026-11-16.) Locked & Loaded left
Coreware on 2026-11-18 and is read from its price feed instead."""

from __future__ import annotations

import pytest

from app.scrapers.base import ScrapedItem
from app.scrapers.coreware_search import ScrapeError, search_settings
from app.scrapers.florida_guns import FloridaGunsScraper
from app.scrapers.g4g_guns import G4gGunsScraper
from app.scrapers.james_river_armory import parse_product, product_ids
from app.scrapers.locked_loaded import SITE_BASE, item_from_offer, offers
from app.scrapers.woo_carry import stated_caliber


class TestCorewareSearch:
    def test_the_page_publishes_the_search_settings(self):
        page = (
            '{"MEILISEARCH_URL":"https:\\/\\/search.coreware.com\\/",'
            '"MEILISEARCH_INDEX_NAME":"lockedloaded","MEILISEARCH_SEARCH_API_KEY":"abc123"}'
        )
        assert search_settings(page) == {
            "MEILISEARCH_URL": "https://search.coreware.com/",
            "MEILISEARCH_INDEX_NAME": "lockedloaded",
            "MEILISEARCH_SEARCH_API_KEY": "abc123",
        }
        with pytest.raises(ScrapeError):
            search_settings("<html></html>")

    def test_a_record_is_a_listing(self):
        item = FloridaGunsScraper().item_from_hit(
            {
                "id": 121370829,
                "title": "M&P BODYGUARD 2.0 380 ACP SEMI-AUTO HANDGUN",
                "description": "Introducing the Bodyguard 2.0.",
                "brandDescription": "Smith & Wesson",
                "upc": "022188897029",
                "facets": {"CALIBER": "380 ACP"},
                "image": "https://images.coreware.com/images/products/1.jpg",
                "categories": ["PISTOLS", "SEMI_AUTO"],
                "userTypePricing": {"DEFAULT": {"displayPrice": 449.99}},
                "inStockLocally": 1,
                "link_name": "mp-bodyguard-2.0-380-acp",
            }
        )
        assert item.url == "https://www.floridaguns.com/product/mp-bodyguard-2.0-380-acp"
        assert (item.price, item.caliber, item.manufacturer, item.is_new) == (
            449.99,
            "380 ACP",
            "Smith & Wesson",
            True,
        )
        used = FloridaGunsScraper().item_from_hit(
            {"id": 2, "title": "Glock 19", "categories": ["PISTOLS", "USED_FIREARMS"]}
        )
        assert (used.is_new, used.price) == (False, None)
        assert used.url == "https://www.floridaguns.com/product-details?id=2"


def feed(*bodies: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<offers>'
        + "".join(f"<offer>{body}</offer>" for body in bodies)
        + "</offers>"
    ).encode("utf-8")


def handgun(
    *,
    title="Glock 19 Gen5 9mm 15rd",
    path="glock-19-gen5-9mm-15rd",
    price="<price>549.99</price>",
    kind="handgun",
    caliber="9mm Luger",
    availability="In Stock",
):
    return (
        f"<title>{title}</title>"
        f"<url>https://www.lockedloaded.com/{path}?utm_source=gundeals&amp;utm_medium=pricefeed</url>"
        f"{price}<upc>764503037382</upc><mpn>PA195S203</mpn>"
        "<image>https://images.2adata.com/product_images/catalog/1/g19.jpg</image>"
        "<brand>Glock</brand>"
        f"<firearm><model>19</model><type>{kind}</type><action>Safe Action</action>"
        f"<caliber>{caliber}</caliber></firearm>"
        f"<availability>{availability}</availability><shippingInfo>$24.99 Shipping</shippingInfo>"
    )


class TestLockedLoadedFeed:
    """The price feed the shop publishes for gun.deals, read since 2026-11-18."""

    def test_an_offer_is_a_listing(self):
        (offer,) = offers(feed(handgun()))
        item = item_from_offer(offer)
        assert item.external_key == "ll-glock-19-gen5-9mm-15rd"
        # The feed's tracking parameters are left off.
        assert item.url == f"{SITE_BASE}glock-19-gen5-9mm-15rd"
        assert (item.price, item.caliber, item.manufacturer, item.stated_kind) == (
            549.99,
            "9mm Luger",
            "Glock",
            "handgun",
        )
        assert item.image_urls == ["https://images.2adata.com/product_images/catalog/1/g19.jpg"]
        assert item.extra["upc"] == "764503037382"
        assert item.extra["shipping"] == "$24.99 Shipping"

    def test_a_hidden_price_is_still_the_price(self):
        (offer,) = offers(feed(handgun(price='<price hide="MAP">1,199.00</price>')))
        assert item_from_offer(offer).price == 1199.0

    @pytest.mark.parametrize(
        "body",
        [
            handgun(kind="rifle"),
            handgun(caliber="454 Casull"),
            handgun(availability="Out of Stock"),
            handgun(title=""),
            (
                "<title>CCI Blazer Brass 9mm 1000ct</title><url>https://www.lockedloaded.com/cci</url>"
                "<price>239.99</price><ammunition><caliber>9mm Luger</caliber></ammunition>"
                "<availability>In Stock</availability>"
            ),
        ],
        ids=["rifle", "not-a-carry-caliber", "out-of-stock", "no-title", "ammunition"],
    )
    def test_what_is_not_read(self, body):
        (offer,) = offers(feed(body))
        assert item_from_offer(offer) is None

    def test_a_revolver_counts(self):
        (offer,) = offers(feed(handgun(kind="revolver", caliber="357 Magnum | 38 Special")))
        assert item_from_offer(offer).stated_kind == "revolver"

    def test_a_link_to_another_site_is_not_one_of_the_shops(self):
        body = handgun().replace("https://www.lockedloaded.com/", "https://elsewhere.test/")
        (offer,) = offers(feed(body))
        assert item_from_offer(offer) is None

    def test_a_page_that_is_not_the_feed_says_so(self):
        with pytest.raises(ScrapeError):
            offers(b"<html><body>Maintenance</body></html>")
        with pytest.raises(ScrapeError):
            offers(b"not xml at all")

    def test_an_entity_in_the_feed_is_never_resolved(self, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("do-not-read")
        document = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<!DOCTYPE offers [<!ENTITY x SYSTEM "file://{secret}">]>'
            f"<offers><offer>{handgun(title='Glock &x;')}</offer></offers>"
        ).encode()
        (offer,) = offers(document)
        item = item_from_offer(offer)
        assert "do-not-read" not in (item.title if item else "")


def test_a_cut_short_title_keeps_the_whole_one(clean_db):
    from app.models import Site
    from app.services import scan_service

    site = Site(slug="carry-shop", name="Carry Shop", base_url="https://d.test/")
    clean_db.add(site)
    clean_db.commit()

    def scan(title, truncated):
        scraped = ScrapedItem(external_key="k", url="https://b.test/k", title=title)
        scraped.title_truncated = truncated
        item, _, _ = scan_service._upsert_item(
            clean_db, site, scraped, run=None, seen_at=scan_service.utcnow()
        )
        clean_db.commit()
        return item.title

    whole = 'Korth Mongoose, .357 Magnum, 4" Barrel, 6rd Cylinder Revolver'
    assert scan(whole, False) == whole
    assert scan('Korth Mongoose, .357 Magnum, 4" Barrel, 6rd Cylind', True) == whole
    # A different title is the shop's change, and is taken.
    assert scan('Korth Mongoose, .357 Magnum, 6" Ba', True) == 'Korth Mongoose, .357 Magnum, 6" Ba'


class TestWooCarry:
    def test_the_stated_caliber(self):
        product = {"attributes": [{"name": "Caliber/Gauge", "terms": [{"name": "9mm"}]}]}
        assert stated_caliber(product) == "9mm"
        assert stated_caliber({"attributes": []}) is None

    def test_only_carry_calibers_and_a_demonstrator_is_used(self):
        scraper = G4gGunsScraper()

        def product(name, caliber=None):
            return {
                "id": 1,
                "permalink": "https://g4gguns.com/p/",
                "name": name,
                "prices": {"price": "50000", "currency_minor_unit": 2},
                "is_in_stock": True,
                "attributes": (
                    [{"name": "Caliber/Gauge", "terms": [{"name": caliber}]}] if caliber else []
                ),
            }

        new = scraper.item_from_product(product("Glock 19 Gen 5", "9mm"), "Semi-Auto Handguns")
        assert (new.caliber, new.is_new) == ("9mm", True)
        demo = scraper.item_from_product(product("DEMO Canik METE MC9 9mm Luger"), "x")
        assert demo.is_new is False
        assert scraper.item_from_product(product("KRISS Vector 5.56 NATO"), "x") is None


class TestJamesRiverArmory:
    def test_the_section_and_a_product(self):
        assert product_ids(
            '<a href="index.php?dispatch=products.view&amp;product_id=211">'
            '<a href="index.php?dispatch=products.view&amp;product_id=354">'
            '<a href="index.php?dispatch=products.view&amp;product_id=211">'
        ) == ["211", "354"]
        page = (
            "<h1>JRA M14 As-Issued</h1>"
            '<span id="sec_discounted_price_211">1,795.00</span>'
            '<span class="ty-qty-in-stock">In stock</span>'
            '<div id="content_description">Original unrefinished parts.</div>'
            '<a href="https://www.jamesriverarmory.com/images/detailed/9/DSC00730.JPG">'
            '<img src="https://www.jamesriverarmory.com/images/thumbnails/400/400/detailed/9/DSC00728.JPG">'
        )
        item = parse_product(page, "211", "https://jra.test/211")
        assert (item.title, item.price, item.is_sold, item.is_new) == (
            "JRA M14 As-Issued",
            1795.0,
            False,
            True,
        )
        assert item.image_urls == [
            "https://www.jamesriverarmory.com/images/detailed/9/DSC00730.JPG",
            "https://www.jamesriverarmory.com/images/detailed/9/DSC00728.JPG",
        ]
        gone = parse_product(page.replace("ty-qty-in-stock", "ty-qty-out-of-stock"), "211", "u")
        assert gone.is_sold
