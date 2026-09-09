"""Atlantic Firearms — which three of their nine sections, and why not the others.

The most-visited site on the roadmap, and the first PrestaShop shop. The walk
belongs to the platform and is covered by test_prestashop.py; what is pinned
here is the judgment a live measurement of all six candidate sections
established, and the caveat that goes with it.
"""

from __future__ import annotations

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.atlantic_firearms import SITE_BASE, AtlanticFirearmsScraper
from app.scrapers.prestashop import PrestaShopScraper


class TestItIsRegistered:
    def test_the_registry_knows_it(self):
        assert isinstance(get_scraper("atlantic-firearms"), AtlanticFirearmsScraper)

    def test_and_lists_it(self):
        assert AtlanticFirearmsScraper in SCRAPER_CLASSES

    def test_it_is_the_prestashop_shop(self):
        assert issubclass(AtlanticFirearmsScraper, PrestaShopScraper)

    def test_no_browser_is_needed(self):
        assert AtlanticFirearmsScraper.requires_browser is False


class TestWhichSectionsAreTaken:
    def test_the_three(self):
        assert [source["category"] for source in AtlanticFirearmsScraper.sources] == [
            "C&R Eligible",
            "Parts Kits",
            "Bayonets",
        ]

    def test_their_gear_sections_are_refused(self):
        """Measured, not assumed. `/military-surplus` is 180 listings of which
        98 read as neither gun nor kit — gas masks, rucksacks, ammo pouches,
        thread protectors, magazine grips — and `/surplus-guns-gear` is the
        same stock under an honestly-named heading. Together with
        `/soviet-russian-surplus` the four refused sections are 318 unique
        listings, 123 of them gear."""
        urls = " ".join(source["url"] for source in AtlanticFirearmsScraper.sources)
        for refused in ("military-surplus", "surplus-guns-gear", "soviet-russian-surplus"):
            assert refused not in urls

    def test_and_so_is_their_modern_stock(self):
        """ "Classic Military Arms" is 180 listings of modern Bula Defense M14
        builds. The Arms Unlimited call, for the fifth time."""
        urls = " ".join(source["url"] for source in AtlanticFirearmsScraper.sources)
        assert "other-cool-firearms" not in urls
        for retail in ("ak-47-74-rifles", "ar15-rifles", "tactical-rifles", "handguns-pistols"):
            assert retail not in urls

    def test_the_parts_kit_section_is_read_despite_its_components(self):
        """38 of its 77 read as kits — Yugo, AK, VZ58, Galil, RPD — and the
        other 39 are bare barrels and AR uppers. Unlike SARCO's 465-item
        "Parts & Kits", the ratio here is close enough to half that the section
        is worth taking and letting the classifier sort."""
        urls = [source["url"] for source in AtlanticFirearmsScraper.sources]
        assert f"{SITE_BASE}parts-kits" in urls


class TestThePace:
    def test_it_keeps_the_gentle_default(self):
        """They are behind Cloudflare and answer plain requests happily; there
        is no measured reason to go slower than the platform default, and no
        429 has been seen from them."""
        assert AtlanticFirearmsScraper.min_request_delay >= 5

    def test_it_scans_daily(self):
        """Unlike Collectors Firearms, whose crawl delay made a pass cost
        hours: 128 listings at five seconds is minutes."""
        assert AtlanticFirearmsScraper.default_interval_minutes == 1440
