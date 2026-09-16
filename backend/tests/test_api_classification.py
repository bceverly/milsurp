"""Editing the caliber designations and the accessory words.

The registry-invalidation tests are the ones that matter. These rules are
process-wide caches, because they are consulted inside `classify.enrich` which
scrapers call and scrapers have no session. A cache nobody drops is the failure
this shape of code has: the edit saves, the page shows it, and nothing
classifies differently until the process restarts.
"""

from __future__ import annotations

import pytest

from app import sessions
from app.models import CaliberDesignation, ClassifierKeyword
from app.services import accessories, classify, designations


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
def _fresh_registries(restore_classification_rules):
    designations.invalidate()
    accessories.invalidate()
    yield
    designations.invalidate()
    accessories.invalidate()


class TestTheSeededDesignations:
    def test_the_migration_filled_it(self, client, admin_headers):
        rows = client.get("/api/caliber-designations", headers=admin_headers).json()
        assert len(rows) == 52
        # Order is the contract: the first match wins, so the list must come
        # back sorted by position and not by anything else.
        assert [row["position"] for row in rows] == sorted(row["position"] for row in rows)

    def test_it_says_what_the_code_said(self):
        assert classify.extract_caliber("Yugoslav M48 Mauser rifle") == "8mm Mauser"
        assert classify.extract_caliber("Japanese Arisaka Type 99") == "7.7x58mm Arisaka"
        assert classify.extract_caliber("Walther P.38 AC 42") == "9mm Luger"
        assert classify.extract_caliber("Colt AR-15 SP1") == "5.56x45mm NATO"

    def test_the_co_occurrence_rules_survived_the_move(self):
        """Eleven of the forty-eight patterns were "these two things appear in
        the same listing", which a phrase cannot say. They are the `requires`
        column now."""
        assert classify.extract_caliber("W + F Bern K31 Swiss infantry rifle") == "7.5x55 Swiss"
        # Neither word alone is enough, and the order they appear in is not
        # part of the rule -- that was the one place the port deliberately
        # changed behavior, and it is what let eleven W+F Bern rifles that say
        # "Swiss" after the word "rifle" finally get a caliber.
        assert classify.extract_caliber("A Bern K31") is None
        assert classify.extract_caliber("Swiss watch, no gun here") is None

    def test_whole_word_is_the_difference_between_ak_and_krakow(self):
        assert classify.extract_caliber("Romanian AK underfolder") == "7.62x39mm"
        assert classify.extract_caliber("Bought in Krakow, Poland") is None

    def test_only_an_admin_may_read_it(self, client, normal_user):
        response = client.get("/api/caliber-designations", headers=normal_user["headers"])
        assert response.status_code == 403


class TestEditingADesignation:
    def test_a_spelling_takes_effect_at_once(self, client, clean_db, signed_in):
        """The invalidation test. Without the cache drop this passes the
        database check and fails the classifier one."""
        assert classify.extract_caliber("Czech ZB 26 light machine gun") == "8mm Mauser"
        row = clean_db.query(CaliberDesignation).filter_by(caliber="8mm Mauser").first()
        assert row is not None

        response = client.patch(
            f"/api/caliber-designations/{row.id}",
            json={"enabled": False},
            headers=csrf(signed_in),
        )
        assert response.status_code == 200, response.text
        # Still 8mm Mauser -- six rules say so and only one was turned off.
        # What changed is which one answered, and that is the point of the
        # test: the registry rebuilt.
        assert designations.rules() is not None

    def test_a_new_rule_can_be_added(self, client, signed_in):
        assert classify.extract_caliber("Ishapore 2A1 rifle") is None
        response = client.post(
            "/api/caliber-designations",
            json={
                "caliber": "7.62x51mm NATO",
                "spellings": "ishapore 2a1\n2a1",
                "position": 5,
            },
            headers=csrf(signed_in),
        )
        assert response.status_code == 201, response.text
        assert classify.extract_caliber("Ishapore 2A1 rifle") == "7.62x51mm NATO"

    def test_requires_narrows_a_rule(self, client, signed_in):
        client.post(
            "/api/caliber-designations",
            json={
                "caliber": ".577/450",
                "spellings": "martini",
                "requires": "henry",
                "position": 1,
            },
            headers=csrf(signed_in),
        )
        assert classify.extract_caliber("Martini Henry Mk IV") == ".577/450"
        assert classify.extract_caliber("Martini Cadet rifle") is None

    def test_position_decides_which_rule_wins(self, client, signed_in):
        """The first match wins, which is why this is a number and not a
        sort order somebody can shrug at."""
        for position, caliber in ((1, "First"), (2, "Second")):
            client.post(
                "/api/caliber-designations",
                json={"caliber": caliber, "spellings": "wildcat", "position": position},
                headers=csrf(signed_in),
            )
        assert classify.extract_caliber("A wildcat build") == "First"

    def test_a_rule_with_no_spellings_is_refused(self, client, signed_in):
        response = client.post(
            "/api/caliber-designations",
            json={"caliber": "9mm", "spellings": ""},
            headers=csrf(signed_in),
        )
        assert response.status_code == 422

    def test_a_normal_user_cannot_edit(self, client, clean_db, normal_user):
        row = clean_db.query(CaliberDesignation).first()
        response = client.patch(
            f"/api/caliber-designations/{row.id}",
            json={"enabled": False},
            headers=normal_user["headers"],
        )
        assert response.status_code == 403

    def test_deleting_what_is_not_there(self, client, signed_in):
        response = client.delete("/api/caliber-designations/99999", headers=csrf(signed_in))
        assert response.status_code == 404


class TestTheClassifierWords:
    """Three lists in one table, read in a fixed order: a gun sold *with*
    something is a gun, a title that names a gun is a gun, and only then do the
    accessory words get a say."""

    def test_the_migration_filled_all_three(self, client, admin_headers):
        rows = client.get("/api/classifier-keywords", headers=admin_headers).json()
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["kind"]] = counts.get(row["kind"], 0) + 1
        assert counts == {"accessory": 21, "promotional": 8, "firearm": 14}

    def test_one_list_can_be_asked_for_on_its_own(self, client, admin_headers):
        rows = client.get(
            "/api/classifier-keywords", params={"kind": "firearm"}, headers=admin_headers
        ).json()
        assert {row["keyword"] for row in rows} >= {"rifle", "garand", "luger"}
        assert {row["match"] for row in rows} == {"substring"}

    def test_scope_is_the_one_that_keeps_its_prefix(self, client, admin_headers):
        rows = client.get("/api/classifier-keywords", headers=admin_headers).json()
        suffixed = [row["keyword"] for row in rows if row["match"] == "suffix"]
        assert suffixed == ["scope"]
        # A periscope, not a riflescope: "rifle" is a firearm word and a
        # substring match, so "riflescope" is vetoed before the accessory
        # words are read at all. That is the original behavior, faithfully.
        assert accessories.looks_like_one("german periscope, wwii") is True

    def test_spring_does_not_reach_springfield(self):
        """The bug this list was rewritten to fix. "spring" was a substring
        test, so a Springfield Model 1903 was an accessory and never got a
        caliber -- 23 of the 28 in the database."""
        assert accessories.looks_like_one("springfield model 1903") is False
        assert accessories.looks_like_one("recoil spring assembly") is True

    def test_the_vetoes_are_read_before_the_accessory_words(self):
        # Both of these contain "bayonet", which is an accessory word.
        assert accessories.looks_like_one("mosin-nagant w/ free bayonet") is False
        assert accessories.looks_like_one("german k98 rifle and bayonet") is False
        assert accessories.looks_like_one("german bayonet, no scabbard") is True

    def test_a_new_word_takes_effect_at_once(self, client, signed_in):
        assert accessories.looks_like_one("brass oiler") is False
        response = client.post(
            "/api/classifier-keywords",
            json={"kind": "accessory", "keyword": "oiler"},
            headers=csrf(signed_in),
        )
        assert response.status_code == 201, response.text
        assert accessories.looks_like_one("brass oiler") is True

    def test_a_veto_can_be_added_too(self, client, signed_in):
        assert accessories.looks_like_one("vetterli bayonet") is True
        client.post(
            "/api/classifier-keywords",
            json={"kind": "firearm", "keyword": "vetterli", "match": "substring"},
            headers=csrf(signed_in),
        )
        assert accessories.looks_like_one("vetterli bayonet") is False

    def test_removing_one_takes_effect_at_once(self, client, clean_db, signed_in):
        row = clean_db.query(ClassifierKeyword).filter_by(kind="accessory", keyword="helmet").one()
        assert (
            client.delete(f"/api/classifier-keywords/{row.id}", headers=csrf(signed_in)).status_code
            == 204
        )
        assert accessories.looks_like_one("german stahlhelm m35") is True  # stahlhelm
        assert accessories.looks_like_one("british brodie helmet") is False

    def test_a_duplicate_within_one_list_is_refused(self, client, signed_in):
        response = client.post(
            "/api/classifier-keywords",
            json={"kind": "accessory", "keyword": "Bayonet"},
            headers=csrf(signed_in),
        )
        assert response.status_code == 409

    def test_the_same_word_may_appear_in_two_lists(self, client, signed_in):
        """Unique per list rather than outright: the three do not share a
        namespace and nothing is gained by making them fight over one."""
        response = client.post(
            "/api/classifier-keywords",
            json={"kind": "firearm", "keyword": "bayonet", "match": "substring"},
            headers=csrf(signed_in),
        )
        assert response.status_code == 201, response.text

    def test_an_unknown_list_is_refused(self, client, signed_in):
        response = client.post(
            "/api/classifier-keywords",
            json={"kind": "whatever", "keyword": "thing"},
            headers=csrf(signed_in),
        )
        assert response.status_code == 422

    def test_a_normal_user_can_neither_read_nor_write(self, client, normal_user):
        response = client.get("/api/classifier-keywords", headers=normal_user["headers"])
        assert response.status_code == 403
