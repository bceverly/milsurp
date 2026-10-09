"""Black powder: the rule, and the Type it fills.

Asked for on 2026-10-08. The cases are titles from production's 14,930 guns,
the rule measured against all of them before it shipped -- including the ones
it was caught taking on the way: military "Long Rifles", a Colt's "black powder
frame", a top-break "(black powder loads)".
"""

from __future__ import annotations

import inspect
import pathlib

import pytest
from sqlalchemy import func, select

from app.models import Item, Site
from app.services import blackpowder, hotdeals
from app.services.search import KINDS

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def powder(title, *, kind=None, is_rifle=True, is_pistol=False, is_parts_kit=False):
    return blackpowder.is_black_powder(
        title, is_rifle=is_rifle, is_pistol=is_pistol, is_parts_kit=is_parts_kit, kind=kind
    )


class TestWhatIsBlackPowder:
    @pytest.mark.parametrize(
        ("title", "kind"),
        [
            ("VERY RARE MODEL 1809 BROWN BESS FLINTLOCK MUSKET", None),
            ("U.S. Model 1819 Flintlock Pistol by Simeon North (AH5758)", "flintlock_pistol"),
            ("Confederate British Pattern 1853 Rifle Musket (AL7505)", "rifle"),
            ("J. HAYDEN ENGLISH DOUBLE BARREL PERCUSSION SHOTGUN", "shotgun"),
            ("Very Rare 16th Century German Military Match Lock (75174)", None),
            ("LANCASTER, PENNSYLVANIA PERCUSSION LONGRIFLE SIGNED G. F. FAINOT", None),
            ("Italian-made Uberti M1858 Remington Black Powder Revolver", "revolver"),
            ("Gorgeous Pedersoli Sharps 1859 Carbine - Blackpowder", "carbine"),
            ("USED Thompson Center Patriot 45CAL Black Powder Pistol", "pistol"),
            # The armory's kind is enough on its own.
            ("COLT'S MODEL 1861 NAVY REVOLVER", "percussion_revolver"),
        ],
    )
    def test_these_are(self, title, kind):
        assert powder(title, kind=kind)

    @pytest.mark.parametrize(
        ("title", "kind"),
        [
            # Converted to take cartridges, whatever the armory's model says.
            ("Colt Model 1860 Army Richards Conversion Revolver", "percussion_revolver"),
            ("Whitney Navy Percussion Revolver Altered to Cartridge", "percussion_revolver"),
            ("SHARPS NEW MODEL 1863 CARTRIDGE CONVERSION CARBINE", "percussion_rifle"),
            ("Remington New Model Pocket Revolver 32 RF Conversion", "percussion_revolver"),
            # A military rifle's length, and a .22 cartridge.
            ("Very Nice Steyr M95 Long Rifle - 8x50R", "rifle"),
            ("J.C. HIGGINS MODEL 103.18 .22 SHORT, LONG & LONG RIFLE CAL. RIFLE", "rifle"),
            # Black powder describing a cartridge gun.
            ("BLACK POWDER FRAME COLT FRONTIER SIX SHOOTER SAA", "revolver"),
            ("H&R First Model Hammerless 38 S&W (black powder loads)", None),
            ("ORIGINAL ANTIQUE COLT BLACK POWDER SINGLE ACTION .32WCF CAL.", None),
            ("Shiloh Sharps 1874 Black Powder Cartridge Rifle", "rifle"),
            # Cartridge guns of the same age.
            ("Springfield Model 1884 Trapdoor .45-70", "rifle"),
        ],
    )
    def test_these_are_not(self, title, kind):
        assert not powder(title, kind=kind)

    def test_only_a_firearm_and_never_a_kit(self):
        assert not powder("Percussion cap tin", is_rifle=False)
        assert not powder("Flintlock musket lock parts kit", is_parts_kit=True)


class TestBothPathsSetIt:
    def test_the_scan_does(self):
        from app.services import scan_service

        assert "blackpowder.decide(session, item)" in inspect.getsource(scan_service._settle_last)

    def test_and_reclassify_does(self):
        source = (BACKEND / "cli.py").read_text(encoding="utf-8")
        assert "blackpowder.decide(session, item)" in source


class TestTheType:
    """Black powder outranks the other gun Types, and each listing is still
    counted once."""

    @pytest.fixture
    def shelf(self, clean_db):
        site = Site(slug="s", name="S", base_url="https://s.test/")
        clean_db.add(site)
        clean_db.flush()
        rows = {
            "musket": dict(is_rifle=True, is_black_powder=True),
            "revolver": dict(is_pistol=True, is_black_powder=True),
            # A loose rule calling a cap-and-ball revolver a carry gun too.
            "both": dict(is_pistol=True, is_black_powder=True, is_concealed_carry=True),
            "rifle": dict(is_rifle=True),
            "carry": dict(is_pistol=True, is_concealed_carry=True),
        }
        for key, flags in rows.items():
            clean_db.add(
                Item(
                    site_id=site.id,
                    external_key=key,
                    url=f"https://s.test/{key}",
                    title=key,
                    **flags,
                )
            )
        clean_db.commit()
        return clean_db

    def keys(self, session, kind):
        return set(session.execute(select(Item.external_key).where(KINDS[kind])).scalars())

    def test_each_listing_lands_in_one_type(self, shelf):
        assert self.keys(shelf, "black_powder") == {"musket", "revolver", "both"}
        assert self.keys(shelf, "rifle") == {"rifle"}
        assert self.keys(shelf, "concealed_carry") == {"carry"}
        assert self.keys(shelf, "pistol") == set()

    def test_and_the_types_still_add_up(self, shelf):
        total = shelf.execute(select(func.count(Item.id))).scalar_one()
        assert sum(len(self.keys(shelf, kind)) for kind in KINDS) == total

    def test_hot_deals_buckets_agree(self, shelf):
        rows = {row.external_key: row for row in shelf.execute(select(Item)).scalars()}
        assert hotdeals.bucket_of(rows["both"]) == "black_powder"
        assert hotdeals.bucket_of(rows["musket"]) == "black_powder"
        assert hotdeals.BUCKET_LABELS["black_powder"] == "Black powder"


class TestTheShopsSections:
    """A muzzleloading shop says it once, in the section name, for every gun
    in it -- and the classifier reads the section as a firearms section."""

    def test_the_section_says_it(self):
        assert blackpowder.is_black_powder(
            "Traditions Crockett Squirrel Rifle - .32 Caliber",
            is_rifle=True,
            is_pistol=False,
            category="Traditional Muzzleloaders",
        )

    def test_but_not_over_a_cartridge_or_an_inline(self):
        for title in ("CVA Wolf .50 Cal Inline Muzzleloader", "Sharps 1874 .45-70 Musket"):
            assert not blackpowder.is_black_powder(
                title, is_rifle=True, is_pistol=False, category="Muzzleloaders"
            )

    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            ("SPRINGFIELD M1842 MUSKET", True),
            ("U.S. Model 1847 Artillery Musketoon (AL4084)", True),
            ("English Box-lock Flint Pistol w/Silver Butt Cap by WATERS, LONDON", True),
            ("PEABODY MARTINI ENGRAVED MUSKET", False),
            ("Winchester 1873 44-40 Musket Made In 1894", False),
            ("WEBLEY & SCOTT WWI FENCING MUSKET MKXI", False),
        ],
    )
    def test_muskets(self, title, wanted):
        assert powder(title) is wanted

    def test_a_hawken_described_by_its_stock_is_a_rifle(self):
        from app.services.classify import classify_firearm

        title = "Pedersoli Rocky Mountain Hawken - Maple Stock .54 Cal Percussion"
        assert classify_firearm(title, category="Traditional Muzzleloaders") == (True, False)
        # While a stock for sale is still a stock.
        assert classify_firearm("Mauser K98 Walnut Stock") == (False, False)
