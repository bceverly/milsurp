"""One-click store searches for an owned gun (app.services.shoplinks), slice 1
of "Upgrades and accessories for the guns you own", 2026-10-27."""

from __future__ import annotations

from types import SimpleNamespace

from app.models import FirearmKind
from app.services import shoplinks


def _row(title, model=None, kind=None):
    firearm_model = SimpleNamespace(name=model, kind=kind) if model else None
    return SimpleNamespace(title=title, firearm_model=firearm_model)


def _shelf(found, label):
    return next(shelf for shelf in found if shelf.label == label)


def test_a_pistol_gets_magazines_at_gunmag_warehouse_first():
    found = shoplinks.shelves(_row("My carry gun", "Glock 19", FirearmKind.PISTOL))
    magazines = _shelf(found, "Magazines")
    assert magazines.query == "Glock 19 magazine"
    assert magazines.links[0].store == "GunMag Warehouse"
    assert magazines.links[0].url == (
        "https://gunmagwarehouse.com/catalogsearch/result/?q=Glock+19+magazine"
    )
    assert {shelf.label for shelf in found} >= {"Holsters", "Grips and sights", "Parts"}


def test_a_revolver_gets_speedloaders_not_magazines():
    found = shoplinks.shelves(_row("Dad's", "Smith & Wesson Model 10", FirearmKind.REVOLVER))
    labels = [shelf.label for shelf in found]
    assert "Speedloaders and moon clips" in labels and "Magazines" not in labels
    loaders = _shelf(found, "Speedloaders and moon clips")
    assert loaders.links[0].url == (
        "https://www.brownells.com/search/?search=Smith+%26+Wesson+Model+10+speedloader"
    )


def test_a_shotgun_gets_chokes_and_a_muzzleloader_gets_parts():
    assert "Chokes" in [s.label for s in shoplinks.shelves(_row("x", "Remington 870", "shotgun"))]
    percussion = shoplinks.shelves(_row("x", "Colt 1851 Navy", FirearmKind.PERCUSSION_REVOLVER))
    assert [shelf.label for shelf in percussion] == ["Parts"]
    assert percussion[0].links[0].store == "Numrich Gun Parts"


def test_a_gun_with_no_model_is_searched_by_what_its_owner_called_it():
    found = shoplinks.shelves(_row("Grandpa's Mauser"))
    assert _shelf(found, "Magazines").query == "Grandpa's Mauser magazine"
    assert shoplinks.shelves(_row("   ")) == []


def test_every_store_has_a_search_address():
    for template in shoplinks.STORES.values():
        assert template.startswith("https://") and "{q}" in template
