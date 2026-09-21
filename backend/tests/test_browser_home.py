"""Chrome needs somewhere to write, and the service unit gives it nowhere.

Royal Tiger failed for a week with nothing but *"session not created: Chrome
instance exited"* -- a message that names no file and no directory, and that
reads exactly like the version mismatch it was not. The browser and the driver
were the same build, both started fine from a shell, and the scan died in four
tenths of a second.

The service runs as a user whose home is ``/opt/milsurp``, and the unit's
``ProtectSystem=strict`` makes that read-only on purpose: the install
directory is the last thing a scraper should be able to write to. What changed
was Chrome. ``--headless=new`` now builds a "user data directory container"
under ``$HOME`` before it starts, and gives up if it cannot; behind that, the
crash handler wants a database under ``$HOME`` and aborts the whole browser
when it has none. Both land as "Chrome instance exited".

``--user-data-dir`` on its own does not fix it, which is the part worth
remembering -- crashpad reads the environment, not the flag. So the browser
gets a throwaway home per session, and it is removed afterwards: nothing a
scrape's browser writes down is worth keeping.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import ScrapingConfig
from app.scrapers import browser


@pytest.fixture
def config():
    """Both paths pinned, so nothing here depends on the host's browser."""
    return ScrapingConfig(
        chrome_binary="/usr/bin/google-chrome",
        chromedriver_path="/usr/local/bin/chromedriver",
    )


@pytest.fixture
def started(monkeypatch):
    """Capture what Selenium would have been started with, and start nothing."""
    from selenium import webdriver

    seen: dict = {}

    class FakeDriver:
        def __init__(self, options=None, service=None):
            seen["arguments"] = list(options.arguments)
            seen["env"] = dict(service.env or {})
            seen["service"] = service

        def set_page_load_timeout(self, _seconds):
            seen["timeout_set"] = True

        def quit(self):
            seen["quit"] = True

    monkeypatch.setattr(webdriver, "Chrome", FakeDriver)
    return seen


def _flag(arguments: list[str], name: str) -> str:
    """The value of ``--name=value`` among Chrome's arguments."""
    prefix = f"--{name}="
    matched = [arg for arg in arguments if arg.startswith(prefix)]
    assert matched, f"no {prefix} in {arguments}"
    return matched[0][len(prefix) :]


class TestTheBrowserGetsAHomeOfItsOwn:
    def test_every_path_chrome_writes_to_is_redirected(self, config, started):
        """Not just HOME. Crashpad and the profile follow XDG when it is set,
        so leaving one of them pointed at the real account would put a stray
        cache in a directory nobody expects to own one."""
        with browser.chrome(config):
            pass

        home = started["env"]["HOME"]
        assert home != os.environ.get("HOME")
        for name in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
            assert started["env"][name] == home

    def test_the_profile_and_the_dumps_live_inside_it(self, config, started):
        with browser.chrome(config):
            pass

        home = started["env"]["HOME"]
        assert _flag(started["arguments"], "user-data-dir").startswith(home)
        assert _flag(started["arguments"], "crash-dumps-dir").startswith(home)

    def test_the_rest_of_the_environment_is_left_alone(self, config, started):
        """It is the driver's environment, not a replacement for it: Chrome
        still needs PATH to find its own helpers."""
        with browser.chrome(config):
            pass

        assert started["env"].get("PATH") == os.environ.get("PATH")

    def test_and_this_process_keeps_its_own(self, config, started):
        """Scans run on worker threads. Setting HOME on the process would
        reach into whatever else happened to be scraping at the time."""
        before = os.environ.get("HOME")
        with browser.chrome(config):
            pass
        assert os.environ.get("HOME") == before


class TestItIsCleanedUpAfterwards:
    def test_the_scratch_home_is_removed_when_the_scan_ends(self, config, started):
        with browser.chrome(config):
            home = Path(started["env"]["HOME"])
            assert home.exists()
        assert not home.exists()

    def test_and_when_the_browser_never_started(self, config, monkeypatch):
        """The failure path is the one that matters: this is the case that has
        been happening every eight hours for a week, and a directory left
        behind each time is a slow leak in /tmp."""
        from selenium import webdriver

        made: list[str] = []
        real_mkdtemp = browser.tempfile.mkdtemp

        def remember(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            made.append(path)
            return path

        monkeypatch.setattr(browser.tempfile, "mkdtemp", remember)

        def explode(**_kwargs):
            raise RuntimeError("Chrome instance exited")

        monkeypatch.setattr(webdriver, "Chrome", explode)

        with pytest.raises(browser.BrowserUnavailable), browser.chrome(config):
            pass

        assert made and not Path(made[0]).exists()
