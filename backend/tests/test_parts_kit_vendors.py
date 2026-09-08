"""The three vendors added for their parts kits.

Apex Gun Parts, Arms of America and Bowman Arms are the first shops on this
list whose reason for being here is the kit rather than the gun. The walks
themselves belong to their platforms and are covered by test_magento.py and
test_bigcommerce.py; what is pinned here is the per-shop judgment that a live
measurement established and that nothing in the code would notice going stale.

The judgment they share is a boundary: **a parts kit is in, a loose part is
not, and a modern build is not.** Every one of the three has stock on the wrong
side of it, and each scraper's ``sources`` is the record of where the line was
drawn.
"""

from __future__ import annotations

import pytest

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.apex_gun_parts import ApexGunPartsScraper
from app.scrapers.arms_of_america import ArmsOfAmericaScraper
from app.scrapers.bigcommerce import BigCommerceScraper
from app.scrapers.bowman_arms import BowmanArmsScraper
from app.scrapers.magento import MagentoScraper

SHOPS = (ApexGunPartsScraper, ArmsOfAmericaScraper, BowmanArmsScraper)


class TestTheyAreRegistered:
    @pytest.mark.parametrize("scraper", SHOPS)
    def test_the_registry_knows_it(self, scraper):
        assert isinstance(get_scraper(scraper.slug), scraper)

    @pytest.mark.parametrize("scraper", SHOPS)
    def test_and_lists_it(self, scraper):
        assert scraper in SCRAPER_CLASSES

    @pytest.mark.parametrize("scraper", SHOPS)
    def test_none_of_them_needs_a_browser(self, scraper):
        """All three render their catalogs server-side. Measured, not assumed:
        the roadmap had SARCO down as needing one on the evidence of an empty
        page, and it did not."""
        assert scraper.requires_browser is False

    @pytest.mark.parametrize("scraper", SHOPS)
    def test_they_keep_the_gentle_pace(self, scraper):
        assert scraper.min_request_delay >= 2

    @pytest.mark.parametrize("scraper", SHOPS)
    def test_every_source_is_on_the_shops_own_site(self, scraper):
        for source in scraper.sources:
            assert source["url"].startswith(scraper.base_url)

    @pytest.mark.parametrize("scraper", SHOPS)
    def test_every_source_names_its_section(self, scraper):
        """The section name becomes the ``category`` the classifier trusts over
        its own reading of a title, so an unnamed source throws that away."""
        for source in scraper.sources:
            assert source["category"].strip()


class TestApexGunParts:
    """Parts only, and they say so themselves: their "Rifles", "Handguns" and
    "Machine Guns" menus are *parts* sections organized by the gun the part
    fits. 57 of the first 60 parts kits read as a kit and all 60 carry a price.
    """

    def test_it_is_a_magento_shop(self):
        assert issubclass(ApexGunPartsScraper, MagentoScraper)

    def test_the_parts_kit_section_is_the_whole_of_it(self):
        assert [source["category"] for source in ApexGunPartsScraper.sources] == ["Parts Kits"]

    def test_it_pages_the_category_rather_than_walking_facets(self):
        """Facet-walking is Classic Firearms' workaround for a robots.txt that
        disallows ``?p=``. Apex serves an empty robots.txt -- nothing is
        disallowed -- so ordinary pagination is both permitted and cheaper."""
        assert ApexGunPartsScraper.follow_facets is False

    def test_their_escaped_names_are_why_the_base_class_decodes_entities(self):
        """Apex is the shop that found this. Their structured data carries
        ``1911 Pistol Parts Kit, 5&quot; Barrel`` where the ``<h1>`` beside it
        carries ``5" Barrel`` -- and the base class prefers the structured data,
        so without the decode the entity is what gets stored and shown."""
        from app.scrapers.magento import _plain_text

        assert _plain_text("1911 Parts Kit, 5&quot; Barrel &amp; Grips") == (
            '1911 Parts Kit, 5" Barrel & Grips'
        )

    def test_their_description_is_read_from_the_markup(self):
        """Their schema.org ``description`` is Magento's meta description, so
        on a Page Builder page it is that layout's stylesheet, truncated at 120
        characters, on every single product. The real text sits in an id with
        dots in it, which no stock Magento selector matches -- so the shop has
        to name it, and the base class has to be willing to ask."""
        assert '[id="product.info.description"]' in ApexGunPartsScraper.detail_description_selectors

    def test_no_firearm_section_is_claimed(self):
        """Guarding the thing a future reader would most likely get wrong:
        their nav says "Rifles" and "Handguns", and neither sells a gun."""
        urls = [source["url"] for source in ApexGunPartsScraper.sources]
        assert not any("rifle" in url or "handgun" in url for url in urls)


class TestArmsOfAmerica:
    """Kits and four Swiss C&R rifles in; the modern builds out."""

    def test_it_is_a_bigcommerce_shop(self):
        assert issubclass(ArmsOfAmericaScraper, BigCommerceScraper)

    def test_it_reads_the_kits_and_the_surplus_rifles(self):
        assert [source["category"] for source in ArmsOfAmericaScraper.sources] == [
            "Parts Kits",
            "Military Surplus",
        ]

    def test_the_modern_builds_are_left_alone(self):
        """``/firearms/rifles/`` is WBP Fox and Jack AKs, FB Radom Beryls and
        the shop's own AKM builds; ``/our-products/firearms/pistols/`` is Mini
        Jack AK pistols. Same call that backed this list out of Arms Unlimited
        and out of Legacy Collectibles' modern stock."""
        urls = [source["url"] for source in ArmsOfAmericaScraper.sources]
        assert not any(url.endswith("/firearms/rifles/") for url in urls)
        assert not any("pistols" in url for url in urls)

    def test_the_surplus_section_is_the_specific_one(self):
        """Not the parent ``/firearms/``, which is the modern stock plus these
        four. The narrower path is what keeps the boundary."""
        assert any(
            source["url"].endswith("/firearms/military-surplus/")
            for source in ArmsOfAmericaScraper.sources
        )


class TestBowmanArms:
    """Seventeen listings, all kits, all priced, and no firearms section to
    leave out -- the only shop on the list where the boundary needed no call.
    """

    def test_it_is_a_bigcommerce_shop(self):
        assert issubclass(BowmanArmsScraper, BigCommerceScraper)

    def test_the_parts_kit_section_is_the_whole_of_it(self):
        assert [source["category"] for source in BowmanArmsScraper.sources] == ["Parts Kits"]


class TestTheKitsAreClassifiedAsKits:
    """The point of adding these three: their stock has to come out of the
    scan as parts kits, not as rifles. Titles taken verbatim from the live
    catalogs.

    A kit is a kit "regardless of how the ATF categorizes it" -- a torch-cut
    receiver included -- which is the rule ``_is_a_parts_kit`` was rewritten
    around and which these hold to it.
    """

    @pytest.mark.parametrize(
        "title",
        [
            # Apex Gun Parts
            "Beretta M38/49 Parts Kit, 9mm, *Very Good*",
            "Brazilian 1908 Mauser Rifle Parts Kit, 7mm, *Good*",
            "British Hotchkiss M1909 Portative LMG Parts Kit, .303 British",
            "German C93 Parts Kit, 7.92x57mm, *Fair*",
            "Spanish CETME Model C Parts Kit, 7.62x51mm, *Very Good*",
            "British STEN Mk3 Parts Kit, 9mm, *Very Good*",
            # Arms of America
            "PPSh-41 Parts Kit with Drum Magazine",
            "Yugo M72B1 RPK Parts Kit",
            "Polish Radom DPM Parts Kit",
            "Sig STG 57 Parts Kit",
            # Bowman Arms
            "Polish PM63 RAK Parts Kit",
            "Yugoslavian M56 Parts Kit",
            "Israeli FAL Parts Kit",
            "1928 Thompson Parts Kit",
        ],
    )
    def test_a_kit_reads_as_a_kit(self, title):
        from app.services.classify import enrich

        fields = enrich(title, category="Parts Kits")
        assert fields["is_parts_kit"] is True

    @pytest.mark.parametrize(
        "title",
        [
            "PPSh-41 Parts Kit with Drum Magazine",
            "Brazilian 1908 Mauser Rifle Parts Kit, 7mm, *Good*",
            "Israeli FAL Parts Kit",
        ],
    )
    def test_and_not_also_as_a_firearm(self, title):
        """The kit wins outright. "Mauser Rifle Parts Kit" says "Rifle" in it
        and is not one; a listing that is both would show up in the rifle
        browse and be wrong there."""
        from app.services.classify import enrich

        fields = enrich(title, category="Parts Kits")
        assert fields["is_rifle"] is False
        assert fields["is_pistol"] is False
