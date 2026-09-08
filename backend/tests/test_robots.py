"""robots.txt matching.

Written because the standard library's parser was measured against a real
shop's file and got two things wrong, both towards crawling more than
permitted. Those two cases are the first tests here.
"""

from __future__ import annotations

import pytest

from app.robots import Robots, RobotsCache

UA = "Mozilla/5.0 (X11; Linux x86_64) milsurp-monitor"

#: The shape of the file this module was written against.
SHOP = """
Sitemap: https://shop.test/sitemap_index.xml

User-agent: *
Crawl-delay: 10
Disallow: /wp-content/uploads/wc-logs/
Disallow: /wp-admin/
Disallow: /*?*
Allow: /wp-admin/admin-ajax.php
Disallow: /513-british-bayonets/page/4/
"""


class TestTheCasesTheStandardLibraryGotWrong:
    @pytest.fixture
    def shop(self):
        return Robots.parse(SHOP)

    def test_a_query_string_rule_is_honored(self, shop):
        """ "Disallow: /*?*" is what keeps a monitor out of faceted search."""
        assert shop.allows("/product-category/rifles/", UA)
        assert shop.allows("/product-category/rifles/page/2/", UA)
        assert not shop.allows("/wp-json/wc/store/v1/products?page=2", UA)
        assert shop.allows("/wp-json/wc/store/v1/products", UA)

    def test_the_longest_match_wins_not_the_first(self, shop):
        """Allow beneath Disallow, and more specific, so Allow wins."""
        assert not shop.allows("/wp-admin/", UA)
        assert shop.allows("/wp-admin/admin-ajax.php", UA)

    def test_a_crawl_delay_is_read(self, shop):
        assert shop.crawl_delay(UA) == 10.0


class TestMatching:
    def rules(self, text):
        return Robots.parse(text)

    def test_a_full_url_and_a_bare_path_are_the_same_question(self):
        robots = self.rules("User-agent: *\nDisallow: /private/")
        assert not robots.allows("https://shop.test/private/x", UA)
        assert not robots.allows("/private/x", UA)

    def test_an_end_anchor_matches_only_the_whole_path(self):
        robots = self.rules("User-agent: *\nDisallow: /catalog$")
        assert not robots.allows("/catalog", UA)
        assert robots.allows("/catalog/rifles", UA)

    def test_a_star_matches_any_run(self):
        robots = self.rules("User-agent: *\nDisallow: /*/private/")
        assert not robots.allows("/anything/private/x", UA)
        assert robots.allows("/private/x", UA)

    def test_punctuation_in_a_path_is_literal(self):
        """These files are full of "?" and "&"; none of it is a pattern."""
        robots = self.rules("User-agent: *\nDisallow: /Rifles-C&R-c179758763")
        assert not robots.allows("/Rifles-C&R-c179758763", UA)
        assert robots.allows("/Rifles-CXR-c179758763", UA)

    def test_a_ties_go_to_allow(self):
        robots = self.rules("User-agent: *\nDisallow: /same\nAllow: /same")
        assert robots.allows("/same", UA)

    def test_an_empty_disallow_restricts_nothing(self):
        """ "Disallow:" with nothing after it means "everything is allowed"."""
        robots = self.rules("User-agent: *\nDisallow:")
        assert robots.allows("/anything", UA)

    def test_rules_before_any_user_agent_belong_to_nobody(self):
        assert self.rules("Disallow: /\nUser-agent: *\nAllow: /").allows("/x", UA)

    def test_comments_and_blank_lines_are_ignored(self):
        robots = self.rules("# a note\nUser-agent: *\n\nDisallow: /x  # trailing\n")
        assert not robots.allows("/x", UA)


class TestWhichGroupApplies:
    #: The shape seen on two of the shops: a permissive catch-all, then a list
    #: of named crawlers shut out entirely.
    NAMED = """
    User-agent: *
    Allow: /

    User-agent: GPTBot
    Disallow: /

    User-agent: ClaudeBot
    Disallow: /
    """

    def test_a_named_crawler_gets_its_own_rules(self):
        robots = Robots.parse(self.NAMED)
        assert not robots.allows("/products", "ClaudeBot/1.0")
        assert not robots.allows("/products", "GPTBot")

    def test_everyone_else_gets_the_catch_all(self):
        assert Robots.parse(self.NAMED).allows("/products", UA)

    def test_consecutive_user_agent_lines_share_one_set_of_rules(self):
        robots = Robots.parse("User-agent: a-bot\nUser-agent: b-bot\nDisallow: /x")
        assert not robots.allows("/x", "a-bot")
        assert not robots.allows("/x", "b-bot")
        assert robots.allows("/x", UA)

    def test_the_most_specific_token_wins(self):
        robots = Robots.parse(
            "User-agent: some-bot\nDisallow: /\n\nUser-agent: some-bot/2.0\nAllow: /"
        )
        assert robots.allows("/x", "some-bot/2.0")


class TestFetching:
    class Response:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    def cache(self, response):
        calls = []

        def fetch(url):
            calls.append(url)
            if isinstance(response, Exception):
                raise response
            return response

        return RobotsCache(fetch), calls

    def test_it_asks_the_origin_for_its_rules(self):
        cache, calls = self.cache(self.Response(200, "User-agent: *\nDisallow: /x"))
        robots = cache.for_url("https://shop.test/product-category/rifles/")

        assert calls == ["https://shop.test/robots.txt"]
        assert not robots.allows("/x", UA)

    def test_it_asks_once_per_site(self):
        cache, calls = self.cache(self.Response(200, "User-agent: *\nAllow: /"))
        cache.for_url("https://shop.test/a")
        cache.for_url("https://shop.test/b")
        assert len(calls) == 1

    def test_no_robots_file_restricts_nothing(self):
        cache, _ = self.cache(self.Response(404))
        assert cache.for_url("https://shop.test/a").allows("/anything", UA)

    @pytest.mark.parametrize("status", [401, 403, 500, 503])
    def test_a_site_that_cannot_answer_is_left_alone(self, status):
        """Erring the other way would let a blip switch off every restriction."""
        cache, _ = self.cache(self.Response(status))
        assert not cache.for_url("https://shop.test/a").allows("/anything", UA)

    def test_so_is_one_we_cannot_reach(self):
        cache, _ = self.cache(OSError("connection refused"))
        assert not cache.for_url("https://shop.test/a").allows("/anything", UA)

    def test_an_implausibly_large_file_is_ignored(self):
        cache, _ = self.cache(self.Response(200, "User-agent: *\nDisallow: /\n" + "#" * 600_000))
        assert cache.for_url("https://shop.test/a").allows("/anything", UA)


class TestAFailedFetchIsNotAnAnswer:
    """A dropped connection must not stand as a host's rules for the next hour.

    Both a 403 and a timeout refuse the request, and only one of them is a
    decision. Caching the timeout as though it were cost a whole SARCO scan:
    every section of that catalog is served by one third-party host, so the
    first failed robots.txt fetch denied all six sections, and the run finished
    PARTIAL with zero listings and six warnings reading "robots.txt disallows"
    about a file that had never been read.
    """

    class Response:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    def cache(self, *responses):
        """A fetcher that returns (or raises) each of these in turn."""
        queue = list(responses)
        calls = []

        def fetch(url):
            calls.append(url)
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(answer, Exception):
                raise answer
            return answer

        return RobotsCache(fetch), calls

    def test_the_request_that_provoked_it_is_still_refused(self):
        """Failing closed on the attempt is the safety property, and stays."""
        cache, _ = self.cache(OSError("connection reset"))
        assert not cache.for_url("https://shop.test/a").allows("/anything", UA)

    def test_but_the_next_request_asks_again(self):
        cache, calls = self.cache(
            OSError("connection reset"), self.Response(200, "User-agent: *\nDisallow:\n")
        )
        assert not cache.for_url("https://shop.test/a").allows("/anything", UA)
        assert cache.for_url("https://shop.test/b").allows("/anything", UA)
        assert len(calls) == 2

    def test_a_real_answer_is_still_remembered(self):
        """Only the failure is re-asked; a site that answered is asked once."""
        cache, calls = self.cache(self.Response(403))
        cache.for_url("https://shop.test/a")
        cache.for_url("https://shop.test/b")
        assert len(calls) == 1

    def test_a_server_error_is_an_answer_and_is_remembered(self):
        """A 500 came from the host. A timeout came from nowhere."""
        cache, calls = self.cache(self.Response(503))
        assert not cache.for_url("https://shop.test/a").allows("/x", UA)
        cache.for_url("https://shop.test/b")
        assert len(calls) == 1

    def test_the_two_are_told_apart(self):
        unreachable, _ = self.cache(OSError("no route to host"))
        refused, _ = self.cache(self.Response(403))
        assert unreachable.for_url("https://shop.test/a").reachable is False
        assert refused.for_url("https://shop.test/a").reachable is True
