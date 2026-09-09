"""Saved searches: a named browse query, and the email that carries its results.

Three things have to hold, and they are the three the feature was asked for:

1. **A saved search is the browse page's own query**, so running one lands on
   exactly the listings the browser would show.
2. **The email is capped and the run is not.** The cap is the owner's setting;
   opening the search returns everything it matches.
3. **The sort is part of the search**, and the email comes out in it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    EmailPreference,
    EmailStatus,
    Item,
    SavedSearch,
    Site,
    User,
    utcnow,
)
from app.services import digest
from app.services import search as search_service


@pytest.fixture
def user(seeded):
    return seeded.query(User).filter_by(username="admin").one()


@pytest.fixture
def catalog(seeded):
    """Twelve rifles and three handguns at known prices."""
    site = seeded.query(Site).first()
    now = utcnow()
    long_prose = (
        "A long description of this rifle, of its bore and of its many markings, "
        "which runs a good deal past the length that any single row of an email "
        "digest is willing to carry before it has to stop and say so with an ellipsis."
    )
    made = [
        Item(
            site_id=site.id,
            external_key=f"saved-rifle-{index}",
            url=f"https://example.test/rifle-{index}",
            title=f"Mosin Nagant 91/30 number {index}",
            description=long_prose,
            caliber="7.62x54R",
            current_price=100.0 + index,
            is_rifle=True,
            is_active=True,
            first_seen_at=now - timedelta(hours=index + 1),
            last_seen_at=now,
        )
        for index in range(12)
    ] + [
        Item(
            site_id=site.id,
            external_key=f"saved-pistol-{index}",
            url=f"https://example.test/pistol-{index}",
            title=f"Tokarev TT-33 number {index}",
            caliber="7.62x25",
            current_price=400.0 + index,
            is_pistol=True,
            is_active=True,
            first_seen_at=now - timedelta(hours=index + 1),
            last_seen_at=now,
        )
        for index in range(3)
    ]
    seeded.add_all(made)
    seeded.commit()
    return made


class TestTheStoredQuery:
    def test_it_is_the_browse_pages_own_parameters(self):
        parsed = search_service.parse_query("caliber=7.62x54R&kind=rifle&sort=price_asc")
        assert parsed.filters["calibers"] == ["7.62x54R"]
        assert parsed.filters["kinds"] == ["rifle"]
        assert parsed.sort == "price_asc"

    def test_paging_is_dropped(self):
        """Two searches that differ only in page size are one search — and an
        email must never be silently capped at whatever page the user happened
        to be on when they saved it."""
        parsed = search_service.parse_query("kind=rifle&page=7&per_page=12&include_facets=false")
        assert parsed.as_query_string() == "availability=available&kind=rifle&sort=newest"

    def test_the_stored_form_is_canonical(self):
        """Same clicks in a different order, same saved search."""
        one = search_service.parse_query("kind=rifle&caliber=8mm&sort=title")
        two = search_service.parse_query("sort=title&caliber=8mm&kind=rifle")
        assert one.as_query_string() == two.as_query_string()

    @pytest.mark.parametrize(
        "query",
        ["sort=sideways", "frobnicate=1", "min_price=cheap", "kind=tank", "site_id=all"],
    )
    def test_a_query_that_cannot_be_run_is_refused(self, query):
        """Refused when saved, because it is run unattended afterwards and
        there is nobody there to see an error."""
        with pytest.raises(search_service.BadQuery):
            search_service.parse_query(query)


class TestRunningIt:
    def test_it_returns_what_the_filters_match(self, seeded, catalog):
        found = search_service.run(seeded, search_service.parse_query("kind=rifle"))
        assert len(found) == 12

    def test_and_honors_the_saved_sort(self, seeded, catalog):
        cheapest = search_service.run(
            seeded, search_service.parse_query("kind=rifle&sort=price_asc")
        )
        dearest = search_service.run(
            seeded, search_service.parse_query("kind=rifle&sort=price_desc")
        )
        assert cheapest[0].current_price == 100.0
        assert dearest[0].current_price == 111.0

    def test_a_run_is_uncapped(self, seeded, catalog):
        """The cap belongs to the email. Opening the search shows the lot."""
        assert len(search_service.run(seeded, search_service.parse_query(""))) >= 15

    def test_but_the_email_asks_for_a_limit(self, seeded, catalog):
        found = search_service.run(seeded, search_service.parse_query("kind=rifle"), limit=5)
        assert len(found) == 5


class TestTheApi:
    def _save(self, client, headers, **body):
        payload = {"name": "Mosins", "query": "kind=rifle&sort=price_asc"}
        payload.update(body)
        return client.post("/api/saved-searches", json=payload, headers=headers)

    def test_saving_and_listing(self, client, admin_headers, catalog):
        assert self._save(client, admin_headers).status_code == 201

        rows = client.get("/api/saved-searches", headers=admin_headers).json()
        assert [row["name"] for row in rows] == ["Mosins"]
        assert rows[0]["sort"] == "price_asc"
        # The whole result set, not the email's view of it.
        assert rows[0]["match_count"] == 12
        assert rows[0]["email_item_limit"] == 10

    def test_the_query_comes_back_canonical(self, client, admin_headers):
        body = self._save(client, admin_headers, query="page=4&kind=rifle&sort=title").json()
        assert body["query"] == "availability=available&kind=rifle&sort=title"

    def test_an_unrunnable_query_is_a_400(self, client, admin_headers):
        assert self._save(client, admin_headers, query="sort=sideways").status_code == 400

    def test_two_searches_cannot_share_a_name(self, client, admin_headers):
        self._save(client, admin_headers)
        assert self._save(client, admin_headers).status_code == 409

    def test_the_email_settings_are_patchable_on_their_own(self, client, admin_headers):
        made = self._save(client, admin_headers).json()

        body = client.patch(
            f"/api/saved-searches/{made['id']}",
            json={"email_enabled": True, "email_item_limit": 20},
            headers=admin_headers,
        ).json()

        assert body["email_enabled"] is True
        assert body["email_item_limit"] == 20
        # Untouched by a patch that did not mention it.
        assert body["query"] == made["query"]

    def test_a_limit_the_dropdown_does_not_offer_is_refused(self, client, admin_headers):
        """The control that sets this is a select box, and a value it does not
        offer is one it cannot show back — it renders blank, which reads as
        "unset" for something very much set."""
        made = self._save(client, admin_headers).json()
        response = client.patch(
            f"/api/saved-searches/{made['id']}",
            json={"email_item_limit": 17},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_and_every_one_it_does_offer_is_accepted(self, client, admin_headers):
        from app.schemas import SAVED_SEARCH_LIMITS

        made = self._save(client, admin_headers).json()
        for limit in SAVED_SEARCH_LIMITS:
            body = client.patch(
                f"/api/saved-searches/{made['id']}",
                json={"email_item_limit": limit},
                headers=admin_headers,
            )
            assert body.status_code == 200, limit
            assert body.json()["email_item_limit"] == limit

    def test_deleting_one(self, client, admin_headers):
        made = self._save(client, admin_headers).json()
        assert (
            client.delete(f"/api/saved-searches/{made['id']}", headers=admin_headers).status_code
            == 204
        )
        assert client.get("/api/saved-searches", headers=admin_headers).json() == []

    def test_somebody_elses_search_does_not_exist(self, client, admin_headers, seeded):
        """404 rather than 403: whether a given id exists is not this user's
        business either."""
        other = User(username="other", email="other@example.test", password_hash="x")
        seeded.add(other)
        seeded.commit()
        row = SavedSearch(user_id=other.id, name="Theirs", query="", sort="newest")
        seeded.add(row)
        seeded.commit()

        assert client.get("/api/saved-searches", headers=admin_headers).json() == []
        assert (
            client.patch(
                f"/api/saved-searches/{row.id}", json={"name": "Mine"}, headers=admin_headers
            ).status_code
            == 404
        )

    def test_it_needs_a_signed_in_user(self, client):
        assert client.get("/api/saved-searches").status_code in (401, 403)


class TestTheEmail:
    @pytest.fixture
    def mailing(self, seeded, user):
        preference = seeded.query(EmailPreference).filter_by(user_id=user.id).one_or_none()
        if preference is None:
            preference = EmailPreference(user_id=user.id)
            seeded.add(preference)
        preference.enabled = True
        row = SavedSearch(
            user_id=user.id,
            name="Cheap Mosins",
            query="kind=rifle&sort=price_asc",
            sort="price_asc",
            email_enabled=True,
            email_item_limit=5,
        )
        seeded.add(row)
        seeded.commit()
        seeded.refresh(user)
        return row

    def test_it_carries_the_whole_result_set_capped(self, seeded, user, catalog, mailing):
        """Not "what is new": a saved search is a standing question and its
        answer is what matches today."""
        found = digest.collect_saved_searches(seeded, user)
        assert len(found) == 1
        row, items, total = found[0]
        assert row.name == "Cheap Mosins"
        assert len(items) == 5
        assert total == 12

    def test_in_the_order_the_search_was_saved_with(self, seeded, user, catalog, mailing):
        _row, items, _total = digest.collect_saved_searches(seeded, user)[0]
        assert [item.current_price for item in items] == [100.0, 101.0, 102.0, 103.0, 104.0]

    def test_a_search_with_email_off_is_not_collected(self, seeded, user, catalog, mailing):
        mailing.email_enabled = False
        seeded.commit()
        assert digest.collect_saved_searches(seeded, user) == []

    def test_a_query_that_has_rotted_is_skipped_not_raised(self, seeded, user, catalog, mailing):
        """One bad row must not cost the user their whole digest."""
        mailing.query = "frobnicate=1"
        seeded.commit()
        assert digest.collect_saved_searches(seeded, user) == []

    def test_the_rows_link_to_our_item_page_not_the_vendor(
        self, seeded, user, catalog, mailing, app_config
    ):
        """What was asked for, and the better link: our page carries the price
        history and a "View on vendor site" button, so the vendor is one more
        click rather than unreachable."""
        saved = digest.collect_saved_searches(seeded, user)
        _subject, body, _images = digest.render_digest(
            user, {}, {}, {}, utcnow(), app_config, saved
        )

        item = saved[0][1][0]
        assert f"/items/{item.id}" in body
        assert item.url not in body

    def test_the_section_says_what_it_left_out(self, seeded, user, catalog, mailing, app_config):
        saved = digest.collect_saved_searches(seeded, user)
        _subject, body, _images = digest.render_digest(
            user, {}, {}, {}, utcnow(), app_config, saved
        )
        assert "Showing 5 of 12 matches" in body

    def test_the_subject_names_a_single_search(self, seeded, user, catalog, mailing, app_config):
        saved = digest.collect_saved_searches(seeded, user)
        subject, _body, _images = digest.render_digest(
            user, {}, {}, {}, utcnow(), app_config, saved
        )
        assert "Cheap Mosins" in subject

    def test_titles_and_descriptions_are_truncated(
        self, seeded, user, catalog, mailing, app_config
    ):
        saved = digest.collect_saved_searches(seeded, user)
        _subject, body, _images = digest.render_digest(
            user, {}, {}, {}, utcnow(), app_config, saved
        )
        assert "…" in body
        assert "before it has to stop and say so" not in body


@pytest.fixture
def sent_mail(monkeypatch):
    """Every message the code under test would have sent, captured."""
    posted: list[dict[str, str]] = []

    def capture(to_address, subject, html_body, *args, **kwargs):
        posted.append({"to": to_address, "subject": subject, "html": html_body})

    monkeypatch.setattr(digest.mailer, "send_html", capture)
    return posted


@pytest.fixture
def mail_on(client, app_config):
    """Email switched on in the config the API reads.

    The suite's config has it off, which is the right default for a test run
    and is its own case below — but the send path cannot be exercised without
    turning it on. `Config` is frozen, so this replaces the dependency rather
    than mutating the object.
    """
    import dataclasses

    from app.deps import get_config

    on = dataclasses.replace(app_config, email=dataclasses.replace(app_config.email, enabled=True))
    client.app.dependency_overrides[get_config] = lambda: on
    yield on
    client.app.dependency_overrides.pop(get_config, None)


class TestSendNow:
    """The button on each card: mail this one search, now.

    Two things it must not do — move the digest's watermark, and refuse to run
    because the daily email is switched off. "Send this every day" and "send it
    to me now" are different questions, and being able to see what a search
    would mail before committing to the daily one is most of the point.
    """

    @pytest.fixture
    def saved(self, seeded, user):
        row = SavedSearch(
            user_id=user.id,
            name="Cheap Mosins",
            query="kind=rifle&sort=price_asc",
            sort="price_asc",
            email_enabled=False,
            email_item_limit=5,
        )
        seeded.add(row)
        seeded.commit()
        return row

    def test_it_sends_and_stamps_the_row(self, seeded, user, catalog, saved, app_config, sent_mail):
        entry = digest.send_saved_search(seeded, user, saved, app_config)

        assert entry.status is EmailStatus.SENT
        assert saved.last_emailed_at is not None
        assert len(sent_mail) == 1
        assert "Cheap Mosins" in sent_mail[0]["subject"]

    def test_even_though_the_daily_email_is_off(
        self, seeded, user, catalog, saved, app_config, sent_mail
    ):
        assert saved.email_enabled is False
        assert digest.send_saved_search(seeded, user, saved, app_config).status is EmailStatus.SENT

    def test_it_carries_only_this_search(self, seeded, user, catalog, saved, app_config, sent_mail):
        """Not the digest. No new-listings or price-reductions section."""
        digest.send_saved_search(seeded, user, saved, app_config)

        body = sent_mail[0]["html"]
        assert "Cheap Mosins" in body
        assert "New listings" not in body
        assert "Price reductions" not in body

    def test_it_honors_the_cap_and_the_sort(
        self, seeded, user, catalog, saved, app_config, sent_mail
    ):
        digest.send_saved_search(seeded, user, saved, app_config)
        assert "Showing 5 of 12 matches" in sent_mail[0]["html"]

    def test_it_does_not_move_the_digest_watermark(
        self, seeded, user, catalog, saved, app_config, sent_mail
    ):
        """This is not the daily digest arriving early. Moving the watermark
        would make the next real one skip everything sent in between."""
        preference = seeded.query(EmailPreference).filter_by(user_id=user.id).one_or_none()
        if preference is None:
            preference = EmailPreference(user_id=user.id)
            seeded.add(preference)
            seeded.commit()
        before = (preference.last_digest_cutoff, preference.next_send_at, preference.last_sent_at)

        digest.send_saved_search(seeded, user, saved, app_config)

        assert (
            preference.last_digest_cutoff,
            preference.next_send_at,
            preference.last_sent_at,
        ) == before

    def test_a_search_matching_nothing_sends_nothing(
        self, seeded, user, saved, app_config, sent_mail
    ):
        """An empty email is worse than a line of text on the screen the button
        is on, so the caller is told instead."""
        entry = digest.send_saved_search(seeded, user, saved, app_config)

        assert entry.status is EmailStatus.SKIPPED
        assert "matches nothing" in (entry.error_message or "")
        assert sent_mail == []

    def test_the_endpoint_is_refused_when_email_is_switched_off(self, client, admin_headers):
        """The test config has email off, which is the interesting case."""
        made = client.post(
            "/api/saved-searches",
            json={"name": "Offline", "query": "kind=rifle"},
            headers=admin_headers,
        ).json()

        response = client.post(f"/api/saved-searches/{made['id']}/send", headers=admin_headers)
        assert response.status_code == 409
        assert "disabled" in response.json()["detail"]

    def test_the_endpoint_reports_an_empty_search_as_a_conflict(
        self, client, admin_headers, mail_on, sent_mail
    ):
        made = client.post(
            "/api/saved-searches",
            json={"name": "Empty", "query": "search=nothingmatchesthis"},
            headers=admin_headers,
        ).json()

        response = client.post(f"/api/saved-searches/{made['id']}/send", headers=admin_headers)
        assert response.status_code == 409
        assert "matches nothing" in response.json()["detail"]

    def test_the_endpoint_sends(self, client, admin_headers, catalog, mail_on, sent_mail):
        made = client.post(
            "/api/saved-searches",
            json={"name": "Sendable", "query": "kind=rifle"},
            headers=admin_headers,
        ).json()

        response = client.post(f"/api/saved-searches/{made['id']}/send", headers=admin_headers)
        assert response.status_code == 202
        assert len(sent_mail) == 1

    def test_somebody_elses_search_cannot_be_sent(self, client, admin_headers, seeded):
        other = User(username="other-send", email="other-send@example.test", password_hash="x")
        seeded.add(other)
        seeded.commit()
        row = SavedSearch(user_id=other.id, name="Theirs", query="", sort="newest")
        seeded.add(row)
        seeded.commit()

        assert (
            client.post(f"/api/saved-searches/{row.id}/send", headers=admin_headers).status_code
            == 404
        )


class TestTruncation:
    @pytest.mark.parametrize("text", [None, ""])
    def test_nothing_stays_nothing(self, text):
        assert digest.truncate(text, 10) == ""

    def test_something_short_enough_is_untouched(self):
        assert digest.truncate("K98k", 10) == "K98k"

    def test_a_cut_lands_on_a_word_boundary(self):
        assert digest.truncate("Mosin Nagant 91/30 Izhevsk 1943", 20) == "Mosin Nagant 91/30…"

    def test_a_word_longer_than_the_budget_is_cut_anyway(self):
        """No boundary to find, and returning the whole thing would defeat the
        cap it was called to enforce."""
        assert digest.truncate("supercalifragilistic", 10) == "supercalif…"

    def test_whitespace_is_collapsed_first(self):
        assert digest.truncate("K98k\n\n  rifle", 40) == "K98k rifle"
