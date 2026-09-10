"""The "coming soon" list, and the ways it can quietly become a lie.

Two lists describe the same vendors from opposite ends -- the scraper registry
says what can be read, `scrapers/planned.py` says what cannot yet -- and a
promise on the Sites page is only worth showing while both agree.
"""

from __future__ import annotations

import pytest

from app.scrapers import get_scraper, iter_scrapers
from app.scrapers.planned import PLANNED


class TestTheListItself:
    def test_every_field_is_filled_in(self):
        """A blank blocker is the failure mode this list exists to avoid: a
        card that promises a vendor and says nothing about what is in the way
        is a wish, and the roadmap already holds plenty of those."""
        for site in PLANNED:
            assert site.slug and site.name and site.base_url
            assert site.platform, site.slug
            assert len(site.blocker) > 30, site.slug

    def test_the_slugs_are_unique(self):
        slugs = [site.slug for site in PLANNED]
        assert len(slugs) == len(set(slugs))

    def test_the_slugs_are_shaped_like_the_registry_s(self):
        """Because one of these becoming a scraper should be a rename of
        nothing: the slug it is promised under is the slug it ships under."""
        for site in PLANNED:
            assert site.slug == site.slug.lower()
            assert site.slug.replace("-", "").isalnum(), site.slug

    def test_every_url_is_absolute_and_https(self):
        for site in PLANNED:
            assert site.base_url.startswith("https://"), site.slug


class TestItCannotContradictTheRegistry:
    """The failure this file is really for.

    A vendor that ships stays on the "coming soon" list until somebody
    remembers to take it off, and nothing about shipping one would otherwise
    fail. That is a stale promise on a page an operator is reading to find out
    what this application does.
    """

    @pytest.mark.parametrize("site", PLANNED, ids=lambda s: s.slug)
    def test_a_planned_vendor_has_no_scraper(self, site):
        assert get_scraper(site.slug) is None, (
            f"{site.name} has a scraper now -- remove it from scrapers/planned.py, "
            f"and add it to the Shipped table in ROADMAP.md"
        )

    @pytest.mark.parametrize("site", PLANNED, ids=lambda s: s.slug)
    def test_nor_a_name_the_registry_already_claims(self, site):
        """Slugs are the identity, but a slug can be spelled two ways for one
        shop. The names are what an operator reads, and two cards for one
        vendor -- one working, one "coming soon" -- is the visible symptom."""
        shipped = {scraper.name.lower() for scraper in iter_scrapers()}
        assert site.name.lower() not in shipped

    @pytest.mark.parametrize("site", PLANNED, ids=lambda s: s.slug)
    def test_nor_a_base_url_it_already_reads(self, site):
        def host(url: str) -> str:
            return url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")

        shipped = {host(scraper.base_url) for scraper in iter_scrapers()}
        assert host(site.base_url) not in shipped


class TestTheEndpoint:
    def test_it_lists_them(self, client, admin_headers):
        response = client.get("/api/sites/planned", headers=admin_headers)
        assert response.status_code == 200
        assert [row["slug"] for row in response.json()] == [s.slug for s in PLANNED]

    def test_planned_is_not_read_as_a_site_id(self, client, admin_headers):
        """The route has to be declared before `/{site_id}` or FastAPI tries to
        parse "planned" as an integer and answers 422."""
        assert client.get("/api/sites/planned", headers=admin_headers).status_code != 422

    def test_any_signed_in_user_can_see_it(self, client, normal_user):
        assert client.get("/api/sites/planned", headers=normal_user["headers"]).status_code == 200

    def test_a_stranger_cannot(self, client):
        assert client.get("/api/sites/planned").status_code == 401
