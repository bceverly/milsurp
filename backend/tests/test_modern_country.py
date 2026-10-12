"""A listing's country, when what the rules read was the shop talking
(scan_service.modern_country). Found 2026-10-12: a Taurus PT111 and a Zastava
M70A filed under United States from their descriptions' terms of sale."""

from __future__ import annotations

from app.models import ArmoryStatus, FirearmModel, Item, Manufacturer, Site
from app.services import scan_service


def _world(
    session,
    *,
    modern=False,
    title="Taurus PT111 Pro 9mm",
    source="derived",
    country="United States",
):
    taurus = Manufacturer(name="Taurus", country="Brazil", status=ArmoryStatus.APPROVED)
    model = FirearmModel(
        name="PT111", country="Brazil", status=ArmoryStatus.APPROVED, modern_production=modern
    )
    model.manufacturers = [taurus]
    site = Site(slug="mc", name="Shop MC", base_url="https://mc.test/")
    session.add_all([taurus, model, site])
    session.flush()
    item = Item(
        site_id=site.id,
        external_key="k",
        url="https://mc.test/k",
        title=title,
        manufacturer="Taurus",
        country=country,
        country_source=source,
        firearm_model_id=model.id,
        is_pistol=True,
    )
    session.add(item)
    session.commit()
    return item


class TestTheShopTalking:
    def test_a_modern_gun_takes_its_models_country(self, clean_db):
        item = _world(clean_db, modern=True)
        assert scan_service.modern_country(clean_db, item)
        assert (item.country, item.country_source) == ("Brazil", "catalog")

    def test_united_states_from_the_description_alone_gives_way(self, clean_db):
        item = _world(clean_db, modern=False)
        assert scan_service.modern_country(clean_db, item)
        assert item.country == "Brazil"

    def test_but_a_title_saying_so_still_wins(self, clean_db):
        item = _world(clean_db, title="US Contract Taurus PT111")
        assert not scan_service.modern_country(clean_db, item)
        assert item.country == "United States"

    def test_and_so_does_the_vendor(self, clean_db):
        item = _world(clean_db, modern=True, source="vendor")
        assert not scan_service.modern_country(clean_db, item)
        assert item.country == "United States"

    def test_another_country_from_the_text_is_left_alone(self, clean_db):
        """A K98k assembled in Brno is a German pattern made in Czechoslovakia,
        and its listing saying so is the listing's word."""
        item = _world(clean_db, country="Czech Republic")
        assert not scan_service.modern_country(clean_db, item)
