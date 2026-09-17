"""The timezone names a browser actually sends, resolved on any host.

This is a "worked everywhere we tried it" bug. Debian 12 and Ubuntu 23.04 moved
the backward-compatibility *links* out of `tzdata` and into a separate
`tzdata-legacy` package that nothing installs by default. Every development
machine had it; production did not.

So a browser reporting a legacy alias -- `Intl.DateTimeFormat()` still says
"America/Indianapolis" on some systems rather than
"America/Indiana/Indianapolis" -- produced a zone the server could not resolve,
and saving the digest settings failed with *Unknown timezone
'America/Indianapolis'*. The settings page offers the device's own zone as its
first option, so for that person there was no way to save the page at all.

Fixed by depending on the `tzdata` package, which carries the links whatever
the host's own database does. These tests are the regression: they fail on a
machine without it, which is the machine the bug was reported from.
"""

from __future__ import annotations

import tempfile
import zoneinfo

import pytest

#: Legacy aliases that browsers and operating systems still report. Every one
#: of these is a link in the IANA `backward` file rather than a zone in its own
#: right, and every one of them is what some real system calls itself.
LEGACY_ALIASES = (
    "America/Indianapolis",
    "US/Eastern",
    "US/Central",
    "US/Mountain",
    "US/Pacific",
    "Asia/Calcutta",
    "Europe/Kiev",
)


@pytest.fixture
def without_the_system_database():
    """Make `zoneinfo` behave like a host with no tzdata links at all.

    Pointing TZPATH at an empty directory is the closest thing to reproducing
    the production machine, and it is what makes these tests mean something on
    a developer's laptop -- which has `tzdata-legacy` and would otherwise pass
    for the wrong reason.
    """
    original = zoneinfo.TZPATH
    with tempfile.TemporaryDirectory() as empty:
        zoneinfo.reset_tzpath([empty])
        try:
            yield
        finally:
            zoneinfo.reset_tzpath(original)


@pytest.mark.parametrize("name", LEGACY_ALIASES)
def test_a_legacy_alias_resolves_without_the_system_database(name, without_the_system_database):
    assert zoneinfo.ZoneInfo(name) is not None


def test_the_canonical_name_resolves_too(without_the_system_database):
    assert zoneinfo.ZoneInfo("America/Indiana/Indianapolis") is not None


def test_a_name_that_is_not_a_zone_still_fails(without_the_system_database):
    """The point is to resolve the aliases, not to accept anything. A typo has
    to keep being rejected or the settings page silently stores nonsense."""
    with pytest.raises(zoneinfo.ZoneInfoNotFoundError):
        zoneinfo.ZoneInfo("America/Indianapolis_typo")


class TestTheSettingsPageCanSaveThem:
    """End to end, through the endpoint that produced the error.

    Under the same empty TZPATH as the tests above: without it these pass on
    any developer's machine whatever the fix is, because those machines have
    `tzdata-legacy` and were never the ones that failed.
    """

    @pytest.fixture(autouse=True)
    def _no_system_database(self, without_the_system_database):
        pass

    @pytest.mark.parametrize("name", LEGACY_ALIASES)
    def test_a_legacy_alias_is_accepted(self, client, admin_headers, name):
        response = client.put(
            "/api/preferences/email",
            json={"display_timezone": name},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["display_timezone"] == name

    def test_a_zone_that_does_not_exist_is_still_refused(self, client, admin_headers):
        response = client.put(
            "/api/preferences/email",
            json={"display_timezone": "Mars/Olympus_Mons"},
            headers=admin_headers,
        )
        assert response.status_code == 400
        assert "Unknown timezone" in response.json()["detail"]
