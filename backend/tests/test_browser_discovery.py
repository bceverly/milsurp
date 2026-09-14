"""Finding a browser Selenium will not look for on its own.

`apt install chromium-browser` on Ubuntu reports success, installs a working
browser, and leaves Selenium reporting "Unable to obtain driver for chrome" --
because the deb is a transitional shim for a *snap*, and the real binary is
/snap/bin/chromium. Selenium Manager tries "chrome" and "google-chrome", and
neither name exists on the machine.

That message sends whoever reads it to reinstall the thing they already have,
which is what happened on the production VM the first night the canary ran.
"""

from __future__ import annotations

import pytest

from app.scrapers import browser


@pytest.fixture
def nothing_installed(monkeypatch):
    monkeypatch.setattr(browser.os, "access", lambda _path, _mode: False)


class TestWhereItLooks:
    def test_a_real_google_chrome_wins(self, monkeypatch):
        """Preferred over Chromium where both are present: it is the browser
        the vendors' bot protection is least surprised by."""
        monkeypatch.setattr(
            browser.os, "access", lambda path, _mode: path in browser._CHROME_BINARIES
        )
        found, _driver = browser.find_chrome()
        assert found == "/usr/bin/google-chrome"

    def test_the_snap_is_found_when_it_is_all_there_is(self, monkeypatch):
        monkeypatch.setattr(browser.os, "access", lambda path, _mode: path.startswith("/snap/"))
        assert browser.find_chrome() == ("/snap/bin/chromium", "/snap/bin/chromium.chromedriver")

    def test_and_nothing_is_reported_as_nothing(self, nothing_installed):
        assert browser.find_chrome() == (None, None)

    def test_every_path_it_tries_is_absolute(self):
        """A bare name would be resolved against PATH, and PATH under a systemd
        unit is not the one an administrator tested with."""
        for path in (*browser._CHROME_BINARIES, *browser._CHROMEDRIVERS):
            assert path.startswith("/"), path


class TestWhatTheConfigurationSays:
    def test_it_is_never_second_guessed(self, monkeypatch):
        """An installation naming its own paths has made a decision. Discovery
        only answers where the configuration is silent."""
        import inspect

        source = inspect.getsource(browser.chrome)
        assert "config.chrome_binary or found_binary" in source
        assert "config.chromedriver_path or found_driver" in source
