"""Corrections by hand, and the one property that makes them worth having.

Everything this application knows beyond the vendor's own words is derived and
recomputed on every scan. That is deliberate -- it is what lets one rule fix
reach eleven thousand listings -- and it is exactly what made a correction
typed into the database survive until the next scan and no longer.

So the test that matters here is not that an override can be saved. It is that
a scan runs afterwards and the correction is still there.
"""

from __future__ import annotations

import pytest

from app import sessions
from app.models import Item, ItemOverride, Site
from app.services import overrides


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


@pytest.fixture
def listing(clean_db):
    # Its own site when there is not one: three of the tests below never touch
    # the API, so nothing has seeded the catalog for them.
    site = clean_db.query(Site).first()
    if site is None:
        site = Site(slug="override-shop", name="Override Shop", base_url="https://example.com/")
        clean_db.add(site)
        clean_db.flush()
    item = Item(
        site_id=site.id,
        external_key="override-subject",
        url="https://example.com/rifle",
        title="Swiss Luger 1906/24 7.65mm",
        caliber=".32 ACP",
        country="Switzerland",
        is_active=True,
    )
    clean_db.add(item)
    clean_db.commit()
    return item


class TestSettingOne:
    def test_it_wins_over_what_the_rules_said(self, client, clean_db, listing, signed_in):
        response = client.put(
            f"/api/items/{listing.id}/override",
            json={"caliber": "7.65 Parabellum", "note": "It is a Luger."},
            headers=csrf(signed_in),
        )
        assert response.status_code == 200, response.text
        clean_db.refresh(listing)
        assert listing.caliber == "7.65 Parabellum"

    def test_it_records_who_and_why(self, client, clean_db, listing, signed_in):
        """An override nobody can explain is one nobody can safely undo."""
        client.put(
            f"/api/items/{listing.id}/override",
            json={"caliber": "7.65 Parabellum", "note": "It is a Luger."},
            headers=csrf(signed_in),
        )
        row = clean_db.query(ItemOverride).filter_by(item_id=listing.id).one()
        assert row.set_by_name == "admin"
        assert row.note == "It is a Luger."

    def test_an_omitted_field_is_not_an_opinion(self, client, clean_db, listing, signed_in):
        """Correcting a caliber is not also asserting the country is unknown,
        and a form posting every box would say exactly that on every save."""
        client.put(
            f"/api/items/{listing.id}/override",
            json={"caliber": "7.65 Parabellum"},
            headers=csrf(signed_in),
        )
        clean_db.refresh(listing)
        assert listing.country == "Switzerland"
        assert clean_db.query(ItemOverride).filter_by(item_id=listing.id).one().country is None

    def test_an_empty_field_stops_overriding_it(self, client, clean_db, listing, signed_in):
        client.put(
            f"/api/items/{listing.id}/override",
            json={"caliber": "7.65 Parabellum", "country": "Germany"},
            headers=csrf(signed_in),
        )
        client.put(
            f"/api/items/{listing.id}/override",
            json={"country": ""},
            headers=csrf(signed_in),
        )
        row = clean_db.query(ItemOverride).filter_by(item_id=listing.id).one()
        assert row.country is None
        # ...and the other correction is untouched.
        assert row.caliber == "7.65 Parabellum"


class TestItSurvivesAScan:
    def test_re_deriving_the_listing_does_not_undo_it(self, clean_db, listing):
        """The whole point. `apply_to` is what the scan calls after the
        heuristics and the armory have had their say."""
        overrides.save(clean_db, listing, {"caliber": "7.65 Parabellum"})
        clean_db.commit()

        # What a scan does: recompute, then apply.
        listing.caliber = ".32 ACP"
        clean_db.flush()
        changed = overrides.apply_to(clean_db, listing)

        assert changed
        assert listing.caliber == "7.65 Parabellum"

    def test_a_listing_with_no_override_is_left_alone(self, clean_db, listing):
        assert overrides.apply_to(clean_db, listing) is False
        assert listing.caliber == ".32 ACP"


class TestClearingOne:
    def test_it_goes(self, client, clean_db, listing, signed_in):
        client.put(
            f"/api/items/{listing.id}/override",
            json={"caliber": "7.65 Parabellum"},
            headers=csrf(signed_in),
        )
        response = client.delete(f"/api/items/{listing.id}/override", headers=csrf(signed_in))
        assert response.status_code == 204
        assert clean_db.query(ItemOverride).filter_by(item_id=listing.id).first() is None

    def test_the_derived_value_is_not_guessed_back(self, clean_db, listing):
        """What it should be is the scan's business. Restoring it from here
        would mean a second implementation of the pipeline."""
        overrides.save(clean_db, listing, {"caliber": "7.65 Parabellum"})
        clean_db.commit()
        overrides.clear(clean_db, listing)
        assert listing.caliber == "7.65 Parabellum"

    def test_clearing_nothing_is_a_404(self, client, listing, signed_in):
        assert (
            client.delete(f"/api/items/{listing.id}/override", headers=csrf(signed_in)).status_code
            == 404
        )


class TestWhoMayDoIt:
    def test_a_normal_user_cannot_set_one(self, client, listing, normal_user):
        """An override outranks every rule in the application, and one set by
        mistake is invisible: the listing simply reads wrong."""
        response = client.put(
            f"/api/items/{listing.id}/override",
            json={"caliber": "9mm"},
            headers=normal_user["headers"],
        )
        assert response.status_code == 403

    def test_but_can_read_one(self, client, listing, normal_user):
        response = client.get(f"/api/items/{listing.id}/override", headers=normal_user["headers"])
        assert response.status_code == 200
