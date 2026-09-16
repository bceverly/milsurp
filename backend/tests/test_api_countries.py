"""Editing the country rules, and the cache that has to be dropped when you do.

The list was 38 regular expressions in `classify`, so teaching it that
"Ishapore" means India was a code change for a fact about the world the
operator knows and the programmer does not.

**The test that matters most is the invalidation one.** The rules are a
process-wide registry, because they are consulted inside `classify.enrich`
which scrapers call and scrapers have no session. A cache nobody drops is the
failure this shape of code has: the edit saves, the page shows it, and nothing
classifies differently until the process restarts.
"""

from __future__ import annotations

import pytest

from app import sessions
from app.models import Country
from app.services import classify, countries


@pytest.fixture
def signed_in(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-passphrase"},
    )
    assert response.status_code == 200, response.text
    return response


def csrf(response) -> dict[str, str]:
    return {sessions.CSRF_HEADER: response.json()["csrf_token"]}


@pytest.fixture(autouse=True)
def _fresh_registry(restore_classification_rules):
    countries.invalidate()
    yield
    countries.invalidate()


class TestTheSeededList:
    def test_the_migration_filled_it(self, client, admin_headers):
        rows = client.get("/api/countries", headers=admin_headers).json()
        assert len(rows) == 38
        assert {row["name"] for row in rows} >= {"Germany", "Russia", "United States"}

    def test_it_says_what_the_code_said(self):
        """The table's whole promise. Checked here on the cases whose spelling
        is least obvious rather than on the easy ones."""
        assert classify.extract_country("Swedish Mauser m/96") == "Sweden"
        assert classify.extract_country("U.S. Springfield 1903") == "United States"
        assert classify.extract_country("U.S Revolver Company .38") == "United States"
        assert classify.extract_country("Ishapore 2A1 rifle") == "India"

    def test_a_country_its_pattern_never_matched_still_does_not(self):
        """Finland's rule was `\\bFinn(?:ish)?\\b`, which never matched the word
        "Finland". Seeding the name as well moved 38 listings, so the seed
        carries the spellings the code had and no more -- adding "Finland" is
        now an edit somebody makes on purpose."""
        assert classify.extract_country("A gunsmith in Finland sold it") is None
        assert classify.extract_country("Finnish M39") == "Finland"

    def test_only_an_admin_may_read_it(self, client, normal_user):
        assert client.get("/api/countries", headers=normal_user["headers"]).status_code == 403


class TestEditingOne:
    def test_an_alias_takes_effect_at_once(self, client, clean_db, signed_in):
        """The invalidation test. Without the cache drop this passes the
        database check and fails the classifier one."""
        assert classify.extract_country("A gunsmith in Finland sold it") is None

        row = clean_db.query(Country).filter_by(name="Finland").one()
        response = client.patch(
            f"/api/countries/{row.id}",
            json={"aliases": "Finn\nFinnish\nFinland"},
            headers=csrf(signed_in),
        )
        assert response.status_code == 200, response.text
        assert classify.extract_country("A gunsmith in Finland sold it") == "Finland"

    def test_disabling_one_stops_it_matching(self, client, clean_db, signed_in):
        row = clean_db.query(Country).filter_by(name="Sweden").one()
        client.patch(f"/api/countries/{row.id}", json={"enabled": False}, headers=csrf(signed_in))
        assert classify.extract_country("Swedish Mauser m/96") is None

    def test_a_new_rule_can_be_added(self, client, signed_in):
        response = client.post(
            "/api/countries",
            json={"name": "Denmark II", "aliases": "Dansk", "position": 5},
            headers=csrf(signed_in),
        )
        assert response.status_code == 201, response.text
        assert classify.extract_country("Dansk Krag rifle") == "Denmark II"

    def test_a_duplicate_name_is_refused(self, client, signed_in):
        response = client.post("/api/countries", json={"name": "Germany"}, headers=csrf(signed_in))
        assert response.status_code == 409

    def test_position_decides_which_rule_wins(self, client, clean_db, signed_in):
        """ "Czechoslovakian" has to be tried before "Czech" or every one of
        them files under the shorter name."""
        czech = clean_db.query(Country).filter_by(name="Czech Republic").one()
        client.patch(f"/api/countries/{czech.id}", json={"position": 9999}, headers=csrf(signed_in))
        client.post(
            "/api/countries",
            json={"name": "Slovakia", "aliases": "Czechoslovak", "position": 1},
            headers=csrf(signed_in),
        )
        assert classify.extract_country("Czechoslovak vz.24") == "Slovakia"

    def test_a_normal_user_cannot_edit(self, client, clean_db, normal_user):
        row = clean_db.query(Country).filter_by(name="Germany").one()
        response = client.patch(
            f"/api/countries/{row.id}", json={"enabled": False}, headers=normal_user["headers"]
        )
        assert response.status_code == 403


class TestDeletingOne:
    def test_the_rule_goes_and_the_listings_keep_their_country(self, client, clean_db, signed_in):
        """This deletes the rule that assigns a country, not the answer it
        already gave."""
        row = clean_db.query(Country).filter_by(name="Norway").one()
        assert client.delete(f"/api/countries/{row.id}", headers=csrf(signed_in)).status_code == 204
        assert classify.extract_country("Norwegian Krag") is None

    def test_deleting_what_is_not_there(self, client, signed_in):
        assert client.delete("/api/countries/99999", headers=csrf(signed_in)).status_code == 404
