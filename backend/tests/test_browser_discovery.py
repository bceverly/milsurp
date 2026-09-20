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

from pathlib import Path

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


class TestADriverThatFellBehindItsBrowser:
    """What `sudo apt update && sudo apt upgrade` does to a scraping host.

    Chrome and ChromeDriver ship together and a driver only drives the major
    version it was built for. Chrome updates itself through apt; a driver an
    administrator unpacked into /usr/local/bin by hand does not. So an ordinary
    upgrade leaves the two a version apart and Selenium reports *"session not
    created: Chrome instance exited. Examine ChromeDriver verbose log to
    determine the cause"* -- a sentence that names neither version and sends
    whoever reads it to look at the browser, which is fine.

    The canary reported Royal Tiger broken that way on a machine where Chrome
    works perfectly well.
    """

    @staticmethod
    def _versions(monkeypatch, **by_path):
        """Google Chrome and every driver paired with it are present; each one
        reports the major version named, or refuses to say when it is absent
        from *by_path*."""
        present = (*browser._CHROME_BINARIES, *browser._DRIVERS_FOR["/usr/bin/google-chrome"])
        monkeypatch.setattr(browser.os, "access", lambda path, _mode: path in present)
        monkeypatch.setattr(browser, "major_version", by_path.get)

    def test_a_driver_a_version_behind_is_not_offered(self, monkeypatch):
        self._versions(
            monkeypatch,
            **{
                "/usr/bin/google-chrome": 153,
                "/usr/local/bin/chromedriver": 152,
                "/usr/bin/chromedriver": 152,
            },
        )
        binary, driver = browser.find_chrome()
        assert binary == "/usr/bin/google-chrome"
        # None is not giving up -- it is the condition Selenium Manager repairs.
        assert driver is None

    def test_a_matching_one_is(self, monkeypatch):
        self._versions(
            monkeypatch,
            **{"/usr/bin/google-chrome": 153, "/usr/local/bin/chromedriver": 153},
        )
        assert browser.find_chrome()[1] == "/usr/local/bin/chromedriver"

    def test_a_stale_driver_does_not_hide_a_fresh_one_behind_it(self, monkeypatch):
        """/usr/local/bin is searched first because an administrator put it
        there on purpose. That ordering must not cost the run a driver that
        actually works."""
        self._versions(
            monkeypatch,
            **{
                "/usr/bin/google-chrome": 153,
                "/usr/local/bin/chromedriver": 149,
                "/usr/bin/chromedriver": 153,
            },
        )
        assert browser.find_chrome()[1] == "/usr/bin/chromedriver"

    def test_a_version_nobody_will_state_is_taken_at_face_value(self, monkeypatch):
        """A false mismatch throws away a working driver, which is the worse
        mistake -- the same judgment is_snap_driver makes."""
        self._versions(monkeypatch, **{"/usr/local/bin/chromedriver": 153})
        assert browser.find_chrome()[1] == "/usr/local/bin/chromedriver"

    def test_and_neither_half_alone_decides_it(self, monkeypatch):
        self._versions(monkeypatch, **{"/usr/bin/google-chrome": 153})
        assert browser.find_chrome()[1] == "/usr/local/bin/chromedriver"


class TestReadingAVersion:
    def test_it_reads_what_the_binary_prints(self, tmp_path):
        fake = tmp_path / "chromedriver"
        fake.write_text("#!/bin/sh\necho 'ChromeDriver 153.0.8010.52 (78e5e45)'\n")
        fake.chmod(0o755)
        assert browser.major_version(str(fake)) == 153

    def test_google_chromes_wording_too(self, tmp_path):
        fake = tmp_path / "google-chrome"
        fake.write_text("#!/bin/sh\necho 'Google Chrome 153.0.8010.36 '\n")
        fake.chmod(0o755)
        assert browser.major_version(str(fake)) == 153

    def test_a_binary_that_is_not_there_says_nothing(self, tmp_path):
        assert browser.major_version(str(tmp_path / "nope")) is None

    def test_and_so_does_one_that_answers_with_prose(self, tmp_path):
        fake = tmp_path / "chromedriver"
        fake.write_text("#!/bin/sh\necho 'command not found'\n")
        fake.chmod(0o755)
        assert browser.major_version(str(fake)) is None

    def test_it_is_not_cached(self):
        """The whole point is to notice a change made underneath a running
        process, which is exactly what apt does to a scheduler that has been up
        for a week. A cached answer would be stale precisely when it mattered.
        """
        import inspect

        source = inspect.getsource(browser.major_version)
        assert "cache" in source.lower()  # the reasoning is written down
        assert not hasattr(browser.major_version, "cache_clear")


class TestSomewhereToPutTheDownloadedDriver:
    """Selenium Manager fetching a matching driver is the whole recovery, and
    it needs somewhere writable to keep it. Under the shipped unit almost
    nowhere is: ProtectHome=true hides ~/.cache and ProtectSystem=strict makes
    the rest read-only, so the download would fail on a machine with a working
    browser, network and Selenium -- and the message would blame Chrome.
    """

    @staticmethod
    def _config(app_config, tmp_path):
        from dataclasses import replace

        return replace(app_config.scraping, driver_cache_path=tmp_path / "selenium")

    def test_it_names_a_directory_and_creates_it(self, app_config, tmp_path, monkeypatch):
        monkeypatch.delenv("SE_CACHE_PATH", raising=False)
        config = self._config(app_config, tmp_path)
        browser._let_selenium_manager_cache(config)
        assert browser.os.environ["SE_CACHE_PATH"] == str(tmp_path / "selenium")
        assert (tmp_path / "selenium").is_dir()

    def test_an_administrators_own_choice_is_left_alone(self, app_config, tmp_path, monkeypatch):
        monkeypatch.setenv("SE_CACHE_PATH", "/somewhere/else")
        browser._let_selenium_manager_cache(self._config(app_config, tmp_path))
        assert browser.os.environ["SE_CACHE_PATH"] == "/somewhere/else"

    def test_a_directory_that_cannot_be_made_is_not_fatal(self, app_config, monkeypatch):
        """Without it Selenium Manager falls back to its own default, which is
        where it would have looked anyway."""
        from dataclasses import replace

        monkeypatch.delenv("SE_CACHE_PATH", raising=False)
        config = replace(app_config.scraping, driver_cache_path=Path("/proc/nope/selenium"))
        browser._let_selenium_manager_cache(config)
        assert "SE_CACHE_PATH" not in browser.os.environ
