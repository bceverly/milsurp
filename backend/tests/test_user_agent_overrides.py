"""A different user agent for particular shops.

Added 2026-10-08 for Old Steel Arsenal, whose server answered the configured
agent with 429 on every catalog request and this application's default agent
with 200. Keyed by host, so it reaches every request to that shop -- and
robots.txt is read for the agent actually sent.
"""

from __future__ import annotations

import dataclasses

import pytest
import responses

from app.config import ConfigError, _user_agent_overrides
from app.scrapers.base import ScrapeContext

DEFAULT = "Default-Agent/1.0"
SHOP_AGENT = "Shop-Agent/2.0"


@pytest.fixture
def configured(app_config):
    return dataclasses.replace(
        app_config,
        scraping=dataclasses.replace(
            app_config.scraping,
            obey_robots=True,
            request_delay=0.0,
            user_agent=DEFAULT,
            user_agent_overrides=(("oldsteel.test", SHOP_AGENT),),
        ),
    )


class TestTheSetting:
    def test_it_is_a_mapping_of_host_to_agent(self):
        assert _user_agent_overrides({"www.OldSteel.test": " Shop-Agent/2.0 "}) == (
            ("oldsteel.test", "Shop-Agent/2.0"),
        )
        assert _user_agent_overrides(None) == ()

    @pytest.mark.parametrize(
        "raw",
        [["oldsteel.test"], {"https://oldsteel.test/": "A"}, {"oldsteel.test": ""}],
    )
    def test_a_url_a_list_or_an_empty_agent_is_refused(self, raw):
        with pytest.raises(ConfigError):
            _user_agent_overrides(raw)

    def test_a_host_covers_its_subdomains_and_nothing_else(self, configured):
        scraping = configured.scraping
        assert scraping.user_agent_for("oldsteel.test") == SHOP_AGENT
        assert scraping.user_agent_for("www.oldsteel.test") == SHOP_AGENT
        assert scraping.user_agent_for("notoldsteel.test") == DEFAULT
        assert scraping.user_agent_for("other.test") == DEFAULT


class TestTheRequestsCarryIt:
    @responses.activate
    def test_the_shop_and_its_robots_get_the_override(self, configured):
        responses.add(responses.GET, "https://oldsteel.test/robots.txt", body="User-agent: *\n")
        responses.add(responses.GET, "https://oldsteel.test/page", body="ok")
        responses.add(responses.GET, "https://other.test/robots.txt", body="User-agent: *\n")
        responses.add(responses.GET, "https://other.test/page", body="ok")
        ctx = ScrapeContext(configured)
        ctx.get("https://oldsteel.test/page")
        ctx.get("https://other.test/page")
        ctx.close()

        sent = {call.request.url: call.request.headers["User-Agent"] for call in responses.calls}
        assert sent["https://oldsteel.test/robots.txt"] == SHOP_AGENT
        assert sent["https://oldsteel.test/page"] == SHOP_AGENT
        assert sent["https://other.test/robots.txt"] == DEFAULT
        assert sent["https://other.test/page"] == DEFAULT

    @responses.activate
    def test_robots_rules_are_read_for_the_agent_sent(self, configured):
        """A file that turns away one agent and admits another is judged by
        the one this request will actually carry."""
        responses.add(
            responses.GET,
            "https://oldsteel.test/robots.txt",
            body="User-agent: Shop-Agent\nAllow: /\n\nUser-agent: *\nDisallow: /\n",
        )
        ctx = ScrapeContext(configured)
        assert ctx.allowed("https://oldsteel.test/catalog")
        ctx.close()
