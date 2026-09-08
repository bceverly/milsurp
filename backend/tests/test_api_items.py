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

    def test_other_excludes_the_kinds_named_above_it(self, client, admin_headers, inventory):
        """ "Parts & accessories" has to stop meaning "including the bayonets
        and parts kits listed as their own options", or the filter list reads
        as overlapping piles."""
        page = client.get("/api/items?kind=other", headers=admin_headers).json()
        for item in page["items"]:
            assert not item["is_rifle"] and not item["is_pistol"]
            assert not item["is_bayonet"] and not item["is_parts_kit"]

    def test_a_list_row_carries_a_truncated_blurb(self, client, admin_headers, inventory):
        """The list view needs some description; a page of 192 full ones is
        not a reasonable way to render two lines each."""
        page = client.get("/api/items", headers=admin_headers).json()
        for item in page["items"]:
            assert "blurb" in item
            if item["blurb"]:
                assert len(item["blurb"]) <= 281

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


class TestTheTypeCounts:
    """What each Type would show, next to the radio that chooses it."""

    def counts(self, client, headers, query=""):
        body = client.get(f"/api/items{query}", headers=headers).json()
        return {k["value"]: k["count"] for k in body["facets"]["kinds"]}

    def test_one_per_type_plus_anything(self, client, admin_headers, inventory):
        counts = self.counts(client, admin_headers)
        assert set(counts) == {"", "rifle", "pistol", "bayonet", "parts_kit", "other"}
        assert counts["rifle"] == 3
        assert counts["pistol"] == 1

    def test_anything_is_the_whole_set(self, client, admin_headers, inventory):
        """The five partition it, so the sum is the total and not a sixth count
        that could drift away from the rows on the page."""
        counts = self.counts(client, admin_headers)
        named = sum(counts[k] for k in ("rifle", "pistol", "bayonet", "parts_kit", "other"))
        assert counts[""] == named
        assert counts[""] == client.get("/api/items", headers=admin_headers).json()["total"]

    def test_choosing_a_type_does_not_change_them(self, client, admin_headers, inventory):
        """Otherwise picking Rifles would report zero handguns, and the numbers
        would only ever describe the choice already made."""
        assert self.counts(client, admin_headers, "?kind=rifle") == self.counts(
            client, admin_headers
        )

    def test_but_every_other_filter_does(self, client, admin_headers, inventory):
        """They say what picking a Type would give *here*, so the rest of the
        sidebar still applies."""
        counts = self.counts(client, admin_headers, "?country=Germany")
        assert counts["rifle"] == 1
        assert counts["pistol"] == 1
        assert counts[""] == 2


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


class TestUnknownIsAFilterValue:
    """A listing nothing could be worked out for should still be findable.

    Otherwise the ones the heuristics fail on are exactly the ones nobody can
    see, which is the wrong way round: they are the ones worth looking at.

    The column stays NULL. "Unknown" is this view's word for an empty field,
    not a value written into the row — writing it would make it
    indistinguishable from a vendor of that name and would quietly stop every
    "fill in the blanks" rule in the application, all of which key on the field
    being empty.
    """

    @pytest.fixture
    def catalog(self, seeded):
        site = seeded.query(Site).first()
        for key, maker, caliber in [
            ("a", "Mauser", "8mm Mauser"),
            ("b", "Mauser", "8mm Mauser"),
            ("c", None, None),
            ("d", None, "7.62x54R"),
        ]:
            seeded.add(
                Item(
                    site_id=site.id,
                    external_key=key,
                    url=f"https://example.test/{key}",
                    title=f"Rifle {key}",
                    manufacturer=maker,
                    caliber=caliber,
                    is_active=True,
                    first_seen_at=utcnow(),
                    last_seen_at=utcnow(),
                )
            )
        seeded.commit()
        return seeded

    def facet(self, client, headers, name):
        return client.get("/api/items", headers=headers).json()["facets"][name]

    def test_the_unknowns_are_counted(self, client, admin_headers, catalog):
        makers = self.facet(client, admin_headers, "manufacturers")
        assert {"value": "Unknown", "label": None, "count": 2} in [
            {"value": m["value"], "label": m.get("label"), "count": m["count"]} for m in makers
        ]

    def test_it_is_listed_last(self, client, admin_headers, catalog):
        """It is not an answer and should not sit at the top looking like one."""
        makers = self.facet(client, admin_headers, "manufacturers")
        assert makers[-1]["value"] == "Unknown"

    def test_choosing_it_returns_exactly_those_listings(self, client, admin_headers, catalog):
        response = client.get("/api/items?manufacturer=Unknown", headers=admin_headers)
        titles = {item["title"] for item in response.json()["items"]}
        assert titles == {"Rifle c", "Rifle d"}

    def test_a_real_maker_still_filters_normally(self, client, admin_headers, catalog):
        response = client.get("/api/items?manufacturer=Mauser", headers=admin_headers)
        assert {item["title"] for item in response.json()["items"]} == {"Rifle a", "Rifle b"}

    def test_it_combines_with_a_real_maker(self, client, admin_headers, catalog):
        response = client.get(
            "/api/items?manufacturer=Mauser&manufacturer=Unknown", headers=admin_headers
        )
        assert len(response.json()["items"]) == 4

    def test_the_other_fields_have_one_too(self, client, admin_headers, catalog):
        """A filter where one field admits Unknown and the others do not would
        be a puzzle rather than a feature."""
        assert any(v["value"] == "Unknown" for v in self.facet(client, admin_headers, "calibers"))
        response = client.get("/api/items?caliber=Unknown", headers=admin_headers)
        assert {item["title"] for item in response.json()["items"]} == {"Rifle c"}

    def test_no_bucket_when_nothing_is_missing(self, client, admin_headers, seeded):
        site = seeded.query(Site).first()
        seeded.add(
            Item(
                site_id=site.id,
                external_key="only",
                url="https://example.test/only",
                title="Rifle",
                manufacturer="Mauser",
                is_active=True,
                first_seen_at=utcnow(),
                last_seen_at=utcnow(),
            )
        )
        seeded.commit()

        makers = self.facet(client, admin_headers, "manufacturers")
        assert all(m["value"] != "Unknown" for m in makers)


class TestStaticAssetsCannotEscapeTheBuild:
    """The frontend catch-all serves files by path from the request.

    CodeQL flagged it, and the shape it objected to was real: the path was
    joined first and checked afterwards. Both orders reject a traversal, but
    only validating first never constructs the path at all.
    """

    @pytest.mark.parametrize(
        "requested",
        [
            "../../../etc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "assets/../../etc/passwd",
            "/etc/passwd",
            "assets/../../../secrets.yaml",
            ".",
            "..",
            "a//b",
        ],
    )
    def test_a_traversal_names_nothing(self, requested):
        from app.main import _asset_path

        assert _asset_path(requested) is None

    def test_and_neither_does_an_empty_request(self):
        from app.main import _asset_path

        assert _asset_path("") is None

    def test_a_real_asset_resolves(self, tmp_path, monkeypatch):
        import app.main as main

        (tmp_path / "assets").mkdir()
        built = tmp_path / "assets" / "index-abc123.js"
        built.write_text("console.log(1)")
        monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)

        assert main._asset_path("assets/index-abc123.js") == built.resolve()

    def test_a_directory_is_not_an_asset(self, tmp_path, monkeypatch):
        import app.main as main

        (tmp_path / "assets").mkdir()
        monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)

        assert main._asset_path("assets") is None

    def test_a_symlink_out_of_the_build_is_refused(self, tmp_path, monkeypatch):
        """The segment rules cannot see this one; the resolve check can."""
        import app.main as main

        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "escape.txt").symlink_to(outside)
        monkeypatch.setattr(main, "FRONTEND_DIST", dist)

        assert main._asset_path("escape.txt") is None


class TestSecretsAreJudgedNotPassedAround:
    """The function that logs about a secret is never given one."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("", "missing"),
            (None, "missing"),
            ("CHANGE-ME-please", "sample"),
            ("short", "short"),
            ("x" * 64, "ok"),
        ],
    )
    def test_the_verdict(self, value, expected):
        from app.main import inspect_secret

        assert inspect_secret(value).value == expected

    def test_the_verdict_carries_nothing_of_the_secret(self):
        """Not even its length, which is a hint about it."""
        from app.main import SecretHealth, inspect_secret

        assert set(SecretHealth) == {
            SecretHealth.OK,
            SecretHealth.MISSING,
            SecretHealth.SAMPLE,
            SecretHealth.SHORT,
        }
        assert inspect_secret("hunter2hunter2hunter2") in set(SecretHealth)


class TestTheArmoryIsVisible:
    """A listing names the model it matched, and you can filter on it.

    The armory has been shaping listings since it existed and doing all of it
    invisibly: nothing said *which* model a fill had come from, so a
    questionable caliber could not be traced and the M91/30s could not be
    browsed.
    """

    @pytest.fixture
    def garand(self, seeded, inventory):
        from app.models import ArmoryStatus, Caliber, FirearmKind, FirearmModel, Manufacturer

        maker = Manufacturer(name="Springfield")
        cartridge = Caliber(name=".30-06 Springfield", status=ArmoryStatus.APPROVED)
        model = FirearmModel(
            name="M1 Garand",
            kind=FirearmKind.RIFLE,
            status=ArmoryStatus.APPROVED,
            wikipedia_url="https://en.wikipedia.org/wiki/M1_Garand",
        )
        seeded.add_all([maker, cartridge, model])
        model.manufacturers = [maker]
        model.calibers = [cartridge]
        seeded.flush()
        inventory[0].firearm_model_id = model.id
        seeded.commit()
        return model

    def test_a_listing_names_its_model(self, client, admin_headers, garand, inventory):
        body = client.get("/api/items", headers=admin_headers).json()
        named = [row for row in body["items"] if row["model"]]
        assert [row["model"] for row in named] == ["M1 Garand"]
        assert named[0]["firearm_model_id"] == garand.id

    def test_the_detail_view_carries_what_the_armory_knows(
        self, client, admin_headers, garand, inventory
    ):
        body = client.get(f"/api/items/{inventory[0].id}", headers=admin_headers).json()
        assert body["model"] == "M1 Garand"
        assert body["model_kind"] == "rifle"
        assert body["model_makers"] == ["Springfield"]
        assert body["model_calibers"] == [".30-06 Springfield"]
        assert body["model_reference_url"].endswith("M1_Garand")

    def test_a_listing_with_no_match_says_nothing(self, client, admin_headers, inventory):
        body = client.get(f"/api/items/{inventory[1].id}", headers=admin_headers).json()
        assert body["model"] is None
        assert body["model_makers"] == []

    def test_the_models_are_a_facet(self, client, admin_headers, garand, inventory):
        facets = client.get("/api/items", headers=admin_headers).json()["facets"]
        assert [(f["label"], f["count"]) for f in facets["models"]] == [("M1 Garand", 1)]

    def test_and_a_filter(self, client, admin_headers, garand, inventory):
        body = client.get(f"/api/items?model={garand.id}", headers=admin_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["model"] == "M1 Garand"

    def test_the_filter_is_by_id_so_a_rename_keeps_its_listings(
        self, client, admin_headers, garand, seeded, inventory
    ):
        garand.name = "US Rifle, Cal. .30, M1"
        seeded.commit()
        body = client.get(f"/api/items?model={garand.id}", headers=admin_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["model"] == "US Rifle, Cal. .30, M1"
