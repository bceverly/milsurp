"""What this application calls itself when it asks a vendor for a page.

Checkpoint Charlie's refused every uncached request for nine days and it was
never a rate limit. They sit behind Hostinger's CDN, and the CDN was refusing
one exact string: `X11; Linux x86_64` together with `Chrome/124.0.0.0` — the
stock user agent of headless scraping tooling. The refusal arrived on the first
request, with an empty body and none of the origin's headers, so nothing ever
reached their server; the same URL answered 200 from the CDN cache and 429 the
moment it missed, which is what made it look like pace for so long.

Either half alone was fine. Linux with a current Chrome passed; Windows with
Chrome 124 passed. That is how specific the match was, and it is why this file
exists: the failure was invisible, lasted more than a week, and came from a
single string nobody had looked at.

So the rule now is to **say what we are**. It is honest, it cannot go stale the
way a pinned browser version does, and it gives a vendor something to allow or
refuse deliberately and an address to complain to.
"""

from __future__ import annotations

import re

import pytest

from app.config import ScrapingConfig

#: The pair Hostinger's edge refuses, and any close relative of it.
BLOCKED_PLATFORM = "X11; Linux x86_64"
BLOCKED_CHROME = "Chrome/124."


@pytest.fixture
def agent() -> str:
    return ScrapingConfig().user_agent


class TestItDoesNotClaimToBeTheBlockedBrowser:
    def test_not_the_exact_pair_that_was_refused(self, agent):
        assert not (BLOCKED_PLATFORM in agent and BLOCKED_CHROME in agent)

    def test_it_does_not_pin_a_browser_version_at_all(self, agent):
        """A version number is a thing that goes stale. Claiming Chrome 124 was
        still claiming it two years later, which is exactly what made it a
        recognizable signature rather than a disguise."""
        assert not re.search(r"Chrome/\d+", agent)
        assert not re.search(r"Firefox/\d+", agent)
        assert not re.search(r"Safari/\d+", agent)


class TestItSaysWhatItIs:
    def test_it_names_this_application(self, agent):
        assert "MilsurpMonitor" in agent

    def test_it_carries_somewhere_to_complain(self, agent):
        """A vendor who wants this to stop should not have to guess who to ask.
        RFC-style bot etiquette, and the reason an honest agent is worth more
        than a convincing one."""
        assert "+http" in agent

    def test_it_is_a_single_well_formed_header_line(self, agent):
        assert agent.strip() == agent
        assert "\n" not in agent and "\r" not in agent
        assert agent.isascii()


class TestTheSampleAgrees:
    def test_the_shipped_config_does_not_reintroduce_it(self):
        """The default in the code is only half the story: config.yaml.sample
        sets the value explicitly, so an installation copying it would get
        whatever that line says regardless of the dataclass."""
        import pathlib

        sample = pathlib.Path(__file__).resolve().parents[2] / "config.yaml.sample"
        line = next(
            row
            for row in sample.read_text(encoding="utf-8").splitlines()
            if row.strip().startswith("user_agent:")
        )
        assert BLOCKED_CHROME not in line
        assert "MilsurpMonitor" in line
