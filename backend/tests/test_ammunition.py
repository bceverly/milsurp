"""What it costs to shoot a caliber (app.services.ammunition).

"Ammunition" in ROADMAP.md, asked for on 2026-10-11. Recorded that day: the
7.62x54mmR Wikipedia article's wikitext; Milsurp Munitions' Store API
products; and the first page of Lee Precision's rifle dies. Recorded on
2026-10-12, when AmmoSeek was replaced: Ammo.com's rifle category page, its
7.62x54R page and the first page of its 9mm; and the .311" and .312" bullets
from Graf & Sons' catalog, with the .308" ones it sells by the case.
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


class TestAmmoCom:
    def test_the_cheapest_round_at_each_weight(self):
        offers = ammunition.ammo_com_offers(page("ammocom-7.62x54r.html.gz"))
        assert len(offers) == 8
        # 148 gr counts as 150 and 180 gr as 181; the sale price is the price.
        assert ammunition.lows(offers, [150, 174, 181]) == {150: 0.625, 174: 1.7995, 181: 1.0495}

    def test_with_no_weights_the_most_offered_one_stands_in(self):
        offers = ammunition.ammo_com_offers(page("ammocom-7.62x54r.html.gz"))
        assert ammunition.lows(offers, []) == {148.0: 0.625}

    def test_the_caliber_pages_and_their_names(self):
        calibers = dict(ammunition.ammo_com_calibers(page("ammocom-rifle.html.gz")))
        assert calibers["https://ammo.com/rifle/7.62x54r-ammo"] == ["7.62x54r"]
        forty = calibers["https://ammo.com/handgun/40-cal-ammo"]
        assert forty[:3] == ["40 Cal (S&W)", "40 Cal", "40 S&W"]
        # And with the point the armory writes an inch caliber with.
        assert ".40 S&W" in forty
        # Ammo.com's "8mm" is the 8mm Mauser (AMMO_COM_HINTS).
        assert calibers["https://ammo.com/rifle/8mm-ammo"][0] == "8mm Mauser"
        # A caliber with nothing in stock is still a page, named without it.
        assert calibers["https://ammo.com/rifle/6.5x52mm-carcano-ammo"] == ["6.5x52mm Carcano"]

    def test_a_long_list_links_its_next_page(self):
        nine = page("ammocom-9mm-1.html.gz")
        assert len(ammunition.ammo_com_offers(nine)) == 40
        assert ammunition.ammo_com_more(nine, 1)
        assert not ammunition.ammo_com_more(page("ammocom-7.62x54r.html.gz"), 1)


class TestGrafs:
    BULLETS = ammunition.grafs_bullets(recorded("grafs-bullets-311.json.gz")["products"])

    def test_bullets_by_diameter(self):
        mosin = ammunition.at_diameter(self.BULLETS, 0.3118)  # .311" and .312"
        assert ammunition.lows(mosin, [150, 174, 181]) == {150: 0.3299, 174: 0.359, 181: 0.3399}
        assert ammunition.at_diameter(self.BULLETS, 0.02) == []

    def test_every_way_a_title_is_written(self):
        found = ammunition.grafs_bullets(
            [
                {
                    "title": title,
                    "handle": "x",
                    "variants": [{"available": True, "price": "50.00", "title": "Default Title"}],
                }
                for title in (
                    "Prvi Partizan .311 Diameter Bullets 174 grain Full Metal Jacket Bag of 50",
                    "SIERRA 6.5(.264) 153g BULLET TMK 500/bx",
                    "PULL DOWN 30c (.308) 160g BULLET (30-30) P/100",
                    "MISSOURI BULLET COMPANY CAST 38c (.358) 105gTCFP CB16 BLKPWD 500b",
                    "Nosler RDF 28 Caliber, 7mm (.284 Diameter) Bullets 185 grain Each of 500",
                    "SPEER 44 CAPSULES EMPTY w/BASE PLUG 25/bx",
                )
            ]
        )
        assert [(inches, offer.grains, offer.rounds) for inches, offer in found] == [
            (0.311, 174.0, 50),
            (0.264, 153.0, 500),
            (0.308, 160.0, 100),
            (0.358, 105.0, 500),
            (0.284, 185.0, 500),
        ]

    def test_a_box_of_four_is_a_case_and_its_handle_counts_the_bullets(self):
        thirty = {
            offer.url.rsplit("/", 1)[1]: offer.rounds
            for offer in ammunition.at_diameter(self.BULLETS, 0.308)
        }
        # Both titled "Box of 4".
        assert thirty["winchester-bullet-30-308-147gr-fmjbt-500bx-4cs"] == 500
        assert thirty["federal-30cal-308-fusion-150gr-bt-bullet-box-of-50"] == 50

    def test_sold_out_is_not_offered(self):
        product = {
            "title": "Hornady .312 Diameter Bullets 150 grain Box of 100",
            "handle": "h",
            "variants": [{"available": False, "price": "30.00", "title": "Default Title"}],
        }
        assert ammunition.grafs_bullets([product]) == []


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


#: Graf & Sons' collections as recorded on 2026-10-14, cut to a few cartridges.
GRAFS_COLLECTIONS = {
    "bullets": "grafs-bullets-311.json.gz",
    "rifle-brass": "grafs-brass.json.gz",
    "primers": "grafs-primers.json.gz",
    "smokeless-powder": "grafs-powders.json.gz",
}


class RecordedSites:
    """Ammo.com, Graf & Sons, Milsurp Munitions and Lee as recorded, for a
    whole refresh."""

    def __init__(self):
        self.asked = []

    def keep_at_least(self, *_args):
        pass

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        if url.startswith(ammunition.LEE):
            if "rifle-dies" in url and "pagenumber=1" in url:
                return page("lee-rifle-dies-1.html.gz")
            return "<html></html>"
        if url == ammunition.AMMO_COM + "rifle":
            return page("ammocom-rifle.html.gz")
        if url == ammunition.AMMO_COM + "rifle/7.62x54r-ammo":
            return page("ammocom-7.62x54r.html.gz")
        if url.startswith(ammunition.AMMO_COM):
            return "<html></html>"
        if url.startswith(ammunition.GRAFS):
            if url.endswith("page=1"):
                for handle, name in GRAFS_COLLECTIONS.items():
                    if f"collections/{handle}/" in url:
                        return page(name)
            return '{"products": []}'
        if url.startswith(ammunition.MILSURP_MUNITIONS):
            return page("milsurp-munitions-products.json.gz")
        raise ScrapeError(f"GET {url}: not recorded")


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
        assert mosin_round.factory_cpr == round((0.625 + 1.7995 + 1.0495) / 3, 4)
        assert (mosin_round.factory_source, mosin_round.factory_url) == (
            "ammo-com",
            "https://ammo.com/rifle/7.62x54r-ammo",
        )
        by_weight = {w.grains: w for w in mosin_round.bullet_weights}
        assert by_weight[174.0].factory_cpr == 1.7995
        assert by_weight[150.0].projectile_cost == 0.3299
        assert mosin_round.projectile_cost == round((0.3299 + 0.359 + 0.3399) / 3, 4)
        # Linked to the cheapest bullet priced, on Graf & Sons' own page.
        assert mosin_round.projectile_url == (
            "https://grafs.com/products/speer-303-311-150gr-sp-bullet-spitzer-100bx"
        )
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

    def test_one_page_is_enough_when_it_prices_every_weight(self, clean_db, mosin_round):
        sites = RecordedSites()
        ammunition.refresh(clean_db, sites, fetch=fake_wikipedia, log=lambda _m: None)
        assert [u for u in sites.asked if "7.62x54r" in u] == [
            "https://ammo.com/rifle/7.62x54r-ammo"
        ]

    def test_where_ammo_com_has_nothing_milsurp_munitions_is_asked(self, clean_db):
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
        row.last_full_at = utcnow()
        clean_db.commit()
        assert not ammunition.is_due(clean_db)
        row.requested_at = utcnow()
        clean_db.commit()
        assert ammunition.is_due(clean_db)


class TestOnePartAtATime:
    """Asked for on 2026-10-12: a button each for the Wikipedia facts, the
    reloading bullets and the ammunition prices, and one for all three."""

    def test_asking_for_one_part_runs_only_that_part(self, clean_db, mosin_round):
        ammunition.ask_for(clean_db, ["reloading"])
        assert ammunition.due_parts(clean_db) == ("reloading",)
        sites = RecordedSites()
        summary = ammunition.refresh(
            clean_db, sites, log=lambda _m: None, parts=ammunition.due_parts(clean_db)
        )
        clean_db.refresh(mosin_round)
        # No Ammo.com and no Milsurp Munitions: Graf & Sons and Lee only.
        assert not [u for u in sites.asked if u.startswith(ammunition.AMMO_COM)]
        assert not [u for u in sites.asked if u.startswith(ammunition.MILSURP_MUNITIONS)]
        assert mosin_round.factory_checked_at is None
        assert mosin_round.lee_checked_at is not None
        assert "with projectile prices" in summary and "factory" not in summary
        row = ammunition.settings(clean_db)
        assert (row.requested_at, row.requested_parts, row.last_parts) == (
            None,
            None,
            "reloading",
        )

    def test_one_part_by_hand_does_not_put_the_schedule_off(self, clean_db):
        ammunition.refresh(clean_db, RecordedSites(), log=lambda _m: None, parts=["prices"])
        row = ammunition.settings(clean_db)
        assert row.last_run_at is not None and row.last_full_at is None
        assert ammunition.due_parts(clean_db) == ammunition.PARTS
        ammunition.refresh(clean_db, RecordedSites(), log=lambda _m: None)
        assert ammunition.settings(clean_db).last_full_at is not None
        assert ammunition.due_parts(clean_db) == ()

    def test_wikipedia_by_hand_reads_every_article_again(self, clean_db, mosin_round):
        mosin_round.wikipedia_read_at = utcnow()
        mosin_round.bullet_diameter_in = 0.5
        clean_db.commit()
        summary = ammunition.refresh(
            clean_db,
            RecordedSites(),
            fetch=fake_wikipedia,
            log=lambda _m: None,
            parts=["wikipedia"],
            reread=True,
        )
        clean_db.refresh(mosin_round)
        assert mosin_round.bullet_diameter_in == 0.3118
        assert summary == "Wikipedia: 1 articles read"

    def test_the_api_takes_the_parts(self, client, admin_headers, clean_db):
        asked = client.post(
            "/api/ammunition/refresh", json={"parts": ["wikipedia"]}, headers=admin_headers
        )
        assert asked.status_code == 200, asked.text
        assert asked.json()["requested_parts"] == "wikipedia"
        everything = client.post("/api/ammunition/refresh", headers=admin_headers).json()
        assert everything["requested_parts"] == "wikipedia,reloading,prices"
        wrong = client.post(
            "/api/ammunition/refresh", json={"parts": ["ammoseek"]}, headers=admin_headers
        )
        assert wrong.status_code == 422


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


class TestTheSchedulerRunsIt:
    """On its own worker since 2026-10-11: the first refresh in production,
    an hour of polite requests, was found holding the photo queue behind it."""

    class Pool:
        def __init__(self):
            self.submitted = []

        def submit(self, fn, *args):
            self.submitted.append((fn.__name__, args))

            class Done:
                def done(self):
                    return False

            return Done()

    def test_a_due_refresh_goes_to_the_reference_worker_not_the_photo_one(
        self, clean_db, app_config
    ):
        from app.scheduler import Scheduler

        scheduler = Scheduler(app_config)
        scheduler._photo_pool, scheduler._background_pool = self.Pool(), self.Pool()
        scheduler._dispatch_ammunition()
        assert scheduler._photo_pool.submitted == []
        assert scheduler._background_pool.submitted == [
            ("_refresh_ammunition", (ammunition.PARTS, False))
        ]
        # And never a second while that one is going.
        scheduler._last_ammo_look = 0.0
        scheduler._dispatch_ammunition()
        assert len(scheduler._background_pool.submitted) == 1


class TestUnitsWrittenWithTheNumber:
    """The first production refresh read .22 LR as 0.0088" and .303 British as a
    2,315 gr bullet, by trusting the page's flag over the unit stated."""

    def test_inches_on_a_metric_page(self):
        text = "{{Infobox firearm cartridge |is_SI_specs=yes |bullet=0.308 in (7.82 mm) |bw1=150}}"
        assert ammunition.article_facts(text).diameter_in == 0.308

    def test_a_convert_template(self):
        text = (
            "{{Infobox firearm cartridge |bullet={{convert|0.223|in|mm|2}} "
            "|bw1={{cvt|40|gr|g}} |bw2={{cvt|36|gr|g}}}}"
        )
        found = ammunition.article_facts(text)
        assert (found.diameter_in, found.grains) == (0.223, [36.0, 40.0])

    def test_grains_under_a_metric_ballistics_flag(self):
        text = "{{Infobox firearm cartridge |is_SI_ballistics=yes |bullet=0.312 |bw1=150 |bw2=174}}"
        assert ammunition.article_facts(text).grains == [150.0, 174.0]

    def test_grams_still_read_as_grams(self):
        text = "{{Infobox firearm cartridge |is_SI_specs=yes |bwunit=gram |bullet=9.01 |bw1=7.45}}"
        found = ammunition.article_facts(text)
        assert (found.diameter_in, found.grains) == (0.3547, [115.0])


class TestMatchingShopPages:
    def test_a_page_named_exactly_wins_over_a_loose_reading(self, clean_db):
        """On AmmoSeek (2026-10-11), read loosely and first come first served,
        "9mm Browning Long" claimed 9mm Luger and "22 S, L, LR" .22 LR."""
        clean_db.add_all(
            [
                Caliber(name="9mm Luger", aliases="9x19mm\n9mm", status=ArmoryStatus.APPROVED),
                Caliber(name=".22 LR", aliases=".22LR\n22 LR", status=ArmoryStatus.APPROVED),
            ]
        )
        clean_db.commit()
        pages = ammunition.match_pages(
            clean_db,
            [
                ("/browning-long", ["9mm Browning Long"]),
                ("/short-long-lr", ["22 S, L, LR"]),
                ("/9mm", ["9mm"]),
                ("/22-lr", ["22 Long Rifle (LR)", "22 Long Rifle", "22 LR"]),
            ],
        )
        assert pages["9mm Luger"] == "/9mm"
        assert pages[".22 LR"] == "/22-lr"


class TestTheFirstProductionRun:
    """What the first run against Ammo.com and Graf & Sons got wrong (2026-10-12)."""

    def test_inch_calibers_are_written_the_armory_way(self):
        names = ammunition._ammo_com_names("300 Win Magnum Ammo")
        assert ".300 Winchester Magnum" in names
        assert ".22-250" in ammunition._ammo_com_names("22-250 Ammo")
        # Not a metric size, a gauge or a buckshot size.
        assert ammunition._ammo_com_names("7.62x39 Ammo") == ["7.62x39"]
        assert ammunition._ammo_com_names("12 Gauge Shotgun Shells") == ["12 Gauge"]
        assert ".00 Buck" not in ammunition._ammo_com_names("00 Buck Ammo")

    def test_a_vague_caliber_is_never_matched(self, clean_db):
        clean_db.add_all(
            [
                Caliber(name="6mm", status=ArmoryStatus.APPROVED),
                Caliber(name=".22 Caliber", status=ArmoryStatus.APPROVED),
            ]
        )
        clean_db.commit()
        pages = ammunition.match_pages(
            clean_db, [("/6mm-arc", ["6mm ARC", "6mm"]), ("/22", ["22 Caliber"])]
        )
        assert pages == {}

    def test_a_calibers_own_name_beats_its_alias(self, clean_db):
        clean_db.add(
            Caliber(
                name="5.56x45mm NATO",
                aliases="5.56x45\n223",
                status=ArmoryStatus.APPROVED,
            )
        )
        clean_db.commit()
        pages = ammunition.match_pages(clean_db, [("/223-rem", ["223"]), ("/5.56x45", ["5.56x45"])])
        # "223" is listed first, but "5.56x45" comes earlier in the aliases.
        assert pages == {"5.56x45mm NATO": "/5.56x45"}

    def test_one_lee_die_set_loads_two_cartridges(self):
        """.357 Magnum came out with no Lee dies: Lee sells the set as "38
        Special / 357 Magnum", and only the first name was credited."""
        assert ammunition.lee_names("38 Special / 357 Magnum")[1:] == [
            "38 Special",
            "357 Magnum",
        ]
        # The second written short takes the first's number.
        assert ammunition.lee_names("44 Special/Magnum")[1:] == ["44 Special", "44 Magnum"]
        assert ammunition.lee_names("38 ACP/Super")[1:] == ["38 ACP", "38 Super"]
        # One cartridge, the .32-20, not two.
        assert ammunition.lee_names("32/20 Winchester") == ["32/20 Winchester"]
        assert ammunition.lee_names("9mm Luger") == ["9mm Luger"]

    def test_rimfire_is_not_reloaded(self):
        assert ammunition.is_rimfire(".22 LR")
        assert ammunition.is_rimfire(".17 HMR")
        assert ammunition.is_rimfire(".22 WMR")
        assert not ammunition.is_rimfire(".22 Hornet")
        assert not ammunition.is_rimfire(".22-250 Remington")
        assert not ammunition.is_rimfire(".223 Remington")
        lr = Caliber(name=".22 LR", bullet_diameter_in=0.2235)
        bullets = ammunition.grafs_bullets(
            [
                {
                    "title": "Hornady .224 Diameter Bullets 40 grain Box of 100",
                    "handle": "h",
                    "variants": [{"available": True, "price": "20.00", "title": "Default Title"}],
                }
            ]
        )
        assert not ammunition._projectiles(lr, bullets, utcnow())
        assert lr.projectile_cost is None


class TestWhenAmmoComFails:
    class Failing(RecordedSites):
        def get_text(self, url, **kwargs):
            if url == ammunition.AMMO_COM + "rifle/7.62x54r-ammo":
                self.asked.append(url)
                raise ScrapeError(f"GET {url} failed after 4 attempts: 503 Server Error")
            return super().get_text(url, **kwargs)

    def test_it_keeps_what_it_had_and_the_fallback_still_works(self, clean_db, mosin_round):
        mosin_round.factory_cpr, mosin_round.factory_source = 0.6715, "ammo-com"
        site = Site(slug="am2", name="Shop AM2", base_url="https://am2.test/")
        mannlicher = Caliber(name="8x50R Mannlicher", status=ArmoryStatus.APPROVED)
        clean_db.add_all([site, mannlicher])
        clean_db.flush()
        clean_db.add(
            Item(
                site_id=site.id,
                external_key="s",
                url="https://am2.test/s",
                title="Steyr M95",
                caliber="8x50R Mannlicher",
                is_rifle=True,
                is_active=True,
                is_sold=False,
            )
        )
        clean_db.commit()
        ammunition.refresh(clean_db, self.Failing(), log=lambda _m: None)
        clean_db.refresh(mosin_round)
        clean_db.refresh(mannlicher)
        # "Not read" is not "none for sale": the earlier figure is kept.
        assert (mosin_round.factory_cpr, mosin_round.factory_source) == (0.6715, "ammo-com")
        assert (mannlicher.factory_cpr, mannlicher.factory_source) == (2.9975, "milsurp-munitions")

    def test_a_source_not_read_is_a_warning_and_progress_is_cleared(self, clean_db, mosin_round):
        """Site settings' status (2026-10-16): finished, with less than asked."""

        class NoAmmoCom(RecordedSites):
            def get_text(self, url, **kwargs):
                if url.startswith(ammunition.AMMO_COM):
                    raise ScrapeError(f"GET {url}: 503 Server Error")
                return super().get_text(url, **kwargs)

        ammunition.refresh(clean_db, NoAmmoCom(), log=lambda _m: None, parts=("prices",))
        row = clean_db.get(AmmoSetting, 1)
        assert (row.last_status, row.started_at, row.progress) == ("warning", None, None)

    def test_a_refresh_the_service_restarted_under_is_interrupted(self, clean_db):
        row = ammunition.settings(clean_db)
        row.started_at, row.progress = utcnow(), "Pricing calibers: 40 of 280 (.30-06)"
        clean_db.commit()
        assert ammunition.reap_interrupted(clean_db) is True
        assert (row.last_status, row.started_at) == ("interrupted", None)
        assert "40 of 280" in row.last_summary

    def test_a_gauge_is_priced_by_its_cheapest_round_not_its_slugs(self, clean_db):
        class Shells(RecordedSites):
            def get_text(self, url, **kwargs):
                if url == ammunition.AMMO_COM + "shotgun":
                    return (
                        '<a href="https://ammo.com/shotgun/12-ga-ammo">12 Gauge Shotgun Shells</a>'
                    )
                if url == ammunition.AMMO_COM + "shotgun/12-ga-ammo":
                    # The 7.62x54R page with its cheapest boxes in ounces, as a
                    # shotshell's are, and the rest in grains, as a slug's are.
                    # The weight offered most often is then 150 gr at $1.22; the
                    # cheapest round is 62.5 cents, which is the answer.
                    return page("ammocom-7.62x54r.html.gz").replace(" 148 Grain ", " 1 oz ")
                return super().get_text(url, **kwargs)

        twelve = Caliber(name="12 Gauge", status=ArmoryStatus.APPROVED)
        site = Site(slug="sg", name="Shop SG", base_url="https://sg.test/")
        clean_db.add_all([twelve, site])
        clean_db.flush()
        clean_db.add(
            Item(
                site_id=site.id,
                external_key="g",
                url="https://sg.test/g",
                title="Remington 870",
                caliber="12 Gauge",
                is_active=True,
                is_sold=False,
            )
        )
        clean_db.commit()
        ammunition.refresh(clean_db, Shells(), log=lambda _m: None)
        clean_db.refresh(twelve)
        assert (twelve.factory_cpr, twelve.factory_source) == (0.625, "ammo-com")


class TestShotguns:
    """Asked for on 2026-10-12: shotshells are reloaded too, on Lee's Load-All,
    and a gauge's diameter is its bore -- what a slug is sized to."""

    def test_a_gauge_is_its_bore(self):
        assert ammunition.gauge_bore("12 gauge") == 0.729
        assert ammunition.gauge_bore("20 Gauge") == 0.615
        assert ammunition.gauge_bore(".410 Gauge") == 0.410
        assert ammunition.gauge_bore("10 GA") == 0.775
        assert ammunition.gauge_bore("12mm") is None
        assert ammunition.gauge_bore(".45") is None

    def test_the_load_all_lists_its_gauges(self):
        assert ammunition.lee_shotshells(page("lee-load-all-ii.html.gz")) == [
            "12 Gauge",
            "20 Gauge",
            "16 Gauge",
            "28 Gauge",
            ".410",
        ]

    def test_gauges_take_their_bore_where_they_have_none(self, clean_db):
        twelve = Caliber(name="12 gauge", status=ArmoryStatus.APPROVED)
        typed = Caliber(name="20 Gauge", status=ArmoryStatus.APPROVED, bullet_diameter_in=0.62)
        clean_db.add_all([twelve, typed])
        clean_db.commit()
        assert ammunition.set_gauge_bores(clean_db) == 1
        assert (twelve.bullet_diameter_in, typed.bullet_diameter_in) == (0.729, 0.62)
