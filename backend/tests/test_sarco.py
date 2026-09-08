"""SARCO, Inc. -- the shop's own settings.

The walk itself is covered by test_searchanise.py. These pin the four facts
about SARCO that a live measurement established and that nothing in the code
would notice going stale.
"""

from __future__ import annotations

import pytest

from app.scrapers import SCRAPER_CLASSES, get_scraper
from app.scrapers.sarco import SITE_BASE, SarcoScraper
from app.scrapers.searchanise import SearchaniseScraper


class TestItIsRegistered:
    def test_the_registry_knows_it(self):
        assert isinstance(get_scraper("sarco"), SarcoScraper)

    def test_and_lists_it(self):
        assert SarcoScraper in SCRAPER_CLASSES

    def test_it_is_a_searchanise_shop(self):
        assert issubclass(SarcoScraper, SearchaniseScraper)

    def test_no_browser_is_needed(self):
        """The roadmap had this filed under "needs a browser" on the evidence
        of an empty catalog page. The page is empty; the site is not."""
        assert SarcoScraper.requires_browser is False


class TestTheCategoryNamesCarryNoPipe:
    """Searchanise splits ``restrictBy[categories]`` on ``|``, so SARCO's own
    "Rifles | Military Surplus Guns" category returns *zero* items when asked
    for by name -- 200, an empty list, no error at all. A future section added
    by copying a name out of the site's menu would fail exactly that quietly.
    """

    @pytest.mark.parametrize("source", SarcoScraper.sources)
    def test_a_section_name_has_no_pipe_in_it(self, source):
        assert "|" not in source["category"]

    def test_the_parent_category_is_the_catch_all(self):
        """It is only needed for the rifles, which live in the one category
        that cannot be asked for by name. Everything else has a section that
        says what it is."""
        assert SarcoScraper.sources[2]["category"] == "Shop All Firearms"


class TestTheSectionOrderIsTheClassification:
    """A listing is taken by the first section that offers it, and that
    section's name becomes the ``category`` the classifier trusts over its own
    reading of the title. Measured on SARCO's 283 pistols: under the parent
    "Shop All Firearms", 200 read as handguns, 77 as nothing and 6 as rifles.
    Under "Pistols", 281 of 283 read as handguns.
    """

    def test_the_specific_sections_come_first(self):
        assert [source["category"] for source in SarcoScraper.sources[:2]] == [
            "Pistols",
            "Shotgun",
        ]

    def test_the_catch_all_comes_after_them(self):
        names = [source["category"] for source in SarcoScraper.sources]
        assert names.index("Shop All Firearms") > names.index("Pistols")

    def test_new_arrivals_come_last(self):
        """Not quite a subset -- three of its 73 were not yet in the parent
        when this was measured -- but type-neutral, like the parent."""
        assert SarcoScraper.sources[-1]["category"] == "Exciting New Firearms"

    def test_the_shotgun_section_is_relabeled(self):
        """SARCO's is singular; a listing should not be filed under "Shotgun"."""
        assert SarcoScraper.sources[1]["label"] == "Shotguns"


class TestComponentsAreSkipped:
    """SARCO files bare frames and stripped receivers under firearms, and
    legally that is right -- the receiver is the serialized part. For this
    application they are components, and the standing rule is that the only
    non-firearm category worth ingesting is a parts *kit*. 83 listings.
    """

    def test_both_component_sections_are_excluded(self):
        assert set(SarcoScraper.exclude_categories) == {"Frames", "Actions & Receivers"}

    def test_an_excluded_section_is_not_also_a_source(self):
        """Suppression, not relabeling: fifteen of the fifty frames are also
        filed under "Pistols" and would otherwise be claimed by it first."""
        wanted = {source["category"] for source in SarcoScraper.sources}
        assert wanted.isdisjoint(SarcoScraper.exclude_categories)


class TestTheCanonicalHost:
    """Every link in the feed is bare ``sarcoinc.com`` and every one 301s to
    ``www``. Left alone that is a wasted redirect on each product page and a
    stored link that does not match the site's own.
    """

    def test_a_bare_link_is_canonicalized(self):
        assert (
            SarcoScraper().product_url("https://sarcoinc.com/hakim-receiver-new/")
            == f"{SITE_BASE}hakim-receiver-new/"
        )

    def test_one_that_is_already_canonical_is_left_alone(self):
        url = f"{SITE_BASE}hakim-receiver-new/"
        assert SarcoScraper().product_url(url) == url

    def test_only_the_host_is_rewritten(self):
        """A path that happens to contain the bare host is not a host."""
        url = "https://sarcoinc.com/a/https://sarcoinc.com/"
        assert SarcoScraper().product_url(url) == f"{SITE_BASE}a/https://sarcoinc.com/"


class TestTheDescriptionIsFetched:
    """The API stops at 200 characters -- 508 of the 509 firearms come back cut
    off mid-sentence -- and the description is the half of a listing this
    application reads most closely.
    """

    def test_the_product_page_is_read_for_it(self):
        assert SarcoScraper.detail_description_selectors

    def test_the_tab_body_is_preferred_to_the_wrapper(self):
        """`.productView-description` opens with the literal word "Description"
        from the tab label above it, so the narrower selector goes first."""
        assert SarcoScraper.detail_description_selectors[0] == "#tab-description"

    def test_the_api_key_is_the_one_the_storefront_publishes(self):
        assert SarcoScraper.api_key == "7I8v4I9z4m"
