"""Nickerson Military: one hand-kept price list, read line by line.

Markup below is the shop's, trimmed, from September 2026.
"""

from __future__ import annotations

from app.scrapers import get_scraper
from app.scrapers.nickerson_military import (
    PAGE,
    NickersonMilitaryScraper,
    heading,
    key_for,
    parse_page,
)

LIST = """<html><body><article><div class="entry-content">
<p> </p>
<p>UPDATED 09/18/2026</p>
<p><strong>WORLD WAR I HANDGUNS</strong></p>
<p>Colt 1911 2nd Year of Production 1913 Mfg. $3,500</p>
<p><strong>SPANISH-AMERICAN WAR / WORLD WAR I RIFLES</strong></p>
<p>Springfield Armory Model 1898 Krag Rifle with Sling $1200</p>
<p><strong>WWII PISTOLS</strong></p>
<p>Enfield No. 2 Revolver $450</p>
<p><strong>POST WWII RIFLES</strong></p>
<p>Yugo M48 8mm Mauser MATCHING $550</p>
<p>Yugo M48 8mm Mauser MATCHING $575</p>
<p>Daisy Model 853 Single Shot Target Air Rifle U.S. Property Marked $200</p>
<p>Call for details on the rest</p>
<p> </p>
</div></article></body></html>"""


class _Ctx:
    """Just enough of a ScrapeContext for a one-page scraper."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.lines: list[str] = []

    def get_text(self, url: str) -> str:
        return self.pages[url]

    def log(self, message: str) -> None:
        self.lines.append(message)


class TestThePage:
    def test_each_priced_line_under_its_heading(self):
        lines, updated = parse_page(LIST)
        assert updated == "09/18/2026"
        assert lines[0] == (
            "Colt 1911 2nd Year of Production 1913 Mfg.",
            3500.0,
            "World War I Handguns",
        )
        assert lines[1][1] == 1200.0  # "$1200", no comma
        assert [section for _t, _p, section in lines[2:4]] == ["WWII Pistols", "Post WWII Rifles"]

    def test_lines_without_a_price_are_not_listings(self):
        lines, _updated = parse_page(LIST)
        assert all("Call for details" not in title for title, _p, _s in lines)

    def test_headings_keep_their_numerals(self):
        assert heading("SPANISH-AMERICAN WAR / WORLD WAR I RIFLES") == (
            "Spanish-American War / World War I Rifles"
        )


class TestTheListings:
    def _scrape(self):
        ctx = _Ctx({PAGE: LIST})
        return list(NickersonMilitaryScraper().scrape(ctx)), ctx  # type: ignore[arg-type]

    def test_the_air_rifle_is_left_out(self):
        items, ctx = self._scrape()
        assert not any("Air Rifle" in item.title for item in items)
        assert "1 air gun(s) left out" in ctx.lines[-1]

    def test_a_repeated_line_gets_its_own_key(self):
        items, _ctx = self._scrape()
        keys = [item.external_key for item in items if item.title.startswith("Yugo M48")]
        assert keys == ["yugo-m48-8mm-mauser-matching", "yugo-m48-8mm-mauser-matching-2"]

    def test_every_listing_points_at_the_page(self):
        items, _ctx = self._scrape()
        assert {item.url for item in items} == {PAGE}
        assert all(item.price for item in items)

    def test_the_key_is_the_title(self):
        assert key_for("British No. 4 Mk. 1 (T)") == "british-no-4-mk-1-t"


def test_it_is_registered():
    scraper = get_scraper("nickerson-military")
    assert isinstance(scraper, NickersonMilitaryScraper)
    assert scraper.newsletter_url is None and scraper.newsletter_note
