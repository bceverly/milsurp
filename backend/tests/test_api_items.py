"""Item listing: filters, search, facets, pagination and photo access."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Item, ItemPhoto, PriceHistory, Site, utcnow


@pytest.fixture
def inventory(seeded):
    """A small, deterministic catalog across both seeded sites."""
    sites = {site.slug: site for site in seeded.query(Site).all()}
    rti = sites["royal-tiger"]
    empire = sites["empire-arms"]
    now = utcnow()

    rows = [
        # (site, key, title, price, caliber, country, rifle, pistol, sold, age_days)
        (
            rti,
            "a",
            "GERMAN K98 Mauser rifle",
            900.0,
            "8mm Mauser",
            "Germany",
            True,
            False,
            False,
            1,
        ),
        (
            rti,
            "b",
            "RUSSIAN Mosin Nagant M91/30",
            400.0,
            "7.62x54R",
            "Russia",
            True,
            False,
            False,
            5,
        ),
        (rti, "c", "Luger P08 pistol", 2200.0, "9mm", "Germany", False, True, False, 10),
        (
            empire,
            "d",
            "BRITISH Lee-Enfield No.4",
            650.0,
            ".303 British",
            "United Kingdom",
            True,
            False,
            False,
            2,
        ),
        (empire, "e", "Bayonet, German", 85.0, None, "Germany", False, False, True, 30),
    ]
    created = []
    for site, key, title, price, caliber, country, rifle, pistol, sold, age in rows:
        item = Item(
            site_id=site.id,
            external_key=key,
            url=f"https://example.test/{key}",
            title=title,
            description=f"{title} in collector condition.",
            category="Rifle" if rifle else "Handgun",
            caliber=caliber,
            country=country,
            is_rifle=rifle,
            is_pistol=pistol,
            is_sold=sold,
            is_active=True,
            current_price=price,
            first_seen_at=now - timedelta(days=age),
            last_seen_at=now,
        )
        seeded.add(item)
        created.append(item)
    seeded.flush()

    # One item with a recorded price reduction.
    drop = created[1]
    drop.previous_price = 500.0
    drop.current_price = 400.0
    drop.price_changed_at = now - timedelta(hours=2)
    seeded.add(PriceHistory(item_id=drop.id, price=500.0, observed_at=now - timedelta(days=5)))
    seeded.add(PriceHistory(item_id=drop.id, price=400.0, observed_at=now - timedelta(hours=2)))
    seeded.commit()
    return created


class TestListing:
    def test_returns_available_items_by_default(self, client, admin_headers, inventory):
        body = client.get("/api/items", headers=admin_headers).json()
        # The sold bayonet is excluded by the default availability filter.
        assert body["total"] == 4
        assert all(not item["is_sold"] for item in body["items"])

    def test_timestamps_are_utc_with_z(self, client, admin_headers, inventory):
        item = client.get("/api/items", headers=admin_headers).json()["items"][0]
        assert item["first_seen_at"].endswith("Z")

    def test_pagination(self, client, admin_headers, inventory):
        body = client.get("/api/items?per_page=2&page=1", headers=admin_headers).json()
        assert len(body["items"]) == 2
        assert body["pages"] == 2
        second = client.get("/api/items?per_page=2&page=2", headers=admin_headers).json()
        first_ids = {i["id"] for i in body["items"]}
        assert not first_ids & {i["id"] for i in second["items"]}

    def test_unknown_sort_rejected(self, client, admin_headers, inventory):
        assert client.get("/api/items?sort=sideways", headers=admin_headers).status_code == 400

    def test_sort_price_ascending(self, client, admin_headers, inventory):
        items = client.get("/api/items?sort=price_asc", headers=admin_headers).json()["items"]
        prices = [i["current_price"] for i in items]
        assert prices == sorted(prices)


class TestSearch:
    def test_matches_the_title(self, client, admin_headers, inventory):
        body = client.get("/api/items?search=mauser", headers=admin_headers).json()
        assert body["total"] == 1
        assert "Mauser" in body["items"][0]["title"]

    def test_is_case_insensitive(self, client, admin_headers, inventory):
        assert client.get("/api/items?search=MAUSER", headers=admin_headers).json()["total"] == 1

    def test_matches_the_description(self, client, admin_headers, inventory):
        body = client.get("/api/items?search=collector", headers=admin_headers).json()
        assert body["total"] == 4

    def test_every_term_must_match(self, client, admin_headers, inventory):
        """Terms are ANDed, and may land in different fields."""
        assert (
            client.get("/api/items?search=mosin+russian", headers=admin_headers).json()["total"]
            == 1
        )
        assert (
            client.get("/api/items?search=mosin+german", headers=admin_headers).json()["total"] == 0
        )

    def test_matches_across_fields(self, client, admin_headers, inventory):
        # "enfield" is in the title; ".303" only in the caliber column.
        assert (
            client.get("/api/items?search=enfield+.303", headers=admin_headers).json()["total"] == 1
        )

    def test_quoted_phrase_kept_together(self, client, admin_headers, inventory):
        assert (
            client.get('/api/items?search="Lee-Enfield No.4"', headers=admin_headers).json()[
                "total"
            ]
            == 1
        )

    def test_wildcards_are_escaped(self, client, admin_headers, inventory):
        """LIKE metacharacters must match literally, not act as wildcards."""
        # "%%" would match every row if it reached SQL unescaped.
        assert client.get("/api/items?search=%25%25", headers=admin_headers).json()["total"] == 0
        # "_" is LIKE's single-character wildcard.
        assert client.get("/api/items?search=M_user", headers=admin_headers).json()["total"] == 0
        # ...while the real substring still matches.
        assert client.get("/api/items?search=Mauser", headers=admin_headers).json()["total"] == 1

    def test_short_terms_are_ignored(self, client, admin_headers, inventory):
        """A one-character term matches too much to be worth filtering on."""
        assert client.get("/api/items?search=a", headers=admin_headers).json()["total"] == 4

    def test_no_match(self, client, admin_headers, inventory):
        assert (
            client.get("/api/items?search=zzzznothing", headers=admin_headers).json()["total"] == 0
        )


class TestFilters:
    def test_by_site(self, client, admin_headers, inventory, seeded):
        rti = seeded.query(Site).filter_by(slug="royal-tiger").one()
        body = client.get(f"/api/items?site_id={rti.id}", headers=admin_headers).json()
        assert body["total"] == 3

    def test_by_caliber(self, client, admin_headers, inventory):
        body = client.get("/api/items?caliber=7.62x54R", headers=admin_headers).json()
        assert body["total"] == 1

    def test_by_kind(self, client, admin_headers, inventory):
        assert client.get("/api/items?kind=rifle", headers=admin_headers).json()["total"] == 3
        assert client.get("/api/items?kind=pistol", headers=admin_headers).json()["total"] == 1

    def test_multiple_values_are_ored(self, client, admin_headers, inventory):
        body = client.get("/api/items?country=Germany&country=Russia", headers=admin_headers).json()
        assert body["total"] == 3

    def test_price_range(self, client, admin_headers, inventory):
        body = client.get("/api/items?min_price=500&max_price=1000", headers=admin_headers).json()
        assert body["total"] == 2

    def test_price_drops_only(self, client, admin_headers, inventory):
        body = client.get("/api/items?price_drops_only=true", headers=admin_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["price_drop"] == 100.0

    def test_sold_filter(self, client, admin_headers, inventory):
        assert (
            client.get("/api/items?availability=sold", headers=admin_headers).json()["total"] == 1
        )

    def test_all_availability(self, client, admin_headers, inventory):
        assert client.get("/api/items?availability=all", headers=admin_headers).json()["total"] == 5

    @pytest.mark.parametrize(("hours", "expected"), [(36, 1), (72, 2), (240, 3)])
    def test_new_since_hours(self, client, admin_headers, inventory, hours, expected):
        """Fixture ages are 1, 2, 5 and 10 days; windows are chosen to sit
        clearly between them rather than on a boundary the clock can cross."""
        body = client.get(f"/api/items?new_since_hours={hours}", headers=admin_headers).json()
        assert body["total"] == expected


class TestFacets:
    def test_reflect_the_filtered_set(self, client, admin_headers, inventory):
        facets = client.get("/api/items", headers=admin_headers).json()["facets"]
        assert facets["total"] == 4
        countries = {f["value"]: f["count"] for f in facets["countries"]}
        assert countries["Germany"] == 2
        assert {f["label"] for f in facets["sites"]} == {"Royal Tiger Imports", "Empire Arms"}

    def test_can_be_skipped(self, client, admin_headers, inventory):
        body = client.get("/api/items?include_facets=false", headers=admin_headers).json()
        assert body["facets"] is None


class TestDetail:
    def test_includes_price_history(self, client, admin_headers, inventory):
        drop = inventory[1]
        body = client.get(f"/api/items/{drop.id}", headers=admin_headers).json()
        assert len(body["price_history"]) == 2
        assert body["price_drop"] == 100.0
        assert body["description"]

    def test_missing_item(self, client, admin_headers):
        assert client.get("/api/items/999999", headers=admin_headers).status_code == 404

    def test_price_series_is_chronological(self, client, admin_headers, inventory):
        points = client.get(f"/api/items/{inventory[1].id}/prices", headers=admin_headers).json()
        assert [p["price"] for p in points] == [500.0, 400.0]


class TestPhotos:
    def test_photo_requires_authentication(self, client, seeded, inventory):
        photo = ItemPhoto(item_id=inventory[0].id, source_url="https://example.test/a.jpg")
        seeded.add(photo)
        seeded.commit()
        # No Authorization header: the image store is not publicly readable.
        assert client.get(f"/api/items/{inventory[0].id}/photos/{photo.id}").status_code == 401

    def test_photo_without_a_file_is_404(self, client, admin_headers, seeded, inventory):
        photo = ItemPhoto(item_id=inventory[0].id, source_url="https://example.test/b.jpg")
        seeded.add(photo)
        seeded.commit()
        response = client.get(
            f"/api/items/{inventory[0].id}/photos/{photo.id}", headers=admin_headers
        )
        assert response.status_code == 404

    def test_photo_id_must_belong_to_the_item(self, client, admin_headers, seeded, inventory):
        """A photo cannot be fetched through another item's URL."""
        photo = ItemPhoto(
            item_id=inventory[0].id, source_url="https://example.test/c.jpg", filename="x/y.jpg"
        )
        seeded.add(photo)
        seeded.commit()
        response = client.get(
            f"/api/items/{inventory[1].id}/photos/{photo.id}", headers=admin_headers
        )
        assert response.status_code == 404


class TestPhotoCaching:
    """Photo URLs are not stable identifiers for their content.

    /items/<id>/photos/<id> is built from two database ids, and SQLite reuses a
    rowid after a delete. Clear a site and re-scan it and the same URL now
    holds a different picture — which is exactly what happened, and every
    browser that had seen the old one went on showing it for a day, so listings
    appeared under each other's photographs.
    """

    def stored_photo(self, seeded, inventory, tmp_path, config):
        from app.services.image_store import ImageStore

        store = ImageStore(config)
        stored = store.store_bytes("demo", "cache-test-key", _one_pixel_png())
        assert stored is not None
        photo = ItemPhoto(
            item_id=inventory[0].id,
            source_url="cache-test-key",
            filename=stored.filename,
            content_type=stored.content_type,
        )
        seeded.add(photo)
        seeded.commit()
        return photo

    def test_the_browser_must_revalidate_before_reusing_a_photo(
        self, client, admin_headers, seeded, inventory, tmp_path, app_config
    ):
        photo = self.stored_photo(seeded, inventory, tmp_path, app_config)
        response = client.get(
            f"/api/items/{inventory[0].id}/photos/{photo.id}", headers=admin_headers
        )
        assert response.status_code == 200
        cache_control = response.headers["cache-control"]
        assert "no-cache" in cache_control
        # ...and it stays private: these are behind a session.
        assert "private" in cache_control
        assert "max-age=86400" not in cache_control

    def test_a_validator_is_sent_so_revalidation_is_cheap(
        self, client, admin_headers, seeded, inventory, tmp_path, app_config
    ):
        """Revalidating should cost a 304, not the image again."""
        photo = self.stored_photo(seeded, inventory, tmp_path, app_config)
        response = client.get(
            f"/api/items/{inventory[0].id}/photos/{photo.id}", headers=admin_headers
        )
        assert response.headers.get("etag")
        assert response.headers.get("last-modified")


def _one_pixel_png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("L", (2, 2), 255).save(buffer, format="PNG")
    return buffer.getvalue()
