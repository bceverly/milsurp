"""The shotgun widening of 2026-11-06.

Three shops added for their shotguns -- Double Shotguns, Griffin & Howe and
Vintage Doubles -- and the shotgun shelves of four already read (Simpson, in
test_simpson_ltd; Collectors Firearms, Old Steel Arsenal and Greentop here). The scans themselves are replayed from
their recordings (test_recorded_scrapers); these pin the rules each shop
needed of its own.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.scrapers import get_scraper
from app.scrapers.collectors_firearms import CollectorsFirearmsScraper, is_new_gun
from app.scrapers.double_shotguns import DoubleShotgunsScraper, without_serial
from app.scrapers.greentop import GreentopScraper
from app.scrapers.griffin_howe import GriffinHoweScraper, is_used_card
from app.scrapers.old_steel_arsenal import OldSteelArsenalScraper
from app.scrapers.vintage_doubles import SOURCES as VINTAGE_SOURCES
from app.scrapers.vintage_doubles import VintageDoublesScraper, parse_page


class TestTheyAreRegistered:
    def test_by_slug(self):
        for slug, cls in (
            ("double-shotguns", DoubleShotgunsScraper),
            ("griffin-howe", GriffinHoweScraper),
            ("vintage-doubles", VintageDoublesScraper),
        ):
            assert isinstance(get_scraper(slug), cls)


class TestTheShelvesAlreadyRead:
    def test_old_steel_arsenal_reads_its_shotguns(self):
        assert {"category": "Shotguns", "id": 39} in OldSteelArsenalScraper.sources

    def test_greentop_reads_both_used_shotgun_sections(self):
        names = {source["category"] for source in GreentopScraper.sources}
        assert {"Used Shotguns", "Used Tactical Shotguns"} <= names

    def test_collectors_firearms_reads_the_shotgun_leaves_but_not_the_nfa_one(self):
        urls = [source["url"] for source in CollectorsFirearmsScraper.sources]
        shotguns = [url for url in urls if "/product-category/shotguns/" in url]
        assert len(shotguns) == 11
        assert not any("short-barrel" in url or "accessories" in url for url in shotguns)
        assert len(urls) == len(set(urls))


class TestCollectorsFirearmsNewGuns:
    """The shotgun leaves mix new Benellis with used guns, and say which only
    by a trailing NEW after the stock number."""

    def test_the_trailing_word_marks_a_new_gun(self):
        assert is_new_gun("(SN: X125994Y) BENELLI SUPER BLACK EAGLE III 20 GAUGE (L2026-14685) NEW")
        assert not is_new_gun("FRANCHI AFFINITY 3 SHOTGUN 20 GAUGE (L2026-14035)")

    def test_new_elsewhere_in_a_title_is_not_it(self):
        assert not is_new_gun("NEW HAVEN ARMS MODEL 1860 (L2026-1)")
        assert not is_new_gun("REMINGTON NEW MODEL ARMY (L2026-2) NEWLY LISTED")

    def test_the_card_carries_it(self):
        card = BeautifulSoup(
            '<li class="product type-product post-123">'
            '<a class="woocommerce-loop-product__link" href="https://collectorsfirearms.com/product/x/">'
            '<h2 class="woocommerce-loop-product__title">'
            "BENELLI ETHOS 12 GAUGE (L2026-14195) NEW</h2></a>"
            '<span class="price"><span class="woocommerce-Price-amount">$2,099.00</span></span>'
            "</li>",
            "html.parser",
        ).li
        item = CollectorsFirearmsScraper().item_from_card(
            card, "https://collectorsfirearms.com/", "x"
        )
        assert item is not None and item.is_new is True


class TestDoubleShotgunsSerials:
    def test_the_serial_is_taken_out_and_the_sku_kept(self):
        text = "This CZ Mallard (SKU 17743, Serial 0754056) is a 20 gauge O/U."
        assert without_serial(text) == "This CZ Mallard (SKU 17743) is a 20 gauge O/U."

    def test_other_spellings(self):
        assert "1234" not in (without_serial("Serial #: A1234 and more") or "")
        assert without_serial(None) is None

    def test_the_listing_is_built_without_it(self):
        product = {
            "id": 1939,
            "permalink": "https://doubleshotguns.com/product/cz-mallard/",
            "name": "CZ Mallard &#8211; 20 Gauge",
            "prices": {"price": "59500", "currency_minor_unit": 2},
            "is_in_stock": True,
            "description": "<p>This CZ Mallard (SKU 17743, Serial 0754056) is a 20 gauge.</p>",
            "categories": [{"name": "Shotguns"}],
            "images": [],
        }
        item = DoubleShotgunsScraper().item_from_product(product, "Shotguns")
        assert item is not None
        assert "0754056" not in (item.description or "")
        assert item.price == 595.0


class TestGriffinHoweNewOrUsed:
    def test_a_used_card_is_filed_in_the_used_categories(self):
        assert is_used_card("product type-product product_cat-shotguns product_cat-used-guns")
        assert not is_used_card("product type-product product_cat-shotguns post-1")

    def test_the_card_says_which(self):
        def card(classes):
            return BeautifulSoup(
                f'<div class="e-loop-item product type-product post-558891 {classes}">'
                '<h2 class="woocommerce-loop-product__title">'
                '<a href="https://griffinhowe.com/shop/product/piotti/">PIOTTI SLE 20 GAUGE</a></h2>'
                '<span class="price"><span class="woocommerce-Price-amount amount">'
                "$25,000.00</span></span></div>",
                "html.parser",
            ).div

        scraper = GriffinHoweScraper()
        page = "https://griffinhowe.com/shop/category/gun-room/shotguns/"
        used = scraper.item_from_card(card("product_cat-used-shotguns"), page, "Shotguns")
        new = scraper.item_from_card(card("product_cat-shotguns"), page, "Shotguns")
        assert used is not None and used.is_new is False
        assert new is not None and new.is_new is True
        assert used.price == 25000.0


#: One gun as the catalog prints it, trimmed: the gun's row, then its
#: write-up, the zoom prompt and the spec line, then the next gun's spacer.
_VINTAGE_PAGE = """
<table class="inventory">
<tr class='spacerRow'><td colspan="3">&nbsp;</td></tr>
<tr id='gunRow_6212' class='defaultRow '>
 <td class="photoTD" rowspan="5"><div class='photoBox'>
  <a class='photoThumb' data-gunid="6212"><img data-original='/vd_images/thumbs/6212.jpg'
     src='/vd_images/assets/loading.gif' class='lazy gunThumb'></a></div>
  <span class='gunPrice'>$8900<br><br><a href="/contact?gunID=6212" class='buyNowLink'>CONTACT</a></span>
 </td>
 <td><span class="gunTitle">Westley Richards droplock in wonderful condition</span><br>
  <label>Category:</label> Boxlocks<br><label>Gauge:</label> 12 gauge</td>
 <td class="gunids"><label>GunID:</label> 6212<br><label>Serial:</label> 8172</td>
</tr>
<tr class='defaultRow '><td colspan="2">A super example of the famous Westley Drop lock.</td></tr>
<tr class='defaultRow '><td colspan="2">Click anywhere on the large image below to zoom in. | Full Screen</td></tr>
<tr class='defaultRow '><td colspan="2">Ejector: Yes Barrel Length: 30" Chamber Length: 2 3/4"</td></tr>
<tr class='spacerRow'><td colspan="3">&nbsp;</td></tr>
<tr id='gunRow_6407' class='defaultRow '>
 <td class="photoTD"><span class='gunPrice'>$28000</span></td>
 <td><span class="gunTitle">Jerry Fisher custom rifle in 7mm Dakota</span><br>
  <label>Category:</label> Drillings, Double Rifles, and Rifles<br><label>Gauge:</label> Caliber</td>
 <td class="gunids"><label>GunID:</label> 6407<br><label>Serial:</label> NVN</td>
</tr>
</table>
"""


class TestVintageDoublesCatalog:
    def _items(self):
        url = "https://www.vintagedoubles.com/catalog/?sort=4"
        return {item.external_key: item for item in parse_page(_VINTAGE_PAGE, url, "Boxlocks")}

    def test_each_row_is_a_listing_keyed_by_its_gun_id(self):
        items = self._items()
        assert set(items) == {"6212", "6407"}
        gun = items["6212"]
        assert gun.title == "Westley Richards droplock in wonderful condition"
        assert gun.price == 8900.0
        assert gun.url.endswith("#gunRow_6212")
        assert gun.image_urls == ["https://www.vintagedoubles.com/vd_images/thumbs/6212.jpg"]

    def test_the_gauge_is_read_and_a_rifle_gives_none(self):
        items = self._items()
        assert items["6212"].caliber == "12 gauge"
        assert items["6407"].caliber is None

    def test_the_write_up_keeps_the_specs_and_drops_the_viewer_and_serial(self):
        description = self._items()["6212"].description or ""
        assert "Westley Drop lock" in description
        assert "Barrel Length: 30" in description
        assert "Click anywhere" not in description
        assert "8172" not in description

    def test_a_wanted_notice_is_not_a_listing_and_zero_is_no_price(self):
        page = _VINTAGE_PAGE.replace(
            "Jerry Fisher custom rifle in 7mm Dakota", "WANTED! W.C. Scott action or gun"
        ).replace("$8900", "$0")
        items = {i.external_key: i for i in parse_page(page, "https://x/", "Boxlocks")}
        assert set(items) == {"6212"}
        assert items["6212"].price is None

    def test_the_left_handed_list_is_not_read(self):
        """It repeats guns from the other categories."""
        assert not any(source["url"].endswith("sort=31") for source in VINTAGE_SOURCES)
