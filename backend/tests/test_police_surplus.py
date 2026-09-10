"""Police surplus: the two vendors, and the Type they introduced.

Departments trade their duty weapons in by the lot and dealers sell them as a
named section. It is not military surplus and it is the same question this
catalog asks — somebody's service weapon, sold on, in quantity — so it gets its
own bucket in the browse filter rather than being scattered through Rifles and
Handguns.
"""

from __future__ import annotations

import pathlib

import pytest

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.bigcommerce import BigCommerceScraper
from app.scrapers.officer_store import OfficerStoreScraper
from app.scrapers.recoil_gun_works import RecoilGunWorksScraper
from app.services import classify
from app.services.search import KINDS

BACKEND = pathlib.Path(__file__).resolve().parents[1]


class TestBothShopsAreRegistered:
    @pytest.mark.parametrize(
        ("slug", "cls"),
        [("recoil-gun-works", RecoilGunWorksScraper), ("officer-store", OfficerStoreScraper)],
    )
    def test_the_registry_knows_it(self, slug, cls):
        assert isinstance(get_scraper(slug), cls)
        assert cls in SCRAPER_CLASSES
        assert issubclass(cls, BigCommerceScraper)
        assert cls.requires_browser is False


class TestWhichSectionsAreRead:
    """The sections were chosen by opening them, and the choices are what a
    later reader cannot re-derive from the code."""

    def urls(self, cls):
        return {source["url"] for source in cls.sources}

    def test_recoil_reads_the_three_firearm_leaves(self):
        assert self.urls(RecoilGunWorksScraper) == {
            "https://www.recoilgunworks.com/police-trade-in/firearms/pd-trade-pistols/",
            "https://www.recoilgunworks.com/police-trade-in/firearms/pd-trade-rifles/",
            "https://www.recoilgunworks.com/police-trade-in/firearms/pd-trade-shotguns/",
        }

    def test_and_not_the_parent_above_them(self):
        """`/police-trade-in/` is a mixed shelf: its first page holds Federal
        HST, Speer Gold Dot and a $10.99 Glock magazine beside the pistols."""
        assert not any(
            u.rstrip("/").endswith("police-trade-in") for u in self.urls(RecoilGunWorksScraper)
        )

    def test_and_not_their_surplus_section(self):
        """The trap of the four, because the name is exactly right and the
        contents are not: Scott M98 respirators, UTM and Simunition marking
        cartridges, a P226 UTM conversion kit."""
        assert not any("/surplus" in u for u in self.urls(RecoilGunWorksScraper))

    def test_nor_the_gear_and_magazines(self):
        for section in ("equipment", "magazines"):
            assert not any(section in u for u in self.urls(RecoilGunWorksScraper))

    def test_officer_store_reads_its_one_firearms_section(self):
        assert self.urls(OfficerStoreScraper) == {
            "https://officerstore.com/firearms/used-firearms/"
        }

    def test_every_section_names_itself_as_a_trade_in(self):
        """Which is what makes the listings police surplus: the classifier
        reads the vendor's section, and nothing else says so."""
        for cls in (RecoilGunWorksScraper, OfficerStoreScraper):
            for source in cls.sources:
                assert classify._is_police_surplus(source["category"], is_firearm=True)


class TestWhatMakesAListingPoliceSurplus:
    """The vendor's section, and the listing being a firearm. Nothing else.

    A PD Trade Glock 22 is mechanically the same object as any other Glock 22;
    nothing in its title distinguishes it. That is the opposite of a parts kit,
    where the section over-claims and the listing has to corroborate — and it
    is why there is no title test here.
    """

    def kind_of(self, title, category, description=None, price=500.0):
        derived = classify.enrich(title, description, price, category=category)
        return derived["is_police_surplus"], derived["is_rifle"], derived["is_pistol"]

    def test_a_glock_in_a_police_section_is_police_surplus(self):
        assert self.kind_of("PD Trade | Glock 22 | 40 S&W", "Police Trade-In Pistols") == (
            True,
            False,
            True,
        )

    def test_and_is_still_a_handgun(self):
        """The column sits alongside is_pistol rather than replacing it: the
        armory and the caliber work should keep getting the true answer."""
        police, _, pistol = self.kind_of("PD Trade | Glock 22 | 40 S&W", "Police Trade-In Pistols")
        assert police and pistol

    def test_law_enforcement_is_the_same_claim(self):
        assert self.kind_of("LE Trade-In Glock 21 Gen 4, .45 ACP", "Law Enforcement Trade-Ins")[0]

    def test_a_shotgun_counts_too(self):
        assert self.kind_of("PD Trade | 870 Police Magnum | 12GA", "Police Trade-In Shotguns")[0]

    def test_an_accessory_in_the_same_section_does_not(self):
        """These sections are not pure — Officer Store shelve used Glock
        magazines among the pistols — and an accessory belongs where every
        other accessory goes."""
        police, rifle, pistol = self.kind_of(
            "Glock 22 Magazine, Used Glock Mag Used",
            "Law Enforcement Trade-Ins",
            "Used Glock factory magazine, .40 S&W, 15 round capacity.",
            # Its real price. At $500 the classifier reads it as the pistol,
            # and rightly: nobody sells a magazine for that.
            price=10.0,
        )
        assert not police
        assert not (rifle or pistol)

    def test_ordinary_milsurp_is_not_police_surplus(self):
        assert not self.kind_of("RUSSIAN M44 CARBINE", "Foreign Military Rifles")[0]

    def test_and_neither_is_a_title_that_merely_says_so(self):
        """A fact about the section, not about the gun. Without a section
        saying it, a title claiming it proves nothing."""
        assert not self.kind_of("Police Trade In Glock 17", None)[0]


class TestTheTypesStillPartitionTheCatalog:
    """Six buckets, and every listing in exactly one.

    Police surplus is subtracted from Rifles and Handguns in KINDS rather than
    by making is_pistol lie — so this is where the two views are reconciled.
    """

    def test_police_surplus_is_one_of_the_types(self):
        assert "police_surplus" in KINDS

    def test_rifles_and_handguns_exclude_it(self):
        for kind in ("rifle", "pistol"):
            assert "is_police_surplus" in str(KINDS[kind])

    def test_other_needs_no_exclusion(self):
        """It is only ever true for a listing that is already a rifle or a
        handgun, so "neither of those" excludes it already."""
        assert "is_police_surplus" not in str(KINDS["other"])


class TestASpecListPutsTheProductFirst:
    """Recoil write every title as "PD Trade | 870 Police Magnum | 12GA | Wood
    Stock", and the accessory test reads English word order — the thing being
    sold sits last. In a specification list that is exactly backwards, and it
    cost seven firearms: two Mini-14s and an LWRCI REPR read as a stock and a
    barrel, four 870s and a 590A1 as stocks.

    **Measured before it was written:** no listing in the stored catalog of
    4,121 uses a pipe in its title, so narrowing the head-noun question to the
    first segment cannot change what any existing vendor is filed as.
    """

    def is_rifle(self, title, category="Police Trade-In Rifles"):
        return classify.enrich(title, None, 500.0, category=category)["is_rifle"]

    @pytest.mark.parametrize(
        "title",
        [
            "PD Trade | 870 Police Magnum | 12GA | Wood Stock",
            "PD Trade | Mini-14 | .223 REM | Archangel Stock",
            "PD Trade | 590A1 | 12GA | Surefire Forend | Knoxx Stock | Side Saddle",
            "PD Trade | LWRCI REPR MKII | 7.62 Nato | Carbon Fiber Barrel",
        ],
    )
    def test_a_feature_after_a_pipe_is_not_the_product(self, title):
        assert self.is_rifle(title)

    def test_an_ordinary_title_is_read_as_before(self):
        """No pipe, no change — which is what makes this safe for every vendor
        already in the catalog."""
        assert not self.is_rifle("M1 Garand Rifle Barrel", category=None)
        assert not self.is_rifle("Springfield Trapdoor and Krag Rifle Leather Sling", category=None)
        assert not self.is_rifle("Remington 870 Wood Stock", category=None)


class TestArmsUnlimitedWasRestoredOnASectionNobodyOpened:
    """Written, backed out, and restored — and the refusal was right about what
    it examined.

    `/surplus/` really is police trade-in *gear*: Tasers, Taser batteries, a
    Magpul rear sight, a stainless water bottle. `/firearms/` really is current
    production: Beretta A300s and 92FSs, B&T suppressors, a Colt M4A1 SOCOM.
    Both re-checked when this shipped, and both still refused.

    What the original call missed is that the shop was condemned whole. It has
    a third section, `/used-collectible-firearms/`, and twelve of its twenty
    listings are military: Zastava M57s, M88As and M83s, a Beretta 70, an M79
    Thumper, a French FRF2 sniper rifle, a SIG PE57, HK AG36 and HK69A1
    launchers, an 1881 Colt Gatling gun.
    """

    def urls(self):
        from app.scrapers.arms_unlimited import ArmsUnlimitedScraper

        return {source["url"] for source in ArmsUnlimitedScraper.sources}

    def test_it_is_registered_again(self):
        from app.scrapers.arms_unlimited import ArmsUnlimitedScraper

        assert isinstance(get_scraper("arms-unlimited"), ArmsUnlimitedScraper)
        assert ArmsUnlimitedScraper in SCRAPER_CLASSES
        assert issubclass(ArmsUnlimitedScraper, BigCommerceScraper)

    def test_it_reads_the_used_and_collectible_section(self):
        assert self.urls() == {"https://armsunlimited.com/used-collectible-firearms/"}

    def test_and_still_refuses_the_gear(self):
        """The section that got the shop dropped the first time."""
        assert not any("/surplus" in url for url in self.urls())

    def test_and_still_refuses_the_current_production(self):
        assert not any(url.rstrip("/").endswith("/firearms") for url in self.urls())

    def test_and_does_not_read_the_trade_programme_page(self):
        """`/department-trade-program/` describes how a department trades its
        weapons in. It holds no products at all."""
        assert not any("department-trade-program" in url for url in self.urls())

    def test_their_section_is_not_police_surplus(self):
        """ "Used & Collectible Firearms" says nothing about a trade-in, so
        these are ordinary listings — which is the rule working, not a gap.
        Arms Unlimited is on the police list because of who they sell to, and
        the flag is about what the section says."""
        assert not classify._is_police_surplus("Used & Collectible Firearms", is_firearm=True)


class TestTheFlagSurvivesAScan:
    """The classifier deriving it is not the same as the row carrying it.

    It was not: `_upsert_item` assigned is_rifle, is_pistol, is_bayonet and
    is_parts_kit and silently dropped is_police_surplus, so 263 listings were
    stored under "Police Trade-In Pistols" with the flag false and the browse
    filter showed an empty bucket. Everything upstream was right and the
    catalog was still wrong, which is exactly the gap a classifier test cannot
    see.

    **This is the second time.** The comment above that assignment records the
    first: enrich() returned is_rifle/is_pistol from the very first commit and
    nothing read them onto the row, so every listing on every site sat at the
    column default and the Rifles filter matched nothing. Hence the last test
    here, which is about the shape of the mistake rather than this instance of
    it.
    """

    def test_every_flag_the_classifier_derives_is_stored(self):
        """A new flag added to enrich() and not to the assignment below it is
        invisible until somebody looks at a filter and finds it empty."""
        import inspect

        from app.services import scan_service

        source = inspect.getsource(scan_service._upsert_item)
        for flag in ("is_rifle", "is_pistol", "is_bayonet", "is_parts_kit", "is_police_surplus"):
            assert f'derived["{flag}"]' in source, f"{flag} is derived but never stored"

    def test_and_reclassify_writes_it_too(self):
        """`make reclassify` has its own copy of that mapping, which is the
        other place a new flag gets forgotten."""
        source = (BACKEND / "cli.py").read_text(encoding="utf-8")
        assert '"is_police_surplus": derived["is_police_surplus"]' in source
