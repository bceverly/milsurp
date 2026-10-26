"""Suppressors, a Type of their own (app.services.suppressors), and the shops
added for them on 2026-10-25. The titles are the shops' own.

Capitol Armory, Rainier Arms, Mile High Shooting, Silencer Central, KY Gun Co
and Primary Arms are also replayed from their recordings
(test_recorded_scrapers).
"""

from __future__ import annotations

import pytest

from app.models import Item
from app.scrapers.ky_gun_co import item_from_document
from app.scrapers.ky_gun_co import search_settings as ky_settings
from app.scrapers.primary_arms import item_from_record
from app.scrapers.silencer_central import item_from_hit
from app.scrapers.silencer_central import search_settings as sc_settings
from app.services import search, suppressors


@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("SilencerCo Omega 36M 30 Cal Suppressor", "Suppressors"),
        ("Abel: Pi, FDE", "Suppressors"),
        ("Dead Air Wolfman 9mm Suppressor w/ Key-Micro Mount- Black", "Suppressors"),
        ("Griffin Armament EXPLORR .30Cal Taper Mount Silencer- OD Green", "Suppressors"),
        ("Huxwrx FLOW TI .30cal Suppressor w/ Muzzle Brake- Black", "Suppressors"),
        ("DEAD AIR ARMAMENT Nomad LTi XC Silver 7.62mm Silencer Xeno Adapter", "Suppressors"),
        ("PTR VENT Spiritus Inconel Suppressor 5.56 K Hard Case", "Suppressors"),
        ("GRIFFIN ARMAMENT Optimus 7 Taper Mount", "NFA Suppressors"),
        ("Banish 30 Multi Caliber Silencer", None),
        (
            "DIAMONDBACK FIREARMS DBS-30I 30 Cal/7.62 FDE Direct Thread HUB Adapter",
            "NFA Suppressors",
        ),
        ("Faxon Firearms Twenty-Toucan", "NFA Suppressors"),
    ],
)
def test_a_suppressor(title, category):
    assert suppressors.is_suppressor(title, category=category)


@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("Thunder Beast Ultra 7 Suppressor Cover", "Suppressors"),
        ("Dead Air Key Mount 1/2x28", "Suppressors"),
        ("SilencerCo ASR Muzzle Brake 5/8x24", "Suppressors"),
        ("GRIFFIN ARMAMENT Optimus 7 Taper Mount", "Suppressors"),
        ("Front Cap for Omega 300", "Suppressors"),
        ("Glock 19 Suppressor Height Sights", "Sights"),
        ("Ruger 10/22 Integrally Suppressed Rifle .22LR", "Rifles"),
        ('CMMG FOB 5.56 NATO 16" 30rd w/ ZEROED 556K Suppressor - Black', "NFA Suppressors"),
        ("B&T Station Six-9 Suppressed Pistol - USED", "Suppressors"),
        ("B&T: GHM9 SD2 Pistol, 9mm, Kit", "Suppressors"),
        ("Glock 19 Gen 5 9mm Threaded Barrel Suppressor Ready", "Handguns"),
        ("Sig MCX Rattler .300 BLK w/ Suppressor", "Rifles"),
    ],
)
def test_not_a_suppressor(title, category):
    assert not suppressors.is_suppressor(title, category=category)


def test_it_overrules_a_can_read_as_a_rifle():
    """On production on 2026-10-26, 96 of Silencer Central's first 326 cans had
    been read as rifles -- "Rifle Suppressor", ".30 Cal", or a bare model."""
    item = Item(
        title="HUXWRX: Flow 762 TI, FDE",
        category="Suppressors",
        is_rifle=True,
        is_pistol=False,
        kind="rifle",
        firearm_model_id=12,
        barrel_inches=7.0,
    )
    assert suppressors.settle(item)
    assert not item.is_rifle and item.kind is None and item.firearm_model_id is None
    assert item.barrel_inches is None


def test_the_type_partitions_out_of_other():
    assert "suppressor" in search.KINDS
    other = str(search.KINDS["other"].compile(compile_kwargs={"literal_binds": True}))
    assert "is_suppressor" in other


def test_decide_reads_the_stored_listing_and_changes_nothing():
    item = Item(title="Dead Air Sandman-S", category="Suppressors", is_rifle=True, is_pistol=False)
    assert suppressors.decide(None, item)
    assert item.is_rifle


# -- Silencer Central ----------------------------------------------------------


def test_silencer_central_reads_its_key_from_the_page_every_time():
    page = '"applicationId":"28F06XMI7B","apiKey":"abc=","indexName":"magento2_default"'
    assert sc_settings(page) == {
        "applicationId": "28F06XMI7B",
        "apiKey": "abc=",
        "indexName": "magento2_default",
    }


def test_a_silencer_central_record():
    item = item_from_hit(
        {
            "objectID": "4410",
            "name": "BANISH 30 TI",
            "url": "https://www.silencercentral.com/products/banish-30",
            "price": {"USD": {"default": 849.0}},
            "in_stock": 1,
            "image_url": "https://www.silencercentral.com/media/b30.jpg",
            "short_description": "<p>Multi-caliber.</p>",
        }
    )
    assert item.external_key == "sc-4410" and item.price == 849.0 and not item.is_sold
    assert item.category == "NFA Suppressors" and item.description == "Multi-caliber."
    assert item_from_hit({"objectID": "1", "name": "X", "url": "u", "in_stock": False}).is_sold


# -- KY Gun Co -----------------------------------------------------------------


def test_ky_gun_co_reads_its_settings_from_the_page():
    page = 'typesense:{url:"https://search.keenesdepot.io",apiKey:"2axy",x:1} kygunco_products_1773666625'
    assert ky_settings(page) == (
        "https://search.keenesdepot.io",
        "2axy",
        "kygunco_products_1773666625",
    )


def test_a_ky_gun_co_record():
    item = item_from_document(
        {
            "id": "300100",
            "slug": "silencerco-omega-36m",
            "name": "SILENCERCO Omega 36M 7.6in Silencer / Suppressor - Black",
            "price": 993.65,
            "caliber": [".36 Cal"],
            "manufacturer": {"name": "SilencerCo"},
            "isInStock": True,
            "condition": "New",
            "imageUrl": "https://cdn.kygunco.com/assets/products/300100/main.jpg",
        }
    )
    assert item.url == "https://www.kygunco.com/product/silencerco-omega-36m"
    assert item.manufacturer == "SilencerCo" and item.caliber == ".36 Cal"
    assert item.is_new and not item.is_sold and item.category == "NFA Suppressors"


# -- Primary Arms --------------------------------------------------------------


def test_primary_arms_keeps_only_what_the_shop_flags_as_nfa():
    record = {
        "internalid": 262871,
        "urlcomponent": "rugged-alaskan360",
        "pagetitle": "Rugged Suppressors Alaskan360 Multi Caliber Suppressor",
        "displayname": "AK360",
        "onlinecustomerprice": 868.0,
        "isinstock": True,
        "manufacturer": "Rugged Suppressors",
        "custitem_isnfa": True,
        "itemimages_detail": {
            "urls": [{"url": "https://www.primaryarms.com/SSP Applications/img/AK360_01.jpg"}]
        },
    }
    item = item_from_record(record)
    assert item.title.startswith("Rugged Suppressors Alaskan360")
    assert item.url == "https://www.primaryarms.com/rugged-alaskan360"
    assert item.image_urls == ["https://www.primaryarms.com/SSP%20Applications/img/AK360_01.jpg"]
    assert item_from_record({**record, "custitem_isnfa": False}) is None
