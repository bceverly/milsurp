"""Modern production, and the maker's page one click from a listing.

Slice 1 of "New-gun prices, and the makers' own pages" in ROADMAP.md, asked
for on 2026-10-10: a reader looking at a used carry gun was searching Google
for the maker's page by hand.
"""

from __future__ import annotations

import pytest
import yaml

from app.models import ArmoryStatus, FirearmModel, Item, Manufacturer, Site
from app.services import armory, makerlink


def _gun(
    session,
    *,
    modern=True,
    maker_url=None,
    website="https://www.taurususa.com",
    listing_maker="Taurus",
):
    taurus = Manufacturer(name="Taurus", website=website, status=ArmoryStatus.APPROVED)
    tracker = FirearmModel(
        name="Tracker",
        status=ArmoryStatus.APPROVED,
        modern_production=modern,
        maker_url=maker_url,
    )
    tracker.manufacturers = [taurus]
    site = Site(slug="mp", name="Shop MP", base_url="https://mp.test/")
    session.add_all([taurus, tracker, site])
    session.flush()
    item = Item(
        site_id=site.id,
        external_key="t",
        url="https://mp.test/t",
        title="TAURUS TRACKER M44 PRE OWNED",
        manufacturer=listing_maker,
        is_pistol=True,
        current_price=399.0,
        firearm_model_id=tracker.id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


class TestTheLink:
    def test_without_a_page_it_searches_the_makers_own_site(self, clean_db):
        link = makerlink.for_item(clean_db, _gun(clean_db))
        assert link.kind == "search"
        assert link.site == "taurususa.com"
        assert link.url == "https://www.google.com/search?q=site%3Ataurususa.com+Tracker"
        assert link.maker == "Taurus"

    def test_the_models_own_page_wins(self, clean_db):
        page = "https://www.taurususa.com/revolvers/tracker"
        link = makerlink.for_item(clean_db, _gun(clean_db, maker_url=page))
        assert (link.kind, link.url, link.site) == ("page", page, "taurususa.com")

    def test_nothing_for_a_gun_no_longer_made(self, clean_db):
        assert makerlink.for_item(clean_db, _gun(clean_db, modern=False)) is None

    def test_nothing_when_nobody_knows_the_makers_site(self, clean_db):
        assert makerlink.for_item(clean_db, _gun(clean_db, website=None)) is None

    def test_the_listings_own_maker_is_the_one_searched(self, clean_db):
        item = _gun(clean_db, listing_maker="Rossi")
        rossi = Manufacturer(name="Rossi", website="rossiusa.com", status=ArmoryStatus.APPROVED)
        clean_db.add(rossi)
        item.firearm_model.manufacturers.append(rossi)
        clean_db.commit()
        assert makerlink.for_item(clean_db, item).site == "rossiusa.com"

    def test_a_model_with_no_maker_uses_the_one_the_listing_names(self, clean_db):
        """ "KAHR CW9 PRE OWNED" approved a "CW9" that knows nothing of Kahr."""
        item = _gun(clean_db)
        item.firearm_model.manufacturers = []
        clean_db.commit()
        assert makerlink.for_item(clean_db, item).site == "taurususa.com"


class TestTheArmoryEditsIt:
    def test_a_makers_website_is_taken_as_an_address(self, client, admin_headers):
        made = client.post(
            "/api/manufacturers",
            json={"name": "Web Arms", "website": "  webarms.example  "},
            headers=admin_headers,
        ).json()["manufacturer"]
        assert made["website"] == "https://webarms.example"
        cleared = client.patch(
            f"/api/manufacturers/{made['id']}", json={"website": ""}, headers=admin_headers
        ).json()["manufacturer"]
        assert cleared["website"] is None

    @pytest.mark.parametrize("bad", ["javascript:alert(1)", "not a site", "ftp://x.example"])
    def test_and_nonsense_is_refused(self, client, admin_headers, bad):
        response = client.post(
            "/api/manufacturers", json={"name": "Bad Arms", "website": bad}, headers=admin_headers
        )
        assert response.status_code == 422

    def test_a_model_is_flagged_and_given_its_page(self, client, admin_headers):
        made = client.post(
            "/api/armory/models", json={"name": "Test Carry 9"}, headers=admin_headers
        ).json()
        changed = client.patch(
            f"/api/armory/models/{made['id']}",
            json={"modern_production": True, "maker_url": "maker.example/carry9"},
            headers=admin_headers,
        ).json()["model"]
        assert (changed["modern_production"], changed["maker_url"]) == (
            True,
            "https://maker.example/carry9",
        )

    def test_the_listing_carries_the_link(self, client, admin_headers, clean_db):
        item = _gun(clean_db)
        shown = client.get(f"/api/items/{item.id}", headers=admin_headers).json()
        assert shown["maker_link"]["kind"] == "search"
        assert shown["maker_link"]["site"] == "taurususa.com"


class TestTheShippedFileCarriesIt:
    def test_the_flag_the_page_and_the_website_make_the_round_trip(self, clean_db, tmp_path):
        _gun(clean_db, maker_url="https://www.taurususa.com/revolvers/tracker")
        path = tmp_path / "armory.yaml"
        armory.write_export(clean_db, path)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        model = next(m for m in written["models"] if m["name"] == "Tracker")
        maker = next(m for m in written["manufacturers"] if m["name"] == "Taurus")
        assert model["modern_production"] is True
        assert model["maker_url"] == "https://www.taurususa.com/revolvers/tracker"
        assert maker["website"] == "https://www.taurususa.com"
        # Settled, so the same file plans nothing.
        assert not armory.plan_sync(clean_db, path)

    def test_a_sync_sets_them(self, clean_db, tmp_path):
        _gun(clean_db, modern=False, website=None)
        path = tmp_path / "armory.yaml"
        armory.write_export(clean_db, path)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        next(m for m in written["models"] if m["name"] == "Tracker")["modern_production"] = True
        next(m for m in written["manufacturers"] if m["name"] == "Taurus")[
            "website"
        ] = "https://www.taurususa.com"
        path.write_text(yaml.safe_dump(written), encoding="utf-8")
        plan = armory.plan_sync(clean_db, path)
        assert [c.fields for c in plan.models] == [["modern_production"]]
        assert [c.fields for c in plan.manufacturers] == [["website"]]
        armory.apply_sync(clean_db, path)
        clean_db.commit()
        tracker = clean_db.query(FirearmModel).filter_by(name="Tracker").one()
        assert tracker.modern_production is True
