"""Chrome keeps its sandbox.

The one process here that runs a stranger's JavaScript is the headless browser
reading a shop's page, and it ran with ``--no-sandbox``: the service unit's
``RestrictNamespaces=true`` denied the user namespaces Chrome's sandbox is made
of, and ``NoNewPrivileges`` the setuid helper it falls back on. A browser
exploit on a compromised shop's page would have run as the service account.

The units now allow user, PID and network namespaces and the ``chroot`` call,
and nothing more. Measured on the production VM (2026-10-03) under a
``systemd-run`` copy of the unit: with ``--no-sandbox`` the renderers shared
the service's user and PID namespaces; with the sandbox they ran in their own
(PID 12 and 21 inside) under Chrome's seccomp policy. Without the namespace
change Chrome aborted with "Failed to move to new namespace"; with namespaces
but no ``chroot`` its zygote died.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import ScrapingConfig, load_config
from app.scrapers import browser

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "systemd"


@pytest.fixture
def started(monkeypatch):
    from selenium import webdriver

    seen: dict = {}

    class FakeDriver:
        def __init__(self, options=None, service=None):
            seen["arguments"] = list(options.arguments)

        def set_page_load_timeout(self, _seconds):
            pass

        def quit(self):
            pass

    monkeypatch.setattr(webdriver, "Chrome", FakeDriver)
    return seen


def _config(**overrides) -> ScrapingConfig:
    return ScrapingConfig(
        chrome_binary="/usr/bin/google-chrome",
        chromedriver_path="/usr/local/bin/chromedriver",
        **overrides,
    )


class TestTheSandboxIsOn:
    def test_by_default(self, started):
        with browser.chrome(_config()):
            pass
        assert "--no-sandbox" not in started["arguments"]

    def test_and_off_only_when_configured_off(self, started):
        with browser.chrome(_config(sandbox=False)):
            pass
        assert "--no-sandbox" in started["arguments"]

    def test_the_setting_is_read_from_the_file(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("scraping:\n  selenium:\n    sandbox: false\n")
        assert load_config(path).scraping.sandbox is False
        path.write_text("scraping: {}\n")
        assert load_config(path).scraping.sandbox is True


class TestWhenItCannotStart:
    @pytest.mark.parametrize(
        "message",
        [
            "Failed to move to new namespace: PID namespaces supported, but failed",
            "Zygote process exited prematurely with exit code 1",
            "The setuid sandbox is not running as root",
        ],
    )
    def test_the_error_says_what_the_unit_needs(self, monkeypatch, message):
        from selenium import webdriver

        def explode(**_kwargs):
            raise RuntimeError(message)

        monkeypatch.setattr(webdriver, "Chrome", explode)
        with pytest.raises(browser.BrowserUnavailable) as caught, browser.chrome(_config()):
            pass
        assert "RestrictNamespaces=user pid net" in str(caught.value)
        assert "sandbox: false" in str(caught.value)

    def test_any_other_failure_is_reported_as_before(self, monkeypatch):
        from selenium import webdriver

        def explode(**_kwargs):
            raise RuntimeError("Chrome instance exited")

        monkeypatch.setattr(webdriver, "Chrome", explode)
        with pytest.raises(browser.BrowserUnavailable) as caught, browser.chrome(_config()):
            pass
        assert "RestrictNamespaces" not in str(caught.value)


class TestTheUnitsAllowExactlyThat:
    """The services that run scrapers, and so Chrome, allow its namespaces and
    chroot and nothing wider; the one that never runs Chrome allows none."""

    @staticmethod
    def _setting(unit: str, name: str) -> str:
        found = re.findall(rf"^{name}=(.*)$", (DEPLOY / unit).read_text(), re.MULTILINE)
        assert len(found) == 1, (unit, name, found)
        return found[0].strip()

    @pytest.mark.parametrize("unit", ["milsurp.service", "milsurp-canary.service"])
    def test_the_browser_services(self, unit):
        assert set(self._setting(unit, "RestrictNamespaces").split()) == {"user", "pid", "net"}
        assert self._setting(unit, "SystemCallFilter").split() == ["@system-service", "chroot"]
        assert self._setting(unit, "NoNewPrivileges") == "true"
        assert self._setting(unit, "RestrictSUIDSGID") == "true"

    def test_the_one_that_never_runs_chrome(self):
        assert self._setting("milsurp-prune.service", "RestrictNamespaces") == "true"
        assert self._setting("milsurp-prune.service", "SystemCallFilter") == "@system-service"
