"""How the scraper identifies itself, and why a blank line must not win.

Six of the twenty-eight vendors -- ancestryguns, apexgunparts,
centerfiresystems, collectorsfirearms, ima-usa and jgsales -- answer 403 to a
request carrying an empty ``User-Agent``, and jgsales also refuses curl's
default one. That is a fifth of the catalog, and the symptom is not an error:
a scan that fetches nothing looks exactly like a vendor with empty shelves.

An evening went into chasing that once, from a shell where the variable
holding the agent string happened to be unset. ``user_agent:`` written in
config.yaml with nothing after it is the same mistake in a place that is
harder to notice, because YAML reads it as None and ``str(None)`` is the
perfectly plausible-looking ``"None"``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ScrapingConfig, load_config


class TestTheAgentStringIsNeverBlank:
    @pytest.fixture
    def written(self, tmp_path: Path):
        def write(body: str) -> str:
            path = tmp_path / "config.yaml"
            path.write_text(body, encoding="utf-8")
            return load_config(path).scraping.user_agent

        return write

    def test_a_key_with_nothing_after_it_falls_back(self, written):
        """``user_agent:`` and then end of line. YAML says None."""
        assert written("scraping:\n  user_agent:\n") == ScrapingConfig().user_agent

    def test_an_explicitly_empty_string_falls_back(self, written):
        """The exact request those six vendors refuse."""
        assert written('scraping:\n  user_agent: ""\n') == ScrapingConfig().user_agent

    def test_saying_nothing_at_all_falls_back(self, written):
        assert written("scraping: {}\n") == ScrapingConfig().user_agent

    def test_but_a_real_answer_is_still_honored(self, written):
        """The fallback must not swallow a deliberate choice."""
        assert written("scraping:\n  user_agent: MilsurpBot/1.0\n") == "MilsurpBot/1.0"

    def test_the_default_looks_like_a_browser(self):
        """Not a promise about the exact string, which will age. Only that it
        is long enough and shaped enough to get past a WAF, which "None" and
        "" and "python-requests/2.x" are not."""
        agent = ScrapingConfig().user_agent
        assert agent.startswith("Mozilla/5.0")
        assert len(agent) > 40


class TestEveryRequestCarriesIt:
    def test_the_one_session_sets_the_header(self):
        """Source-inspected: scrapers and the photo fetcher share a single
        requests.Session, so there is exactly one place this can be forgotten
        -- and a second place would be found only by a vendor going quiet."""
        import inspect

        from app.scrapers import base

        source = inspect.getsource(base.ScrapeContext.__init__)
        assert '"User-Agent": self.scraping.user_agent' in source
