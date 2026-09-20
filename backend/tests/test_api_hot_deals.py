"""The hot deals page, over HTTP.

One request answers the whole page — the deals, the tab counts, this reader's
subscription, and for an administrator the settings behind it. That shape is
deliberate and is worth a test of its own: a page that had to make four calls
to render once would spend most of its life in three different half-loaded
states, and every write here answers with the same object so nothing reloads.

The access tests matter more than they look. It is a *reader's* page with an
operator's panel inside it, and the two have to come apart cleanly: everybody
signed in can see the deals and choose their own categories, and only an
administrator can change what counts as one for everybody.
"""

from __future__ import annotations

import pytest

from app.api import hotdeals as hot_deals_api
from app.models import FirearmModel, HotDealPreference, Item, Site
from app.services import hotdeals


@pytest.fixture
def stocked(seeded):
    """One bargain, and enough dearer peers across two shops to make it one."""
    model = FirearmModel(name="K31")
    a = Site(slug="deal-a", name="Deal Shop A", base_url="https://da.test/")
    b = Site(slug="deal-b", name="Deal Shop B", base_url="https://db.test/")
    seeded.add_all([model, a, b])
    seeded.flush()

    def add(site, price, index, **kwargs):
        seeded.add(
            Item(
                site_id=site.id,
                external_key=f"{site.slug}-{index}",
                url=f"{site.base_url}{index}",
                title=f"Schmidt Rubin K31 {index}",
                caliber="7.5x55mm Swiss",
                firearm_model_id=model.id,
                current_price=price,
                is_rifle=kwargs.get("rifle", True),
                is_pistol=kwargs.get("pistol", False),
                is_police_surplus=kwargs.get("police", False),
            )
        )

    add(a, 500.0, 0)
    for index in range(4):
        add(b, 1000.0, index + 1)
    seeded.commit()
    hotdeals.refresh(seeded)
    return seeded


class TestReadingThePage:
    def test_one_request_answers_all_of_it(self, client, admin_headers, stocked):
        body = client.get("/api/hot-deals", headers=admin_headers).json()

        assert len(body["deals"]) == 1
        assert body["counts"] == {"rifle": 1, "pistol": 0, "police_surplus": 0}
        assert body["buckets"] == ["rifle", "pistol", "police_surplus"]
        assert body["labels"]["police_surplus"] == "Police surplus"
        assert body["preference"]["enabled"] is True

    def test_a_deal_carries_its_evidence(self, client, admin_headers, stocked):
        """A discount with nothing behind it is a marketing claim. This one has
        a peer count and a vendor count behind it, and the page says so."""
        deal = client.get("/api/hot-deals", headers=admin_headers).json()["deals"][0]

        assert deal["discount_percent"] == 50.0
        assert deal["median_price"] == 1000.0
        assert deal["cheaper_than"] == 80
        assert deal["peer_count"] == 5
        assert deal["vendor_count"] == 2
        assert deal["duplicate_count"] == 1
        # The listing travels whole, so the page renders it with the same card
        # a search result uses.
        assert deal["item"]["title"].startswith("Schmidt Rubin K31")
        assert deal["item"]["site_name"] == "Deal Shop A"

    def test_a_category_filter_selects_only_its_own(self, client, admin_headers, stocked):
        assert (
            len(client.get("/api/hot-deals?bucket=rifle", headers=admin_headers).json()["deals"])
            == 1
        )
        assert (
            client.get("/api/hot-deals?bucket=pistol", headers=admin_headers).json()["deals"] == []
        )

    def test_but_the_counts_always_describe_the_whole_page(self, client, admin_headers, stocked):
        """So the tabs can say what the other tabs hold, which is the point of
        putting a number on a tab."""
        body = client.get("/api/hot-deals?bucket=pistol", headers=admin_headers).json()
        assert body["deals"] == []
        assert body["counts"]["rifle"] == 1

    def test_a_category_that_does_not_exist_is_refused(self, client, admin_headers, stocked):
        """Rather than quietly answering with everything, which would hide the
        bug behind a plausible-looking result."""
        response = client.get("/api/hot-deals?bucket=nonsense", headers=admin_headers)
        assert response.status_code == 422

    def test_signing_in_is_required(self, client, stocked):
        assert client.get("/api/hot-deals").status_code == 401


class TestWhoSeesTheSettingsPanel:
    def test_an_administrator_does(self, client, admin_headers, stocked):
        body = client.get("/api/hot-deals", headers=admin_headers).json()
        assert body["settings"]["interval_hours"] == 8
        assert body["interval_choices"] == list(hot_deals_api.ALLOWED_INTERVAL_HOURS)

    def test_and_an_ordinary_reader_does_not(self, client, normal_user, stocked):
        """Null rather than absent, so the page keys the panel off the response
        instead of re-deriving the role for itself."""
        body = client.get("/api/hot-deals", headers=normal_user["headers"]).json()
        assert body["settings"] is None
        assert body["interval_choices"] is None
        # ...but they still see the deals. It is a reader's page.
        assert len(body["deals"]) == 1

    def test_and_cannot_change_them(self, client, normal_user, stocked):
        response = client.patch(
            "/api/hot-deals/settings", json={"interval_hours": 24}, headers=normal_user["headers"]
        )
        assert response.status_code == 403


class TestTheSubscription:
    def test_it_starts_on_with_every_category(self, client, normal_user, stocked):
        """No row exists yet. The absence *is* the default, and reading it must
        not create one -- that absence is what gives every existing account the
        feature without a backfill."""
        body = client.get("/api/hot-deals", headers=normal_user["headers"]).json()
        assert body["preference"] == {
            "enabled": True,
            "include_rifles": True,
            "include_handguns": True,
            "include_police_surplus": True,
            "last_sent_at": None,
        }
        assert stocked.query(HotDealPreference).count() == 0

    def test_changing_one_keeps_the_others(self, client, normal_user, stocked):
        body = client.patch(
            "/api/hot-deals/preference",
            json={"include_police_surplus": False},
            headers=normal_user["headers"],
        ).json()
        assert body["preference"]["include_police_surplus"] is False
        assert body["preference"]["include_rifles"] is True

    def test_and_the_answer_is_the_whole_page_again(self, client, normal_user, stocked):
        """So nothing reloads: the response *is* the new state, and a second
        request would leave the two able to disagree for a moment."""
        body = client.patch(
            "/api/hot-deals/preference", json={"enabled": False}, headers=normal_user["headers"]
        ).json()
        assert body["preference"]["enabled"] is False
        assert len(body["deals"]) == 1
        assert body["counts"]["rifle"] == 1

    def test_one_readers_choice_is_not_another_s(self, client, admin_headers, normal_user, stocked):
        client.patch(
            "/api/hot-deals/preference", json={"enabled": False}, headers=normal_user["headers"]
        )
        admin = client.get("/api/hot-deals", headers=admin_headers).json()
        assert admin["preference"]["enabled"] is True


class TestTheThresholds:
    def test_an_administrator_can_move_them(self, client, admin_headers, stocked):
        body = client.patch(
            "/api/hot-deals/settings", json={"min_cheaper_than": 90}, headers=admin_headers
        ).json()
        assert body["settings"]["min_cheaper_than"] == 90

    def test_a_cadence_off_the_list_is_refused(self, client, admin_headers, stocked):
        """Free text invites "1", which is a full pass over the catalog every
        hour to answer a question whose inputs move once a day."""
        response = client.patch(
            "/api/hot-deals/settings", json={"interval_hours": 7}, headers=admin_headers
        )
        assert response.status_code == 400
        assert "must be one of" in response.json()["detail"]

    def test_and_so_is_a_threshold_outside_its_bounds(self, client, admin_headers, stocked):
        response = client.patch(
            "/api/hot-deals/settings", json={"min_cheaper_than": 20}, headers=admin_headers
        )
        assert response.status_code == 400

    def test_a_floor_above_its_ceiling_is_refused_as_a_pair(self, client, admin_headers, stocked):
        """**Checked against the saved row, not against the payload.**

        The page sends only what changed, so raising the floor past a ceiling
        that is staying put arrives as a single field -- each half in range,
        the pair selecting nothing at all. Validating the fields one at a time
        would wave this through.
        """
        client.patch(
            "/api/hot-deals/settings", json={"max_discount_percent": 25}, headers=admin_headers
        )
        response = client.patch(
            "/api/hot-deals/settings", json={"min_discount_percent": 30}, headers=admin_headers
        )
        assert response.status_code == 400
        assert "below the largest" in response.json()["detail"]

    def test_and_nothing_is_saved_when_it_is(self, client, admin_headers, stocked):
        client.patch(
            "/api/hot-deals/settings", json={"max_discount_percent": 25}, headers=admin_headers
        )
        client.patch(
            "/api/hot-deals/settings", json={"min_discount_percent": 30}, headers=admin_headers
        )
        body = client.get("/api/hot-deals", headers=admin_headers).json()
        assert body["settings"]["min_discount_percent"] == 20
        assert body["settings"]["max_discount_percent"] == 25

    def test_moving_a_threshold_changes_what_the_next_pass_finds(
        self, client, admin_headers, stocked
    ):
        client.patch(
            "/api/hot-deals/settings", json={"max_discount_percent": 40}, headers=admin_headers
        )
        body = client.post("/api/hot-deals/refresh", headers=admin_headers).json()
        # The 50%-off K31 is now past the ceiling.
        assert body["deals"] == []


class TestLookingAgainNow:
    def test_it_runs_even_when_the_schedule_is_off(self, client, admin_headers, stocked):
        """Which is the state it is most useful in: thresholds just changed,
        and nobody wants to wait eight hours to see what they did."""
        client.patch("/api/hot-deals/settings", json={"enabled": False}, headers=admin_headers)
        body = client.post("/api/hot-deals/refresh", headers=admin_headers).json()
        assert len(body["deals"]) == 1
        assert body["settings"]["last_deal_count"] == 1

    def test_an_ordinary_reader_cannot(self, client, normal_user, stocked):
        assert (
            client.post("/api/hot-deals/refresh", headers=normal_user["headers"]).status_code == 403
        )
