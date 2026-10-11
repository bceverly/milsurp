"""What this application calls itself when it asks a vendor for a page.

Checkpoint Charlie's refused every uncached request for nine days and it was
never a rate limit. They sit behind Hostinger's CDN, and the CDN was refusing
one exact string: `X11; Linux x86_64` together with `Chrome/124.0.0.0` — the
stock user agent of headless scraping tooling. The refusal arrived on the first
request, with an empty body and none of the origin's headers, so nothing ever
reached their server; the same URL answered 200 from the CDN cache and 429 the
moment it missed, which is what made it look like pace for so long.

Either half alone was fine. Linux with a current Chrome passed; Windows with
Chrome 124 passed. That is how specific the match was.

The default became the application's own name for a while, and production kept
the Linux string in its config anyway, which refused Checkpoint Charlie's again
from 2026-10-06. Since 2026-10-11 the default -- and production -- is current
Chrome on Windows, checked from the production VM against that shop. These
tests hold the shape of it: a Windows desktop Chrome, never the blocked pair,
and a version recent enough not to be a signature of its own.
"""

from __future__ import annotations

import re

import pytest

from app.config import ScrapingConfig

BLOCKED_PLATFORM = "X11; Linux x86_64"
BLOCKED_CHROME = "Chrome/124."
#: The oldest Chrome the default may claim. Raise it with the default: an agent
#: still claiming a two-year-old browser is how the blocked string became one.
OLDEST_CHROME = 150


@pytest.fixture
def agent() -> str:
    return ScrapingConfig().user_agent


class TestItDoesNotClaimToBeTheBlockedBrowser:
    def test_not_the_exact_pair_that_was_refused(self, agent):
        assert not (BLOCKED_PLATFORM in agent and BLOCKED_CHROME in agent)

    def test_not_linux_at_all(self, agent):
        """Linux with a current Chrome passed, but Linux is where headless
        tooling runs; a desktop platform is the less remarkable claim."""
        assert "Linux" not in agent


class TestItIsADesktopChromeOnWindows:
    def test_windows(self, agent):
        assert "Windows NT 10.0; Win64; x64" in agent

    def test_a_current_chrome(self, agent):
        found = re.search(r"Chrome/(\d+)\.", agent)
        assert found, agent
        assert int(found.group(1)) >= OLDEST_CHROME

    def test_the_whole_shape_a_browser_sends(self, agent):
        assert agent.startswith("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        assert agent.endswith("Safari/537.36")


class TestTheSampleConfigSaysTheSame:
    def test_a_new_installation_starts_with_the_default(self):
        """The installer copies config.yaml.sample into place, so a fresh
        install's agent is whatever the sample says -- which has to agree with
        the default, or a new deployment quietly starts out blocked."""
        from pathlib import Path

        import yaml

        sample = Path(__file__).resolve().parents[2] / "config.yaml.sample"
        stated = yaml.safe_load(sample.read_text(encoding="utf-8"))["scraping"]["user_agent"]
        assert stated == ScrapingConfig().user_agent
