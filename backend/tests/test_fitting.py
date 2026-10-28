"""Magazines and speedloaders that fit owned guns (app.services.fitting),
layer 2 of "Upgrades and accessories for the guns you own", 2026-10-28."""

from __future__ import annotations

import json

import pytest

from app.models import AccessoryOffer, ArmoryStatus, CollectionItem, FirearmModel, User, utcnow
from app.services import armory, fitting


class FakeStore:
    """GunMag Warehouse's page and Algolia, and Speed Beez's Store API."""

    def __init__(self, hits, products):
        self.hits = hits
        self.products = products
        self.asked = []

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        if url == fitting.GUNMAG_PAGE:
            return '"applicationId":"APP","apiKey":"KEY","indexName":"m2_prod_default"'
        if "algolia" in url:
            return json.dumps({"hits": self.hits})
        if "speedbeez" in url:
            return json.dumps(self.products if "page=1" in url else [])
        raise AssertionError(url)

    def keep_at_least(self, *_args):
        pass

    def check_stop(self):
        pass


@pytest.fixture
def owned(clean_db):
    beretta = FirearmModel(
        name="Beretta 92FS", aliases="92FS\nBeretta 92", status=ArmoryStatus.APPROVED
    )
    ruger = FirearmModel(name="Ruger GP100", aliases="GP100", status=ArmoryStatus.APPROVED)
    user = User(username="owner", email="o@example.test", password_hash="x")
    clean_db.add_all([beretta, ruger, user])
    clean_db.flush()
    clean_db.add_all(
        [
            CollectionItem(user_id=user.id, title="Dad's 92", firearm_model_id=beretta.id),
            CollectionItem(user_id=user.id, title="Wheel gun", firearm_model_id=ruger.id),
        ]
    )
    clean_db.commit()
    armory.invalidate()
    yield beretta, ruger
    armory.invalidate()


MAG = {
    "objectID": "77",
    "name": "Mec-Gar Beretta 92FS / M9 9mm 15-Round Magazine",
    "url": "https://gunmagwarehouse.com/mecgar-92.html",
    "price": {"USD": {"default": 19.99}},
    "in_stock": 1,
    "compatible_firearm": ["Beretta 90-Two", "Beretta 92", "Beretta M9"],
    "am_brand": "Mec-Gar",
}
GLOCK_MAG = {**MAG, "objectID": "78", "name": "Glock mag", "compatible_firearm": ["Glock 19"]}
POUCH = {
    "id": 5,
    "name": "SPEED BEEZ\u00ae Speed-Cases",
    "permalink": "https://www.speedbeez.com/product/cases/",
    "prices": {"price": "5995", "currency_minor_unit": 2},
    "is_in_stock": True,
    "attributes": [{"name": "Gun Model", "terms": [{"name": "GP100\u2122 \u2013 .357, 6 Shot"}]}],
}


def test_a_refresh_keeps_what_the_stores_say_fits_an_owned_gun(clean_db, owned):
    beretta, ruger = owned
    store = FakeStore([MAG, GLOCK_MAG], [POUCH])
    result = fitting.refresh(clean_db, store, log_line=lambda _line: None)
    assert result.kept == {fitting.GUNMAG: 1, fitting.SPEEDBEEZ: 1}
    offers = fitting.for_model(clean_db, beretta.id)
    assert [offer.title for offer in offers] == [MAG["name"]]
    assert offers[0].price == 19.99 and offers[0].source == "GunMag Warehouse"
    loaders = fitting.for_model(clean_db, ruger.id)
    assert [offer.price for offer in loaders] == [59.95]


def test_a_store_that_does_not_answer_keeps_yesterdays_offers(clean_db, owned):
    beretta, _ruger = owned
    clean_db.add(
        AccessoryOffer(
            source=fitting.GUNMAG,
            external_key="old",
            kind="magazine",
            title="Yesterday's mag",
            url="https://x.test",
            fits="Beretta 92FS",
            refreshed_at=utcnow(),
        )
    )
    clean_db.commit()

    class Down(FakeStore):
        def get_text(self, url, **kwargs):
            from app.scrapers.base import ScrapeError

            if url == fitting.GUNMAG_PAGE:
                raise ScrapeError("down")
            return super().get_text(url, **kwargs)

    fitting.refresh(clean_db, Down([], []), log_line=lambda _line: None)
    assert [offer.title for offer in fitting.for_model(clean_db, beretta.id)] == ["Yesterday's mag"]


def test_nobody_owns_anything(clean_db):
    assert fitting.refresh(clean_db, FakeStore([], []), log_line=lambda _l: None).asked == 0
