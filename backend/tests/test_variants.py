"""Variants under a model, and the barrel and finish a listing states.

Slice 2 of "New-gun prices, and the makers' own pages" (ROADMAP.md): a model
is a design, a variant a product within it, and a listing is narrowed to its
variant by caliber, barrel and finish -- linked only when that leaves one.
"""

from __future__ import annotations

import pytest
import yaml

from app.models import ArmoryStatus, Caliber, FirearmModel, Item, ModelVariant, Site
from app.services import armory, variants


class TestReadingTheTitle:
    @pytest.mark.parametrize(
        ("title", "barrel", "finish"),
        [
            ('Used RUGER SP101 357MAG 3" STS VG GTO392276', 3.0, "Stainless"),
            ('Used S&W 36 38SPL J353573 1.875" BLUED VG', 1.875, "Blued"),
            ('Used GLOCK 19V 9X19 4" MATTE G GTO392819', 4.0, "Black"),
            ("KAHR CW9 TWO TONE PRE OWNED (1143227)", None, "Two-tone"),
            ('Used SPRINGFIELD EMP 4 9MM 4" FDE VG', 4.0, "FDE"),
            ("LEO Trade-In Zastava M83 2in .357 Magnum Revolver- Black", 2.0, "Black"),
            ("TAURUS TRACKER M44 PRE OWNED", None, None),
        ],
    )
    def test_barrel_and_finish(self, title, barrel, finish):
        assert variants.read_barrel(title) == barrel
        assert variants.read_finish(title) == finish

    def test_a_long_guns_barrel(self):
        assert variants.read_barrel('Mossberg 500 12ga 18.5" Parkerized', long_gun=True) == 18.5
        assert variants.read_finish("Mossberg 500 Parkerized") == "Parkerized"

    def test_two_tone_before_black_and_stainless_before_ss(self):
        assert variants.read_finish("SCCY CPX-2 BLACK/STAINLESS TWO TONE") == "Two-tone"
        assert variants.normalize_finish("matte black") == "Black"
        assert variants.normalize_finish("Stainless") == "Stainless"


@pytest.fixture
def tracker(clean_db):
    magnum = Caliber(name=".44 Magnum", status=ArmoryStatus.APPROVED)
    model = FirearmModel(name="Tracker", status=ArmoryStatus.APPROVED, modern_production=True)
    model.calibers = [magnum]
    clean_db.add_all([magnum, model])
    clean_db.flush()
    for label, barrel, finish in (
        ('Tracker .44 Magnum 4" Black', 4.0, "Black"),
        ('Tracker .44 Magnum 4" Stainless', 4.0, "Stainless"),
        ('Tracker .44 Magnum 6.5" Black', 6.5, "Black"),
    ):
        clean_db.add(
            ModelVariant(
                model_id=model.id,
                label=label,
                caliber_id=magnum.id,
                barrel_inches=barrel,
                finish=finish,
                status=ArmoryStatus.APPROVED,
            )
        )
    site = Site(slug="vt", name="Shop VT", base_url="https://vt.test/")
    clean_db.add(site)
    clean_db.commit()
    return clean_db, model, site


def listing(session, model, site, title, key="t"):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"https://vt.test/{key}",
        title=title,
        caliber=".44 Magnum",
        is_pistol=True,
        firearm_model_id=model.id,
    )
    session.add(item)
    session.flush()
    session.refresh(item)
    variants.settle(session, item)
    session.commit()
    return item


class TestNarrowing:
    def test_barrel_and_finish_narrow_to_one(self, tracker):
        session, model, site = tracker
        item = listing(session, model, site, 'Used TAURUS TRACKER 44MAG 4" STAINLESS G')
        assert session.get(ModelVariant, item.variant_id).label == 'Tracker .44 Magnum 4" Stainless'

    def test_a_vague_title_narrows_to_several_and_links_none(self, tracker):
        session, model, site = tracker
        item = listing(session, model, site, "TAURUS TRACKER M44 PRE OWNED")
        assert item.variant_id is None
        assert len(variants.candidates(session, item)) == 3

    def test_a_barrel_no_variant_has_matches_none(self, tracker):
        session, model, site = tracker
        item = listing(session, model, site, 'Used TAURUS TRACKER 44MAG 2.5" BLUED')
        assert variants.candidates(session, item) == []

    def test_a_model_no_longer_made_has_no_variant_but_has_its_barrel(self, tracker):
        """Its barrel read since 2026-10-13, as every gun's is (services/barrels);
        a variant still only for a model in production."""
        session, model, site = tracker
        model.modern_production = False
        session.commit()
        item = listing(session, model, site, 'Used TAURUS TRACKER 44MAG 4" STAINLESS')
        assert (item.variant_id, item.barrel_inches, item.finish) == (None, 4.0, None)


class TestTheArmoryEditsThem:
    def test_adding_a_variant_matches_the_listings_at_once(self, tracker, client, admin_headers):
        session, model, site = tracker
        item = listing(session, model, site, 'Used TAURUS TRACKER 44MAG 2.5" BLUED')
        made = client.post(
            f"/api/armory/models/{model.id}/variants",
            json={
                "label": 'Tracker .44 Magnum 2.5" Blued',
                "barrel_inches": 2.5,
                "finish": "blued",
                "upc": "725327351238",
                "msrp": 549.99,
                "status": "approved",
            },
            headers=admin_headers,
        )
        assert made.status_code == 201, made.text
        assert made.json()["finish"] == "Blued"
        session.expire_all()
        assert session.get(Item, item.id).variant_id == made.json()["id"]

        shown = client.get(f"/api/items/{item.id}", headers=admin_headers).json()
        assert shown["variant"]["msrp"] == 549.99
        assert (shown["barrel_inches"], shown["finish"]) == (2.5, "Blued")

        client.delete(f"/api/armory/variants/{made.json()['id']}", headers=admin_headers)
        session.expire_all()
        assert session.get(Item, item.id).variant_id is None

    def test_the_list_names_each_variants_caliber(self, tracker, client, admin_headers):
        """A 500 in production on 2026-10-13: the first variants with a caliber
        were the manufacturers' sites', and the dialog could not list them."""
        _session, model, _site = tracker
        listed = client.get(f"/api/armory/models/{model.id}/variants", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        assert {row["caliber"] for row in listed.json()} == {".44 Magnum"}

    def test_an_unknown_finish_is_refused(self, tracker, client, admin_headers):
        _session, model, _site = tracker
        response = client.post(
            f"/api/armory/models/{model.id}/variants",
            json={"label": "Tracker plaid", "finish": "plaid"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_a_vague_listing_shows_its_candidates(self, tracker, client, admin_headers):
        session, model, site = tracker
        item = listing(session, model, site, "TAURUS TRACKER M44 PRE OWNED")
        shown = client.get(f"/api/items/{item.id}", headers=admin_headers).json()
        assert shown["variant"] is None
        assert len(shown["variant_candidates"]) == 3


class TestTheShippedFileCarriesThem:
    def test_variants_make_the_round_trip(self, tracker, tmp_path):
        session, model, _site = tracker
        path = tmp_path / "armory.yaml"
        armory.write_export(session, path)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        entry = next(m for m in written["models"] if m["name"] == "Tracker")
        assert {v["label"] for v in entry["variants"]} == {
            'Tracker .44 Magnum 4" Black',
            'Tracker .44 Magnum 4" Stainless',
            'Tracker .44 Magnum 6.5" Black',
        }
        assert not armory.plan_sync(session, path)

        entry["variants"] = [v for v in entry["variants"] if "6.5" not in v["label"]]
        entry["variants"][0]["msrp"] = 529.99
        path.write_text(yaml.safe_dump(written), encoding="utf-8")
        [change] = armory.plan_sync(session, path).models
        assert change.fields == ["variants"]
        kept = {v.label: v.id for v in model.variants}
        armory.apply_sync(session, path)
        session.commit()
        session.refresh(model)
        assert {v.label for v in model.variants} == set(kept) - {'Tracker .44 Magnum 6.5" Black'}
        # Matched by label and kept, not replaced.
        assert all(kept[v.label] == v.id for v in model.variants)


class TestTheVariantsTab:
    """Every model's variants on one tab, approved or switched off in bulk
    (asked for on 2026-10-14: "shouldn't that be on its own tab?")."""

    def test_the_views_search_and_bulk_actions(self, tracker, client, admin_headers):
        session, model, _site = tracker
        for row in model.variants:
            row.status = ArmoryStatus.PENDING
        session.commit()

        def listed(status="pending", **params):
            response = client.get(
                "/api/armory/variants", params={"status": status, **params}, headers=admin_headers
            )
            assert response.status_code == 200, response.text
            return response.json()

        waiting = listed()
        assert len(waiting) == 3
        assert {row["model_name"] for row in waiting} == {"Tracker"}
        assert [row["label"] for row in listed(search="6.5")] == ['Tracker .44 Magnum 6.5" Black']

        ids = [row["id"] for row in waiting]
        done = client.post(
            "/api/armory/variants/approve", json={"ids": ids[:2]}, headers=admin_headers
        ).json()
        assert done["changed"] == 2
        assert len(listed()) == 1
        assert len(listed("approved")) == 2

        off = client.post(
            "/api/armory/variants/disable", json={"ids": ids[2:]}, headers=admin_headers
        ).json()
        assert off["changed"] == 1
        assert listed() == []
        assert [row["id"] for row in listed("disabled")] == ids[2:]
        assert len(listed("")) == 3

    def test_an_unknown_view_is_refused(self, tracker, client, admin_headers):
        response = client.get(
            "/api/armory/variants", params={"status": "maybe"}, headers=admin_headers
        )
        assert response.status_code == 422
