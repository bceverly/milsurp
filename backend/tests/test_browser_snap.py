"""A snap browser under the hardened service unit, and why it cannot work.

Royal Tiger failed on production with *"Service /snap/bin/chromium.chromedriver
unexpectedly exited. Status code was: 46"*. Every path in the message was
right — the snap browser was found, and it was correctly paired with the only
driver that can drive it. The pairing was not the problem.

**A snap is not an ordinary executable.** `snap-confine` builds the sandbox
before the browser starts, and needs privileges it picks up from file
capabilities — `cap_sys_admin` and `cap_sys_chroot` among them.
`NoNewPrivileges=true` is exactly a promise that no executable will ever pick
those up, so it dies on the spot. The unit forbids it twice more:
`RestrictNamespaces=true` denies the mount namespace the sandbox is made of,
and `SystemCallFilter=@system-service` covers neither `mount` nor `pivot_root`.

So the two cannot both be right, and the hardening is the half worth keeping —
a scraper runs a stranger's JavaScript and is the last process on the machine
that should be able to escalate. These tests hold the *diagnosis*, because an
error that sends somebody to tune config.yaml costs an afternoon.
"""

from __future__ import annotations

import pytest

from app.scrapers import browser


class TestSpottingIt:
    def test_a_snap_under_no_new_privileges_cannot_run(self, monkeypatch):
        monkeypatch.setattr(browser, "_no_new_privileges", lambda: True)
        assert browser._snap_cannot_run_here("/snap/bin/chromium") is True

    def test_a_snap_outside_one_is_fine(self, monkeypatch):
        """Which is why it works from a shell, and on every developer's
        machine, and only ever failed as a service."""
        monkeypatch.setattr(browser, "_no_new_privileges", lambda: False)
        assert browser._snap_cannot_run_here("/snap/bin/chromium") is False

    def test_a_packaged_browser_under_one_is_fine(self, monkeypatch):
        """The hardening is not the problem on its own -- Google Chrome's .deb
        runs under all of it."""
        monkeypatch.setattr(browser, "_no_new_privileges", lambda: True)
        assert browser._snap_cannot_run_here("/usr/bin/google-chrome") is False

    def test_no_browser_at_all_is_not_this_problem(self, monkeypatch):
        monkeypatch.setattr(browser, "_no_new_privileges", lambda: True)
        assert browser._snap_cannot_run_here(None) is False


class TestReadingTheFlag:
    def test_it_reads_the_kernel_rather_than_guessing(self, tmp_path, monkeypatch):
        status = tmp_path / "status"
        status.write_text("Name:\tpython\nNoNewPrivs:\t1\n", encoding="ascii")
        monkeypatch.setattr(browser, "Path", lambda _: status)
        assert browser._no_new_privileges() is True

    def test_a_zero_is_a_zero(self, tmp_path, monkeypatch):
        status = tmp_path / "status"
        status.write_text("Name:\tpython\nNoNewPrivs:\t0\n", encoding="ascii")
        monkeypatch.setattr(browser, "Path", lambda _: status)
        assert browser._no_new_privileges() is False

    def test_a_kernel_that_does_not_say_is_not_assumed_to_forbid(self, tmp_path, monkeypatch):
        """False is the safe default: it produces the general message, which
        is merely unhelpful, rather than a confident wrong diagnosis."""
        status = tmp_path / "status"
        status.write_text("Name:\tpython\n", encoding="ascii")
        monkeypatch.setattr(browser, "Path", lambda _: status)
        assert browser._no_new_privileges() is False

    def test_an_unreadable_proc_does_not_raise(self, monkeypatch):
        def explode(_):
            raise OSError("no /proc here")

        monkeypatch.setattr(browser, "Path", explode)
        assert browser._no_new_privileges() is False


class TestWhatItSays:
    """The message is the deliverable. The old one named six paths and two
    config keys, every one of which was already correct."""

    @pytest.fixture
    def snap_failure(self, monkeypatch):
        monkeypatch.setattr(browser, "find_chrome", lambda: ("/snap/bin/chromium", None))
        monkeypatch.setattr(browser, "_no_new_privileges", lambda: True)

        # Selenium is imported inside the function, so the patch goes on the
        # module it comes from rather than on `browser`.
        from selenium import webdriver

        def refuse(*args, **kwargs):
            raise RuntimeError("Status code was: 46")

        monkeypatch.setattr(webdriver, "Chrome", refuse)

        from app.config import get_config

        with (
            pytest.raises(browser.BrowserUnavailable) as caught,
            browser.chrome(get_config().scraping),
        ):
            pass
        return str(caught.value)

    def test_it_names_the_directive_rather_than_the_symptom(self, snap_failure):
        assert "NoNewPrivileges" in snap_failure
        assert "RestrictNamespaces" in snap_failure

    def test_it_says_config_cannot_fix_this(self, snap_failure):
        """The old message's advice -- set chrome_binary and chromedriver_path
        -- is an afternoon wasted here, because both were already right."""
        assert "Nothing in config.yaml can bridge that" in snap_failure

    def test_it_says_what_would_fix_it(self, snap_failure):
        assert "non-snap" in snap_failure
        assert "/usr/bin/google-chrome" in snap_failure

    def test_and_why_not_to_simply_un_harden_the_unit(self, snap_failure):
        assert "JavaScript" in snap_failure


class TestTheSnapShimUnderAnotherName:
    """Ubuntu's `chromium-chromedriver` leaves a shim at /usr/bin/chromedriver
    that hands off to the snap.

    It is a perfectly good driver *for the snap* and can drive nothing else, so
    pairing it with Google Chrome produces a process that exits at once and a
    message blaming the browser. Production hit this twice: first as the snap
    browser, then — after Chrome was installed and a real driver placed at
    /usr/local/bin — as the shim winning the ordering anyway. "Status code was:
    1", a second afternoon.
    """

    def test_a_symlink_into_snap_is_a_snap_driver(self, tmp_path):
        real = tmp_path / "snap" / "chromium.chromedriver"
        real.parent.mkdir()
        real.write_bytes(b"\x7fELF" + b"\0" * 32)
        shim = tmp_path / "chromedriver"
        shim.symlink_to(real)
        # Resolved rather than guessed at: the name says nothing.
        assert browser.is_snap_driver(str(shim)) is (str(real.resolve()).startswith("/snap/"))

    def test_a_wrapper_script_naming_snap_is_a_snap_driver(self, tmp_path):
        shim = tmp_path / "chromedriver"
        shim.write_text('#!/bin/sh\nexec /snap/bin/chromium.chromedriver "$@"\n')
        assert browser.is_snap_driver(str(shim)) is True

    def test_a_real_driver_is_not(self, tmp_path):
        real = tmp_path / "chromedriver"
        real.write_bytes(b"\x7fELF" + b"\0" * 9000)
        assert browser.is_snap_driver(str(real)) is False

    def test_a_script_that_mentions_no_snap_is_not(self, tmp_path):
        wrapper = tmp_path / "chromedriver"
        wrapper.write_text('#!/bin/sh\nexec /opt/chromedriver "$@"\n')
        assert browser.is_snap_driver(str(wrapper)) is False

    def test_something_unreadable_is_taken_at_face_value(self, tmp_path):
        """A false "this is a snap" hides a working driver, which is the worse
        mistake of the two."""
        assert browser.is_snap_driver(str(tmp_path / "not-there")) is False


class TestChoosingTheDriver:
    def test_a_snap_shim_is_skipped_for_a_packaged_browser(self, tmp_path, monkeypatch):
        shim = tmp_path / "shim"
        shim.write_text('#!/bin/sh\nexec /snap/bin/chromium.chromedriver "$@"\n')
        shim.chmod(0o755)
        real = tmp_path / "real"
        real.write_bytes(b"\x7fELF" + b"\0" * 9000)
        real.chmod(0o755)

        chosen = browser._first_usable_driver("/usr/bin/google-chrome", (str(shim), str(real)))
        assert chosen == str(real)

    def test_but_it_is_the_right_driver_for_the_snap(self, tmp_path):
        shim = tmp_path / "shim"
        shim.write_text('#!/bin/sh\nexec /snap/bin/chromium.chromedriver "$@"\n')
        shim.chmod(0o755)
        chosen = browser._first_usable_driver("/snap/bin/chromium", (str(shim),))
        assert chosen == str(shim)

    def test_an_admin_installed_driver_outranks_the_distribution(self):
        """/usr/local/bin is where somebody put something on purpose, and on
        this question a deliberate act outranks whatever apt left behind."""
        for chrome_path in (
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/opt/google/chrome/chrome",
        ):
            order = browser._DRIVERS_FOR[chrome_path]
            assert order.index("/usr/local/bin/chromedriver") < order.index("/usr/bin/chromedriver")

    def test_nothing_usable_returns_nothing(self, tmp_path):
        """Not an error: Selenium Manager can fetch one, and letting it try
        beats refusing to start."""
        assert browser._first_usable_driver("/usr/bin/google-chrome", ()) is None
