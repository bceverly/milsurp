"""Every vendor's firearm shipping, declared from its own policy page.

A delivered price is only honest if the shipping in it is the shop's own
figure, so declaring it -- or saying why there is none -- is part of adding a
vendor, like the mailing-list signup. Surveyed 2026-09-30: nine of thirty-nine
shops state a firearm charge; the rest calculate it at checkout or say nothing,
and a note says which.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.scrapers import SCRAPER_CLASSES


@pytest.mark.parametrize("scraper", SCRAPER_CLASSES, ids=lambda cls: cls.slug)
class TestEveryVendorDeclaresIt:
    def test_the_scraper_says_what_the_policy_is(self, scraper):
        """On the class, not inherited: a vendor added without anybody reading
        its shipping policy must fail here."""
        assert "shipping_note" in vars(scraper), (
            f"{scraper.__name__} does not declare shipping_note. Read the shop's "
            "shipping policy and declare shipping_long_gun / shipping_handgun where "
            "it states a flat firearm charge, with a note either way."
        )
        assert len(scraper.shipping_note) > 10, scraper.slug

    def test_a_figure_is_a_sane_dollar_amount(self, scraper):
        for value in (scraper.shipping_long_gun, scraper.shipping_handgun):
            assert value is None or 0 <= value <= 200, scraper.slug

    def test_the_source_is_the_vendors_own_page(self, scraper):
        source = scraper.shipping_source
        if source is None:
            return
        host = (urlparse(source).hostname or "").split(".")[-2:]
        assert host == (urlparse(scraper.base_url).hostname or "").split(".")[-2:], scraper.slug
