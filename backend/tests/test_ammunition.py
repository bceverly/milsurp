"""What it costs to shoot a caliber (app.services.ammunition).

"Ammunition" in ROADMAP.md, asked for on 2026-10-11. Recorded that day: the
7.62x54mmR Wikipedia article's wikitext; AmmoSeek's caliber list, its
7.62x54R page and that page's results, its bullets search form and the .311"
bullets; Milsurp Munitions' Store API products; and the first page of Lee
Precision's rifle dies.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from app.models import AmmoSetting, ArmoryStatus, Caliber, Item, Site, utcnow
from app.scrapers.base import ScrapeError
from app.services import ammunition, wikipedia

PAGES = Path(__file__).parent / "fixtures" / "ammo"


def page(name):
    raw = gzip.decompress((PAGES / name).read_bytes())
    return raw.decode("latin-1" if name.endswith(".html.gz") else "utf-8")


def recorded(name):
    return json.loads(page(name))


ARTICLE = recorded("wikipedia-7.62x54mmR.json.gz")["parse"]["wikitext"]


class TestTheArticle:
    def test_diameter_and_weights_from_the_infobox(self):
        found = ammunition.article_facts(ARTICLE)
        # 7.92 mm, stated metric; the weights in grams, 11.3/11.7/9.7.
        assert found.diameter_in == 0.3118
        assert found.grains == [150.0, 174.0, 181.0]

    def test_an_infobox_in_inches_and_grains(self):
        text = "{{Infobox firearm cartridge |bullet=.355 in |bw1=115 |bw2=124 gr |bw3=147}}"
        found = ammunition.article_facts(text)
        assert (found.diameter_in, found.grains) == (0.355, [115.0, 124.0, 147.0])

    def test_no_infobox_says_nothing(self):
        assert ammunition.article_facts("An article about a town.") == ammunition.ArticleFacts(
            None, []
        )

    def test_a_cartridge_title_names_the_caliber_written_either_way(self):
        assert wikipedia.names_cartridge("7.62×54mmR", ["7.62x54R"])
        assert wikipedia.names_cartridge(".303 British", [".303 British"])
        assert not wikipedia.names_cartridge("7.62×39mm", ["7.62x54R"])


class TestAmmoSeek:
    def test_the_cheapest_round_at_each_weight(self):
        offers = ammunition.ammoseek_offers(recorded("ammoseek-7.62x54r.json.gz"))
        found = ammunition.lows(offers, [150, 174, 181])
        # 148 gr counts as 150; nothing within 3% of 174 is offered; the three
        # "46 grain" listings are nobody's weight and are not counted at all.
        assert found == {150: 0.5437, 181: 0.7993}

    def test_with_no_weights_the_most_offered_one_stands_in(self):
        offers = ammunition.ammoseek_offers(recorded("ammoseek-7.62x54r.json.gz"))
        assert ammunition.lows(offers, []) == {148.0: 0.5437}

    def test_a_caliber_page_and_its_query(self):
        calibers = ammunition.ammoseek_calibers(page("ammoseek-calibers.html.gz"))
        assert (
            "/ammo/7.7x58mm",
            ["7.7 Japanese", "7.7x58mm", "7.7 Arisaka", "7.7x58 Arisaka"],
        ) in (calibers)
        assert ammunition.query_of(page("ammoseek-7.62x54r.html.gz")) == (
            "gun=rifle&cal=277&ekw=&seo_name=7.62x54r&ikw=&sort="
        )

    def test_bullets_by_diameter(self):
        options = ammunition.bullet_calibers(page("ammoseek-bullets-form.html.gz"))
        assert ammunition.nearest_bullet(options, 0.3118) == "573"  # .312"
        assert ammunition.nearest_bullet(options, 0.311) == "560"
        assert ammunition.nearest_bullet(options, 0.02) is None
        bullets = ammunition.ammoseek_offers(recorded("ammoseek-bullets-311.json.gz"))
        assert ammunition.lows(bullets, [150, 174, 181]) == {150: 0.196, 174: 0.2732, 181: 0.2695}


class TestTheOtherSources:
    def test_milsurp_munitions_box_price_over_rounds(self):
        found = dict(ammunition.milsurp_offers(recorded("milsurp-munitions-products.json.gz")))
        mannlicher = found["8x50R Mannlicher (205gr SP)"]
        assert (mannlicher.grains, mannlicher.price, mannlicher.rounds) == (205.0, 59.95, 20)
        assert round(mannlicher.each, 4) == 2.9975
        # Merchandise names no rounds and is not a load.
        assert not any("Sticker" in name for name in found)

    def test_lee_die_sets_by_cartridge(self):
        found = dict(ammunition.lee_dies(page("lee-rifle-dies-1.html.gz")))
        assert found["223 Remington"] == "https://leeprecision.com/223-remington-dies"
        assert len(found) == 48


class RecordedSites:
    """AmmoSeek, Milsurp Munitions and Lee as recorded, for a whole refresh."""

    def __init__(self):
        self.asked = []

    def keep_at_least(self, *_args):
        pass

    def get_text(self, url, **_kwargs):
        self.asked.append(("GET", url))
        if url.startswith(ammunition.LEE):
            if "rifle-dies" in url and "pagenumber=1" in url:
                return page("lee-rifle-dies-1.html.gz")
            return "<html></html>"
        if url == ammunition.AMMOSEEK + "calibers/":
            return page("ammoseek-calibers.html.gz")
        if url == ammunition.AMMOSEEK + "ammo/7.62x54r":
            return page("ammoseek-7.62x54r.html.gz")
        if "type1_genform" in url:
            return page("ammoseek-bullets-form.html.gz")
        if url.startswith(ammunition.MILSURP_MUNITIONS):
            return page("milsurp-munitions-products.json.gz")
        raise ScrapeError(f"GET {url}: not recorded")

    def post(self, url, data, **_kwargs):
        self.asked.append(("POST", url, data))
        name = (
            "ammoseek-bullets-311.json.gz"
            if data.get("reloading_type") == "bullets"
            else "ammoseek-7.62x54r.json.gz"
        )

        class Answer:
            def json(self):
                return recorded(name)

        return Answer()


def fake_wikipedia(params):
    if params.get("action") == "parse":
        return {"parse": {"wikitext": ARTICLE}}
    return {"query": {"search": [], "pages": []}}


@pytest.fixture
def mosin_round(clean_db):
    cartridge = Caliber(
        name="7.62x54R",
        aliases="7.62x54mmR",
        status=ArmoryStatus.APPROVED,
        wikipedia_url="https://en.wikipedia.org/wiki/7.62%C3%9754mmR",
    )
    lonely = Caliber(name="223 Remington", status=ArmoryStatus.APPROVED)
    site = Site(slug="am", name="Shop AM", base_url="https://am.test/")
    clean_db.add_all([cartridge, lonely, site])
    clean_db.flush()
    clean_db.add(
        Item(
            site_id=site.id,
            external_key="m",
            url="https://am.test/m",
            title="Mosin-Nagant 91/30",
            caliber="7.62x54R",
            is_rifle=True,
            is_active=True,
            is_sold=False,
        )
    )
    clean_db.commit()
    return cartridge


class TestARefresh:
    def test_reads_the_article_then_prices_what_is_for_sale(self, clean_db, mosin_round):
        sites = RecordedSites()
        summary = ammunition.refresh(clean_db, sites, fetch=fake_wikipedia, log=lambda _m: None)
        clean_db.refresh(mosin_round)
        assert mosin_round.bullet_diameter_in == 0.3118
        assert [w.grains for w in mosin_round.bullet_weights] == [150.0, 174.0, 181.0]
        # The average of 54.37 cents and 79.93 cents; 174 gr had no offer.
        assert mosin_round.factory_cpr == round((0.5437 + 0.7993) / 2, 4)
        assert (mosin_round.factory_source, mosin_round.factory_url) == (
            "ammoseek",
            "https://ammoseek.com/ammo/7.62x54r",
        )
        by_weight = {w.grains: w for w in mosin_round.bullet_weights}
        assert by_weight[174.0].factory_cpr is None
        assert by_weight[150.0].projectile_cost == 0.196
        assert mosin_round.projectile_cost == round((0.196 + 0.2732 + 0.2695) / 3, 4)
        # Lee's catalog said nothing of 7.62x54R on the recorded page.
        assert mosin_round.lee_dies is False
        lonely = clean_db.query(Caliber).filter_by(name="223 Remington").one()
        assert (lonely.lee_dies, lonely.lee_url) == (
            True,
            "https://leeprecision.com/223-remington-dies",
        )
        # Not for sale here, so not priced.
        assert lonely.factory_checked_at is None
        assert "1 calibers for sale: 1 with factory prices, 1 with projectile prices" in summary
        row = clean_db.get(AmmoSetting, 1)
        assert (row.last_status, row.requested_at) == ("ok", None)

    def test_ammoseek_query_is_found_once_and_kept(self, clean_db, mosin_round):
        ammunition.refresh(clean_db, RecordedSites(), log=lambda _m: None)
        sites = RecordedSites()
        ammunition.refresh(clean_db, sites, log=lambda _m: None)
        assert ("GET", ammunition.AMMOSEEK + "ammo/7.62x54r") not in sites.asked

    def test_where_ammoseek_has_nothing_milsurp_munitions_is_asked(self, clean_db):
        mannlicher = Caliber(name="8x50R Mannlicher", status=ArmoryStatus.APPROVED)
        site = Site(slug="mm", name="Shop MM", base_url="https://mm.test/")
        clean_db.add_all([mannlicher, site])
        clean_db.flush()
        clean_db.add(
            Item(
                site_id=site.id,
                external_key="s",
                url="https://mm.test/s",
                title="Steyr M95",
                caliber="8x50R Mannlicher",
                is_rifle=True,
                is_active=True,
                is_sold=False,
            )
        )
        clean_db.commit()
        ammunition.refresh(clean_db, RecordedSites(), log=lambda _m: None)
        clean_db.refresh(mannlicher)
        assert (mannlicher.factory_cpr, mannlicher.factory_source) == (2.9975, "milsurp-munitions")


class TestWhenARefreshIsDue:
    def test_never_run_is_due_and_then_not_until_its_frequency(self, clean_db):
        assert ammunition.is_due(clean_db)
        row = ammunition.settings(clean_db)
        row.last_run_at = utcnow()
        clean_db.commit()
        assert not ammunition.is_due(clean_db)
        row.requested_at = utcnow()
        clean_db.commit()
        assert ammunition.is_due(clean_db)


class TestThePanelAndTheSettings:
    def test_any_reader_sees_a_calibers_ammunition(
        self, client, normal_user, mosin_round, clean_db
    ):
        mosin_round.factory_cpr = 0.6715
        mosin_round.lee_dies = True
        ammunition.set_weights(mosin_round, [150.0, 181.0])
        clean_db.commit()
        shown = client.get(
            "/api/ammunition", params={"caliber": "7.62x54mmR"}, headers=normal_user["headers"]
        )
        assert shown.status_code == 200, shown.text
        body = shown.json()
        assert (body["caliber"], body["factory_cpr"], body["lee_dies"]) == (
            "7.62x54R",
            0.6715,
            True,
        )
        assert [w["grains"] for w in body["bullet_weights"]] == [150.0, 181.0]
        missing = client.get(
            "/api/ammunition", params={"caliber": "nonesuch"}, headers=normal_user["headers"]
        )
        assert missing.status_code == 404

    def test_the_frequency_is_daily_weekly_or_fortnightly(self, client, admin_headers, clean_db):
        shown = client.get("/api/ammunition/settings", headers=admin_headers).json()
        assert shown["refresh_days"] == 7
        assert shown["choices"] == {"1": "Daily", "7": "Weekly", "14": "Every 2 weeks"}
        assert (
            client.patch(
                "/api/ammunition/settings", json={"refresh_days": 3}, headers=admin_headers
            ).status_code
            == 422
        )
        changed = client.patch(
            "/api/ammunition/settings", json={"refresh_days": 14}, headers=admin_headers
        )
        assert changed.json()["refresh_days"] == 14

    def test_refresh_now_asks_the_scheduler(self, client, admin_headers, clean_db):
        asked = client.post("/api/ammunition/refresh", headers=admin_headers).json()
        assert asked["requested_at"] is not None
        assert ammunition.is_due(clean_db)

    def test_only_an_administrator_sets_them(self, client, normal_user):
        assert (
            client.get("/api/ammunition/settings", headers=normal_user["headers"]).status_code
            == 403
        )


class TestEditingACaliber:
    def test_an_edit_has_its_article_read_again(self, client, admin_headers, mosin_round, clean_db):
        mosin_round.wikipedia_read_at = utcnow()
        clean_db.commit()
        response = client.patch(
            f"/api/armory/calibers/{mosin_round.id}",
            json={"bullet_diameter_in": 0.311},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        clean_db.expire_all()
        row = clean_db.get(Caliber, mosin_round.id)
        assert (row.bullet_diameter_in, row.wikipedia_read_at) == (0.311, None)
