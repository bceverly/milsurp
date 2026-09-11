"""Narrow, deliberate exceptions to one host's robots.txt.

``obey_robots`` already existed and is all-or-nothing: switching it off turns
every restriction off on every site, which is a far bigger decision than the
one anybody actually wants to make. This is the small version, and the
properties worth pinning are the ones that keep it small:

* it applies to **one host** and **named path prefixes**, never a whole site;
* a **reason is required**, because an exception nobody explained is
  indistinguishable from a mistake a year later;
* every use is **announced once per scan**, through the progress log the
  operator actually reads, and not as a warning -- a deliberate decision is not
  a fault and must not make the site PARTIAL.

Joe Salter is the case it was built for: their robots.txt disallows ``/image``
and every product photograph OpenCart serves lives under it.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.config import ConfigError, RobotsException, _robots_exceptions
from app.robots import Robots

ROBOTS = "User-agent: *\nDisallow: /files\nDisallow: /image\n"

PHOTO = "https://shop.joesalter.com/image/cache/catalog/a-1280x720.jpg"
PAGE = "https://shop.joesalter.com/Some-Product"

EXCEPTION = RobotsException(
    host="shop.joesalter.com",
    prefixes=("/image/",),
    reason="vendor agreed in writing, 2026-09-11",
)


def _context(ctx_factory, app_config, *exceptions, progress=None):
    context = ctx_factory(
        config=dataclasses.replace(
            app_config,
            scraping=dataclasses.replace(
                app_config.scraping, obey_robots=True, robots_exceptions=exceptions
            ),
        ),
        progress=progress,
    )
    context.robots.for_url = lambda _url: Robots.parse(ROBOTS)  # type: ignore[method-assign]
    return context


class TestWithoutOne:
    def test_the_photograph_is_refused(self, ctx_factory, app_config):
        assert _context(ctx_factory, app_config).allowed(PHOTO) is False

    def test_and_the_product_page_was_never_in_question(self, ctx_factory, app_config):
        assert _context(ctx_factory, app_config).allowed(PAGE) is True


class TestWithOne:
    def test_the_photograph_is_permitted(self, ctx_factory, app_config):
        assert _context(ctx_factory, app_config, EXCEPTION).allowed(PHOTO) is True

    def test_a_path_it_does_not_name_is_still_refused(self, ctx_factory, app_config):
        """``/files`` is disallowed too and this exception says nothing about
        it. An exception that quietly widened to the rest of the file would not
        be a narrow one."""
        context = _context(ctx_factory, app_config, EXCEPTION)
        assert context.allowed("https://shop.joesalter.com/files/catalog.pdf") is False

    def test_another_host_is_not_covered(self, ctx_factory, app_config):
        """The host is matched exactly, with no wildcards: an exception that
        can spread to hosts nobody listed is not narrow either."""
        context = _context(ctx_factory, app_config, EXCEPTION)
        assert context.allowed("https://elsewhere.test/image/a.jpg") is False


class TestItSaysSo:
    def test_the_reason_reaches_the_scan_log(self, ctx_factory, app_config):
        """Where the operator reads it, not only a file on the server."""
        said: list[str] = []
        context = _context(ctx_factory, app_config, EXCEPTION, progress=said.append)
        context.allowed(PHOTO)
        assert any("vendor agreed in writing" in line for line in said)

    def test_once_per_scan_and_not_once_per_photograph(self, ctx_factory, app_config):
        """A gun with 32 pictures would otherwise say it 32 times."""
        said: list[str] = []
        context = _context(ctx_factory, app_config, EXCEPTION, progress=said.append)
        for index in range(32):
            context.allowed(f"https://shop.joesalter.com/image/cache/catalog/{index}.jpg")
        assert len([line for line in said if "exception" in line]) == 1

    def test_it_is_not_a_warning(self, ctx_factory, app_config):
        """A warning makes the site PARTIAL. Doing what somebody configured on
        purpose is not a fault."""
        context = _context(ctx_factory, app_config, EXCEPTION)
        context.allowed(PHOTO)
        assert context.warnings == []


class TestWhatTheConfigFileWillAccept:
    def test_a_complete_entry(self):
        found = _robots_exceptions(
            [{"host": "a.test", "prefixes": ["/image/"], "reason": "because"}]
        )
        assert found == (RobotsException(host="a.test", prefixes=("/image/",), reason="because"),)

    def test_nothing_configured_is_the_normal_case(self):
        assert _robots_exceptions(None) == ()

    def test_a_missing_reason_is_refused(self):
        """The whole design rests on this one."""
        with pytest.raises(ConfigError, match="reason is required"):
            _robots_exceptions([{"host": "a.test", "prefixes": ["/image/"]}])

    def test_the_whole_site_is_refused(self):
        """ "/" is obey_robots: false wearing a disguise, and one that would not
        be obvious in a review."""
        with pytest.raises(ConfigError, match="may not be"):
            _robots_exceptions([{"host": "a.test", "prefixes": ["/"], "reason": "r"}])

    def test_no_prefixes_is_refused(self):
        with pytest.raises(ConfigError, match="non-empty"):
            _robots_exceptions([{"host": "a.test", "prefixes": [], "reason": "r"}])

    def test_a_relative_prefix_is_refused(self):
        with pytest.raises(ConfigError, match="must start with"):
            _robots_exceptions([{"host": "a.test", "prefixes": ["image/"], "reason": "r"}])

    def test_a_host_with_a_path_in_it_is_refused(self):
        with pytest.raises(ConfigError, match="bare hostname"):
            _robots_exceptions([{"host": "a.test/image", "prefixes": ["/i/"], "reason": "r"}])
