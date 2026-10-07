"""The ten vendors added on 2026-10-06, one rule each that a recording cannot
pin: the shape tests in test_recorded_scrapers.py prove each one parses, and
these prove each one parses *right* where the shop does something odd.
"""

from __future__ import annotations

import pytest

from app.scrapers import b4_antiques, cherrys, david_condon, horse_soldier, lugerman, oldguns
from app.scrapers.merz_antiques import without_filing
from app.scrapers.pre98 import without_date
from app.scrapers.woo_store_api import price_now


def product(name, price="95000", **extra):
    """One Store API product, as much of it as the scrapers read."""
    return {
        "id": 7,
        "name": name,
        "permalink": "https://shop.test/p/7",
        "prices": {"price": price, "currency_minor_unit": 2},
        "is_in_stock": True,
        "categories": [],
        "images": [],
        **extra,
    }


class TestTheStoreApiShops:
    def test_a_zero_price_is_no_price(self):
        """1898andB-4 answer "0" for everything pending; a free gun is not a deal."""
        assert price_now(product("x", price="0")) is None
        assert price_now(product("x", price="82995")) == 829.95

    @pytest.mark.parametrize(
        ("title", "expected", "sold"),
        [
            ("TUE OCT 6, US WWII SMITH CORONA 1903A3", "US WWII SMITH CORONA 1903A3", False),
            ("SOLD THU OCT 1, WALTHER ac 42 CODE P.38", "WALTHER ac 42 CODE P.38", True),
            ("MON SEPT 28, ASTRA 600 PISTOL", "ASTRA 600 PISTOL", False),
            ("1903 COLT POCKET HAMMERLESS", "1903 COLT POCKET HAMMERLESS", False),
        ],
    )
    def test_pre98_takes_the_listing_date_off(self, title, expected, sold):
        assert without_date(title) == (expected, sold)

    def test_1898_and_b4_reads_pending_sale_as_gone(self):
        scraper = b4_antiques.B4AntiquesScraper()
        item = scraper.item_from_product(
            product("Jenks Carbine Made By N.P. Ames Co. \u2013 PENDING SALE", price="0"),
            "Military",
        )
        assert (item.title, item.is_sold, item.price) == (
            "Jenks Carbine Made By N.P. Ames Co.",
            True,
            None,
        )

    def test_lugerman_leaves_raffles_out(self):
        scraper = lugerman.LugerManScraper()
        assert scraper.item_from_product(product("1908 DWM Luger Raffle"), "Firearms") is None
        assert (
            scraper.item_from_product(
                product("Luger", categories=[{"name": "Raffles"}]), "Curio and Relics"
            )
            is None
        )
        assert scraper.item_from_product(product("1936 Krieghoff Luger"), "Curio and Relics")


class TestMerz:
    @pytest.mark.parametrize(
        ("title", "expected", "pending"),
        [
            (
                "C037 COLT 1849 POCKET MODEL WELLS FARGO MODEL  [A]",
                "COLT 1849 POCKET MODEL WELLS FARGO MODEL",
                False,
            ),
            (
                "6-134 CASED ENGRAVED PAIR OF REMINGTON VEST POCKET PISTOLS [A]",
                "CASED ENGRAVED PAIR OF REMINGTON VEST POCKET PISTOLS",
                False,
            ),
            (
                "*Sale Pending* MR1730 SHARPS 1874 MID-RANGE RIFLE [A]",
                "SHARPS 1874 MID-RANGE RIFLE",
                True,
            ),
            # A designation after the code is the gun, not the code.
            ("JM12 M1903 SPRINGFIELD RIFLE [M]", "M1903 SPRINGFIELD RIFLE", False),
        ],
    )
    def test_the_filing_comes_off_the_title(self, title, expected, pending):
        assert without_filing(title) == (expected, pending)


CONDON_PAGE = """
<div class="product-list">
  <a href="/inventory/Foreign Military Longarms/ww2-gustloff-k98k-29526">
    <img src="/img/upload/midsize/29526a.jpg" />
    <span class="product-name">WW2 GERMAN GUSTLOFF K98K 337/1940. </span>
    <span class="product-price">$1,250.00</span>
  </a>
  <a href="/inventory/Foreign Military Longarms/sold-ww2-sauer-k98k-30609">
    <img src="/img/upload/midsize/30609a.jpg" />
    <span class="product-name">SOLD- WW2 MAUSER K98K J.P. SAUER CODE.</span>
    <span class="product-price">$0.00</span>
  </a>
</div>
"""


class TestDavidCondon:
    def test_a_card_and_its_stock_number(self):
        first, sold = david_condon.parse_page(
            CONDON_PAGE, "https://www.davidcondon.com/inventory/foreign-military-longarms", "F"
        )
        assert (first.external_key, first.title, first.price, first.is_sold) == (
            "29526",
            "WW2 GERMAN GUSTLOFF K98K 337/1940",
            1250.0,
            False,
        )
        assert " " not in first.url
        assert first.image_urls == ["https://www.davidcondon.com/img/upload/fullsize/29526a.jpg"]
        # Named SOLD and priced at $0.00: both say sold, and neither is a price.
        assert (sold.title, sold.price, sold.is_sold) == (
            "WW2 MAUSER K98K J.P. SAUER CODE",
            None,
            True,
        )

    def test_the_product_page_can_say_sold_too(self):
        item = david_condon.parse_page(
            CONDON_PAGE, "https://www.davidcondon.com/inventory/foreign-military-longarms", "F"
        )[0]
        david_condon.read_detail(
            item,
            """<div id="internal-content"><h1>K98K</h1>
            <a onClick="SetActiveImage ('29526a.jpg')"></a><a onClick="SetActiveImage ('29526b.jpg')"></a>
            <h2>$1,250.00</h2><p>29526- All original and matching. Reasonably priced.(SOLD)</p></div>""",
        )
        assert item.is_sold
        assert len(item.image_urls) == 2 and item.images_are_complete


OLDGUNS_PAGE = """
<a NAME=SMOF8071></a> <B><FONT COLOR="#0000FF">**NEW ADDITION** </FONT></B>
 <b>SMOF8071 - </b> <b>LEE ENFIELD NO 1 MK III* CALIBER .303 BRITISH</b>
The British Army adopted a magazine rifle in 1888. $1350.00 <a href="pix/smof8071.jpg" >(View Picture)</a><br/>
<a NAME=SMOF8084></a> <B>**SOLD**</B>
 <b>SMOF8084 - </b> <b>IZHEVSK MODEL 91/30 MOSIN NAGANT</b>
A wartime rifle, $40 cheaper than last year. $450.00 <a href="pix/smof8084.jpg" >(View Picture)</a>
"""


class TestOldGuns:
    def test_each_anchor_is_a_listing(self):
        new, sold = oldguns.parse_page(OLDGUNS_PAGE, "https://www.oldguns.net/cat.php", "F")
        assert (new.external_key, new.title, new.price, new.is_sold) == (
            "SMOF8071",
            "LEE ENFIELD NO 1 MK III* CALIBER .303 BRITISH",
            1350.0,
            False,
        )
        assert new.url == "https://www.oldguns.net/cat.php#SMOF8071"
        assert new.image_urls == ["https://www.oldguns.net/pix/smof8071.jpg"]
        # The last dollar figure is the price, not one in the write-up.
        assert (sold.price, sold.is_sold) == (450.0, True)
        assert "$450" not in sold.description


HORSE_PAGE = """
<div class="product clearfix"><div class="feature-img"><a href="/products/firearms/longarms/55145"><img src="/images/product/55/252513_tn.jpg"/></a></div>
<h4><a href="/products/firearms/longarms/55145">TRENTON MODEL 1861</a></h4><p>A scarce contract musket.</p></div>
<div class="details"><p><a href="/products/firearms/longarms/55145">$2,750.00</a></p></div>
<div class="product clearfix"><div class="feature-img"><a href="/products/firearms/longarms/55132"><img src="/images/product/55/252437_tn.jpg"/></a></div>
<h4><a href="/products/firearms/longarms/55132">TOWER ENFIELD RIFLE-MUSKET</a></h4><p>Attic condition.</p></div>
<div class="details"><p><a class="on_hold" href="/products/firearms/longarms/55132">$3,895.00</a><br /><span class="sold">ON HOLD</span></p></div>
"""


class TestHorseSoldier:
    def test_on_hold_is_not_for_sale(self):
        open_, held = horse_soldier.parse_page(
            HORSE_PAGE, "https://www.horsesoldier.com/products/firearms/longarms/?show=all", "L"
        )
        assert (open_.external_key, open_.price, open_.is_sold) == ("55145", 2750.0, False)
        assert open_.image_urls == ["https://www.horsesoldier.com/images/product/55/252513.jpg"]
        assert (held.price, held.is_sold) == (3895.0, True)


class TestCherrys:
    @pytest.mark.parametrize(
        ("description", "title"),
        [
            (
                "Ball & Williams Ballard Rifle, .44 Rimfire Single Shot",
                "Ball & Williams Ballard Rifle",
            ),
            # A first clause too short to say what the gun is takes the next.
            ("S&W, Model 10 Revolver, 38 Special", "S&W, Model 10 Revolver"),
        ],
    )
    def test_the_title_is_the_first_clause(self, description, title):
        assert cherrys.title_of(description) == title

    def test_the_header_row_is_not_a_gun(self):
        page = """<table>
          <tr><td>STOCK#</td><td>DESCRIPTION</td><td>PRICE</td><td>PICTURES</td></tr>
          <tr><td>99116</td><td>Belgian 16 Gauge Percussion Shotgun, Antique</td><td>$195.00</td>
              <td><a href="stokpics2/99116.jpg">1</a></td></tr></table>"""
        [item] = cherrys.parse_page(page, "http://www.cherrys.com/longguns.htm", "Long Guns")
        assert (item.external_key, item.price) == ("99116", 195.0)
        assert item.image_urls == ["http://www.cherrys.com/stokpics2/99116.jpg"]
