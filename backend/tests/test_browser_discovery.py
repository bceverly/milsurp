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

    def test_the_driver_matches_the_browser_it_drives(self, monkeypatch):
        """Reported from production, and a real bug in the first version of
        this: the browser and the driver were searched for independently, so a
        machine with the Chromium snap and Ubuntu's /usr/bin/chromedriver got
        the two paired together -- and that shim dies under snap confinement
        with "Service /usr/bin/chromedriver unexpectedly exited. Status code
        was: 46". The canary reported Royal Tiger broken on a machine where
        Chromium works perfectly well.
        """
        present = {"/snap/bin/chromium", "/snap/bin/chromium.chromedriver", "/usr/bin/chromedriver"}
        monkeypatch.setattr(browser.os, "access", lambda path, _mode: path in present)
        binary, driver = browser.find_chrome()
        assert binary == "/snap/bin/chromium"
        assert driver == "/snap/bin/chromium.chromedriver"

    def test_a_browser_with_no_driver_beside_it_still_returns(self, monkeypatch):
        """Selenium Manager can fetch a matching driver, and letting it try is
        better than refusing to start."""
        monkeypatch.setattr(
            browser.os, "access", lambda path, _mode: path == "/usr/bin/google-chrome"
        )
        assert browser.find_chrome() == ("/usr/bin/google-chrome", None)

    def test_every_browser_names_the_drivers_that_can_drive_it(self):
        """A browser missing from the map would silently get no driver at all."""
        assert set(browser._DRIVERS_FOR) == set(browser._CHROME_BINARIES)

    def test_and_nothing_is_reported_as_nothing(self, nothing_installed):
        assert browser.find_chrome() == (None, None)

    def test_every_path_it_tries_is_absolute(self):
        """A bare name would be resolved against PATH, and PATH under a systemd
        unit is not the one an administrator tested with."""
        drivers = [path for paths in browser._DRIVERS_FOR.values() for path in paths]
        for path in (*browser._CHROME_BINARIES, *drivers):
            assert path.startswith("/"), path


class TestWhatTheConfigurationSays:
    def test_it_is_never_second_guessed(self, monkeypatch):
        """An installation naming its own paths has made a decision. Discovery
        only answers where the configuration is silent."""
        import inspect

        source = inspect.getsource(browser.chrome)
        assert "config.chrome_binary or found_binary" in source
        assert "config.chromedriver_path or found_driver" in source
