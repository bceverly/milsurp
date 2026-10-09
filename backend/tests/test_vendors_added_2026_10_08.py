"""The two shops added on 2026-10-08 beside Moka's Raifus, and the one
classifier rule J & J's shelf turned up. The shape of a whole recorded scan is
checked in test_recorded_scrapers.py.
"""

from __future__ import annotations

import pytest

from app.scrapers.jj_military import JjMilitaryScraper
from app.services.classify import classify_firearm


def product(name, *categories, price="129500"):
    """One Store API product, as much of it as the scrapers read."""
    return {
        "id": 7,
        "name": name,
        "permalink": "https://jjmilitary.com/product/x/",
        "prices": {"price": price, "currency_minor_unit": 2},
        "is_in_stock": True,
        "categories": [{"name": c} for c in categories],
        "images": [],
    }


class TestJjMilitary:
    def read(self, name, *categories, price="129500"):
        return JjMilitaryScraper().item_from_product(
            product(name, *categories, price=price), "Antique Firearms"
        )

    def test_a_gun_is_read(self):
        item = self.read("US Navy Jenks Carbine", "Antique Firearms", "Longarm Carbines US")
        assert (item.title, item.price) == ("US Navy Jenks Carbine", 1295.0)

    @pytest.mark.parametrize(
        ("title", "filed"),
        [
            # A part names the gun it fits, which is enough for the classifier
            # to call an $18 screw a carbine. The shop's own filing says better.
            ("Spencer M-1865 Carbine & Rifle Hinge Pivot Screw", "Gun Parts"),
            ("Krag M-1897 Rifle & Carbine Tool", "Tools, Tompions, Cap Tins & Accessories"),
            # The case a revolver came in, without the revolver.
            (
                "Colt M-1851 Navy Revolver Factory Case",
                "Holsters, Slings, Belts, Buckles, Hangers, Boxes",
            ),
        ],
    )
    def test_parts_tools_and_cases_are_not(self, title, filed):
        assert self.read(title, "Antique Firearms", filed, price="1800") is None

    def test_a_price_on_request_is_no_price(self):
        item = self.read("Colt Baby Dragoon Percussion Revolver", "Antique Firearms", price="0")
        assert item.price is None


class TestACartridgeConversion:
    """A percussion revolver altered to take cartridges was filed as
    ammunition: "cartridge", as the last noun in the title, read as the thing
    being sold."""

    @pytest.mark.parametrize(
        "title",
        [
            "Whitney Navy Percussion Revolver Altered to Cartridge",
            "Colt 1860 Army Revolver Converted to Cartridge",
        ],
    )
    def test_is_the_revolver(self, title):
        assert classify_firearm(title, category="Antique Firearms") == (False, True)

    def test_while_cartridges_for_sale_are_still_not_a_gun(self):
        assert classify_firearm("Box of 50 .44 Colt Cartridges") == (False, False)


class TestGreentopSerials:
    """Greentop put each gun's serial number in its title, and the armory's
    discovery proposed every one as a model ("CHFR895", "CEZE544")."""

    @pytest.mark.parametrize(
        ("title", "clean"),
        [
            (
                'Used GLOCK 19V 9X19 CHFR895 4" MATTE G GTO392819',
                'Used GLOCK 19V 9X19 4" MATTE G GTO392819',
            ),
            (
                'Used SPRINGFIELD RANGE OFCR CPT LW138093 4" MATTE G GTO391915',
                'Used SPRINGFIELD RANGE OFCR CPT 4" MATTE G GTO391915',
            ),
            (
                'Used S&W 36 38SPL J353573 1.875" BLUED VG GTO392586',
                'Used S&W 36 38SPL 1.875" BLUED VG GTO392586',
            ),
            (
                'Used RUGER GP100 357MAG 179-90640 6" BLUED G GTO392276',
                'Used RUGER GP100 357MAG 6" BLUED G GTO392276',
            ),
        ],
    )
    def test_the_serial_comes_out(self, title, clean):
        from app.scrapers.greentop import without_serial

        assert without_serial(title) == clean


TOTW_CARD = """
<div class="card h-100"><div class="card-header fw-semibold"><div class="card-title">
<a class="fw-bold rounded text-bg-primary p-1" href="/parts/detail/2584/1/aax-135">AAX-135</a>
Contemporary Longrifle, .40 caliber 36" Green Mountain barrel, large Siler flintlock, used
</div></div><div class="card-body"><div class="card-img-top"><a href="/parts/detail/2584/1/aax-135">
<img src="https://cdn.trackofthewolf.com/imgPart/aax/aax-135_0.webp" /></a></div></div>
<div class="card-footer"><a href="/knowledgebase/2#14"><i class="inventory-status status-1"
title="Item has been shipped out for inspection, and at this time, is NOT available."></i></a>
<span class="fw-bold">$2,125.00</span></div></div>
"""


class TestTrackOfTheWolf:
    def test_a_card(self):
        from app.scrapers.track_of_the_wolf import parse_page

        [item] = parse_page(TOTW_CARD, "https://www.trackofthewolf.com/parts/list/2584/1", "F")
        assert item.external_key == "AAX-135"
        assert item.title.startswith("Contemporary Longrifle, .40 caliber")
        assert item.price == 2125.0
        # Out for inspection is not for sale.
        assert item.is_sold


COMERS_TILE = """
<div class="item"><a href="/products/armisport-5326"><div class="product">
<div class="product-badge out-of-stock-badge">Out of Stock</div>
<div class="image"><img src="https://cdn.example/x.jpg" /></div>
<div class="description"><strong>42 Springfield - Used, like new</strong>
<div class="grid-description"><span class="small">Armisport</span><br />
<span class="small text-muted">69</span></div></div><div class="price">$1,325.00</div>
</div></a></div>
<div class="item"><a href="/products/defarb-1"><div class="product">
<div class="description"><strong>Defarb - Lock Polish</strong>
<div class="grid-description"><span class="small">Comer's</span></div></div>
<div class="price">$45.00</div></div></a></div>
"""


class TestComersGunworks:
    def test_the_maker_leads_the_title_and_services_are_left_out(self):
        from app.scrapers.comers_gunworks import parse_page

        [item] = parse_page(COMERS_TILE, "https://www.comersgunworks.com/catalog/x", "B")
        assert (item.external_key, item.title, item.price, item.is_sold) == (
            "armisport-5326",
            "Armisport 42 Springfield - Used, like new",
            1325.0,
            True,
        )


class TestMuzzleLoadersAndTortuga:
    def test_an_inline_is_left_out(self):
        from app.scrapers.muzzle_loaders import MuzzleLoadersScraper

        product = {"id": 1, "handle": "x", "title": "CVA Wolf V2 .50 Cal Inline", "variants": []}
        assert MuzzleLoadersScraper().item_from_product(product, "c", "Rifles") is None

    def test_only_what_tortuga_files_as_a_firearm(self):
        from app.scrapers.tortuga_trading import TortugaTradingScraper

        flask = {
            "id": 1,
            "handle": "f",
            "title": "Wheellock Powder Flask",
            "product_type": "Powder Flasks",
        }
        assert TortugaTradingScraper().item_from_product(flask, "c", "Antique Firearms") is None
