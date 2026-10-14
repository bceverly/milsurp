"""What it costs to reload one round (app.services.reloading).

Asked for on 2026-10-14. The titles are Graf & Sons', from its brass, primer
and powder collections read that day (1,168 brass, 138 primers, 396
powders); each exclusion is one a first draft got wrong against them.
"""

from __future__ import annotations

import pytest
import yaml
from test_ammunition import ARTICLE, RecordedSites, fake_wikipedia, recorded

from app.models import ArmoryStatus, Caliber, CaliberBulletWeight, Item, ReloadingSupply, Site
from app.services import ammunition, armory, reloading


def product(title, price="49.99", available=True, handle="h", vendor=""):
    return {
        "title": title,
        "vendor": vendor,
        "handle": handle,
        "variants": [{"price": price, "available": available}],
    }


class TestBrassTitles:
    @pytest.mark.parametrize(
        ("title", "caliber", "count"),
        [
            ("Starline 41 Long Colt Brass Bag of 100", "41 Long Colt", 100),
            ("PETERSON BRASS 22-250 REMINGTON UNPRIMED 50/bx", "22-250 REMINGTON", 50),
            ("Prvi 7.62x54mmR Brass Bag of 50", "7.62x54mmR", 50),
            (
                "Starline 44 Remington Magnum Nickel Plated Brass Bag of 100",
                "44 Remington Magnum",
                100,
            ),
            ("Peterson 284 Winchester Brass Box of 50", "284 Winchester", 50),
            ("Quality Cartridge 30-03 Gov't Brass Bag of 20", "30-03 Gov't", 20),
            ("Starline 45 ACP Brass Jug of 1000", "45 ACP", 1000),
        ],
    )
    def test_the_caliber_and_the_count(self, title, caliber, count):
        (found,) = reloading.grafs_brass([product(title)])
        assert (found.caliber_text, found.count) == (caliber, count)

    @pytest.mark.parametrize(
        ("title", "vendor"),
        [
            ("Norma 300 Winchester Magnum Primed Brass Box of 100", ""),
            ("Pull-Down 9mm Luger Primed Nickel Plated Brass Bag of 100", ""),
            ('PULL DOWN BRASS 300 WSM "PRIMED" PER 50', ""),
            ("Lightning Reconditioned 223 Remington Brass Bag of 100", ""),
            ("Lightning 40 S&W Brass Bag of 100", "Lightning"),
            ("Once Fired 380 ACP Brass Bag of 100", ""),
            ("Starline 45 ACP Blank Brass Bag of 100", ""),
            ("Quality Cartridge Basic 6.5 Grendel Brass Bag of 20", ""),
        ],
    )
    def test_only_new_empty_cases(self, title, vendor):
        """A primed case would count its primer twice; Basic brass is a parent
        case to be formed into the one it names."""
        assert reloading.grafs_brass([product(title, vendor=vendor)]) == []

    def test_unprimed_is_new(self):
        (found,) = reloading.grafs_brass([product("LAPUA BRASS 220 RUSSIAN UNPRIMED 100/box")])
        assert found.caliber_text == "220 RUSSIAN"

    def test_out_of_stock_is_not_priced(self):
        assert (
            reloading.grafs_brass(
                [product("Prvi 7.35x51mm Carcano Brass Bag of 50", available=False)]
            )
            == []
        )


@pytest.fixture
def calibers(clean_db):
    rows = {
        name: Caliber(name=name, aliases=aliases, status=ArmoryStatus.APPROVED)
        for name, aliases in (
            (".25 ACP", "25 ACP"),
            (".303 British", "303 British"),
            (".222 Remington", None),
            (".22-250 Remington", None),
            (".30-03", "30-03"),
            ("8x52mmR Siamese", "8x52mmR"),
            ("6.5x55mm Swedish", None),
            (".45-70 Government", None),
            ("9x23 Largo", None),
            (".45 Caliber", None),
        )
    }
    clean_db.add_all(rows.values())
    clean_db.commit()
    return rows


def matched(session, *titles):
    brass = reloading.grafs_brass([product(t) for t in titles])
    found = reloading.brass_by_caliber(session, brass)
    return {name: sorted(b.caliber_text for b in offers) for name, offers in found.items()}


class TestMatchingBrassToCalibers:
    def test_the_same_number_and_words(self, clean_db, calibers):
        assert matched(clean_db, "Starline 45-70 Gov't Brass Bag of 100") == {
            ".45-70 Government": ["45-70 Gov't"]
        }

    @pytest.mark.parametrize(
        "title",
        [
            "Starline 25 Creedmoor Brass Bag of 100",
            "Quality Cartridge 303 Savage Brass Bag of 20",
            "Hornady 222 Remington Magnum Brass Box of 50",
        ],
    )
    def test_not_the_armorys_looser_reading(self, clean_db, calibers, title):
        """Read as a listing's title is, these were .25 ACP, .303 British and
        .222 Remington."""
        assert matched(clean_db, title) == {}

    def test_a_bare_designation_is_its_one_caliber(self, clean_db, calibers):
        assert matched(clean_db, "Lapua 6.5x55mm Brass Box of 100") == {
            "6.5x55mm Swedish": ["6.5x55mm"]
        }

    def test_the_armorys_bare_designation_takes_grafs_only_one(self, clean_db, calibers):
        assert matched(
            clean_db,
            "Quality Cartridge 30-03 Gov't Brass Bag of 20",
            "Quality Cartridge 8x52mmR T-66 Siamese Brass Bag of 20",
        ) == {".30-03": ["30-03 Gov't"], "8x52mmR Siamese": ["8x52mmR T-66 Siamese"]}

    def test_but_not_when_graf_sells_two_under_it(self, clean_db, calibers):
        """The armory's "9x23" could be either; neither is taken for it."""
        clean_db.add(Caliber(name="9x23mm", status=ArmoryStatus.APPROVED))
        clean_db.commit()
        assert matched(
            clean_db,
            "Starline 9x23mm Winchester Brass Bag of 100",
            "Starline 9x23mm Largo Brass Bag of 100",
        ) == {"9x23 Largo": ["9x23mm Largo"]}

    def test_parentheses_are_other_names(self, clean_db, calibers):
        clean_db.add(Caliber(name=".30-40 Krag", status=ArmoryStatus.APPROVED))
        clean_db.commit()
        assert matched(clean_db, "Starline 30-40 Krag (30 Army) Brass Bag of 100") == {
            ".30-40 Krag": ["30-40 Krag (30 Army)"]
        }

    def test_a_vague_caliber_takes_nothing(self, clean_db, calibers):
        assert matched(clean_db, "Starline 45 Caliber Brass Bag of 100") == {}


class TestPrimers:
    @pytest.mark.parametrize(
        ("title", "size", "magnum", "count"),
        [
            ("Winchester Large Pistol Primers Box of 1000", "Large pistol", False, 1000),
            ("CCI #450 Small Rifle Magnum Primers Box of 1000", "Small rifle", True, 1000),
            ("CCI 209 Shotshell Primers Box of 1000", "209 shotshell", False, 1000),
            (
                "CCI #41 5.56mm NATO-Spec Small Rifle Primers Box of 1000",
                "Small rifle",
                False,
                1000,
            ),
            ('UNIS GINEX PRIMER SMALL RIFLE "NICKEL" 5000/CS', "Small rifle", False, 5000),
            ("CCI #35 50 BMG Primers Case of 2500", ".50 BMG", False, 2500),
        ],
    )
    def test_size_magnum_and_count(self, title, size, magnum, count):
        (found,) = reloading.grafs_primers([product(title)])
        assert (found.size, found.magnum, found.count) == (size, magnum, count)

    def test_not_a_muzzleloaders(self):
        assert reloading.grafs_primers([product("CCI 209 Muzzleloader Primers Box of 100")]) == []

    def test_every_size_from_the_recorded_collection(self):
        found = reloading.grafs_primers(recorded("grafs-primers.json.gz")["products"])
        kinds = {reloading.primer_key(p.size, p.magnum) for p in found}
        assert {
            "Small pistol",
            "Small pistol magnum",
            "Large pistol",
            "Large pistol magnum",
            "Small rifle",
            "Small rifle magnum",
            "Large rifle",
            "Large rifle magnum",
            "209 shotshell",
            ".50 BMG",
        } <= kinds


class TestPowders:
    @pytest.mark.parametrize(
        ("title", "name", "pounds"),
        [
            ("Hodgdon H322 Smokeless Powder 1lb", "Hodgdon H322", 1),
            ("ACCURATE HIGH COUNTRY 8LB", "Accurate High Country", 8),
            ("Vihtavuori N340 Smokeless Powder 4lb", "Vihtavuori N340", 4),
            ("Hodgdon CFE 223 Smokeless Powder 8lb", "Hodgdon CFE 223", 8),
            ("Hodgdon BL-C(2) Smokeless Powder 1lb", "Hodgdon BL-C(2)", 1),
            ("Swiss 3F Black Powder 1lb", "Swiss 3F Black", 1),
            ("Swiss Null-B Black Powder 8oz", "Swiss Null-B Black", 0.5),
            ("Hodgdon Titewad Smokeless Powder 14oz", "Hodgdon Titewad", 0.875),
        ],
    )
    def test_name_and_weight(self, title, name, pounds):
        (found,) = reloading.grafs_powders([product(title)])
        assert (found.name, found.pounds) == (name, pounds)

    def test_a_shouted_acronym_stays_one(self):
        assert reloading.powder_name("IMR 4064 SMOKELESS POWDER 8LB") == "IMR 4064"
        assert reloading.powder_name("HODGDON HS6 8LB") == "Hodgdon HS6"

    def test_a_fuse_is_not_powder(self):
        assert (
            reloading.grafs_powders([product("HODGDON FUSE LACQUERED WATER RESISTANT (25 FEET)")])
            == []
        )


class TestTheArticlesPrimer:
    @pytest.mark.parametrize(
        ("text", "size", "magnum"),
        [
            ("Large rifle", "Large rifle", False),
            (" Berdan or boxer large rifle", "Large rifle", False),
            (" Large pistol LP (some makers are now using small pistol SP)", "Large pistol", False),
            ("[[Small rifle magnum]]", "Small rifle", True),
            ("Berdan", "Berdan", False),
            ("Rimfire", None, None),
            ("", None, None),
        ],
    )
    def test_the_infobox(self, text, size, magnum):
        assert reloading.article_primer({"primer": text}) == (size, magnum)

    def test_the_recorded_article(self):
        facts = ammunition.article_facts(ARTICLE)
        assert (facts.primer_size, facts.primer_magnum) == ("Large rifle", False)


@pytest.fixture
def mosin(clean_db):
    """A Mosin for sale, its cartridge's article and bullets known."""
    cartridge = Caliber(
        name="7.62x54mmR",
        aliases="7.62x54R",
        status=ArmoryStatus.APPROVED,
        wikipedia_url="https://en.wikipedia.org/wiki/7.62%C3%9754mmR",
    )
    site = Site(slug="rl", name="Shop RL", base_url="https://rl.test/")
    clean_db.add_all([cartridge, site])
    clean_db.flush()
    clean_db.add(
        Item(
            site_id=site.id,
            external_key="m",
            url="https://rl.test/m",
            title="Mosin-Nagant 91/30",
            caliber="7.62x54mmR",
            is_rifle=True,
            is_active=True,
            is_sold=False,
        )
    )
    clean_db.commit()
    return cartridge


def refreshed(session, cartridge):
    ammunition.refresh(session, RecordedSites(), fetch=fake_wikipedia, log=lambda _m: None)
    session.refresh(cartridge)
    return cartridge


class TestARefresh:
    def test_prices_the_brass_and_the_primer_and_waits_for_a_load(self, clean_db, mosin):
        row = refreshed(clean_db, mosin)
        assert (row.primer_size, row.primer_magnum, row.primer_source) == (
            "Large rifle",
            False,
            "wikipedia",
        )
        assert row.brass_cost is not None and row.brass_url.startswith("https://grafs.com/")
        assert row.primer_cost is not None and 0.02 < row.primer_cost < 0.2
        # No load entered: no powder, so no whole round.
        assert row.powder_cost is None
        assert reloading.reload_cost(row) is None
        stocked = {r.name for r in clean_db.query(ReloadingSupply).filter_by(kind="powder")}
        assert {"Hodgdon H4895", "Hodgdon Varget"} <= stocked

    def test_a_load_completes_the_round(self, clean_db, mosin):
        row = refreshed(clean_db, mosin)
        row.powder_name, row.powder_charge_gr = "Hodgdon Varget", 45.0
        reloading.price_load(clean_db, row)
        varget = reloading.supply(clean_db, "powder", "hodgdon VARGET")
        assert row.powder_cost == round(varget.unit_price / 7000 * 45.0, 5)
        assert reloading.reload_cost(row) == round(
            row.projectile_cost + row.brass_cost + row.powder_cost + row.primer_cost, 4
        )

    def test_a_primer_set_by_hand_is_not_read_over(self, clean_db, mosin):
        mosin.primer_size, mosin.primer_magnum, mosin.primer_source = "Large rifle", True, "hand"
        clean_db.commit()
        row = refreshed(clean_db, mosin)
        assert (row.primer_magnum, row.primer_source) == (True, "hand")
        magnum = reloading.supply(clean_db, "primer", "Large rifle magnum")
        assert row.primer_cost == magnum.unit_price

    def test_a_powder_gone_from_stock_stays_offered_but_unpriced(self, clean_db, mosin):
        row = refreshed(clean_db, mosin)
        clean_db.add(
            ReloadingSupply(kind="powder", name="Old Powder", unit_price=30.0, in_stock=True)
        )
        clean_db.commit()
        refreshed(clean_db, row)
        old = reloading.supply(clean_db, "powder", "Old Powder")
        assert old.in_stock is False
        row.powder_name, row.powder_charge_gr = "Old Powder", 40.0
        reloading.price_load(clean_db, row)
        assert row.powder_cost is None

    def test_the_bullet_is_the_loads_weight(self, clean_db, mosin):
        mosin.projectile_cost = 0.40
        mosin.bullet_weights.append(CaliberBulletWeight(grains=150.0, projectile_cost=0.33))
        mosin.powder_bullet_gr = 150
        assert reloading.bullet_cost(mosin) == 0.33
        mosin.powder_bullet_gr = 174
        assert reloading.bullet_cost(mosin) == 0.40


class TestEditingTheLoad:
    @pytest.fixture
    def stocked(self, clean_db, mosin):
        clean_db.add_all(
            [
                ReloadingSupply(
                    kind="powder", name="Hodgdon Varget", unit_price=52.12, in_stock=True
                ),
                ReloadingSupply(
                    kind="primer", name="Large rifle", unit_price=0.0438, in_stock=True
                ),
            ]
        )
        clean_db.commit()
        return mosin

    def test_typed_on_the_caliber_and_priced_at_once(
        self, client, admin_headers, stocked, clean_db
    ):
        response = client.patch(
            f"/api/armory/calibers/{stocked.id}",
            json={
                "primer_size": "large rifle",
                "powder_name": "hodgdon varget",
                "powder_charge_gr": 46.5,
                "powder_bullet_gr": 150,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        caliber = response.json()["caliber"]
        assert (caliber["primer_size"], caliber["primer_source"], caliber["powder_name"]) == (
            "Large rifle",
            "hand",
            "Hodgdon Varget",
        )
        shown = client.get(
            "/api/ammunition", params={"caliber": "7.62x54R"}, headers=admin_headers
        ).json()
        assert shown["powder_cost"] == round(52.12 / 7000 * 46.5, 5)
        assert (shown["primer_cost"], shown["powder_per_pound"], shown["powder_in_stock"]) == (
            0.0438,
            52.12,
            True,
        )

    @pytest.mark.parametrize(
        "change", [{"primer_size": "medium rifle"}, {"powder_name": "Nonesuch 1000"}]
    )
    def test_refused_when_unknown(self, client, admin_headers, stocked, change):
        response = client.patch(
            f"/api/armory/calibers/{stocked.id}", json=change, headers=admin_headers
        )
        assert response.status_code == 422

    def test_clearing_the_primer_hands_it_back_to_the_article(
        self, client, admin_headers, stocked, clean_db
    ):
        stocked.primer_size, stocked.primer_source = "Large rifle", "hand"
        clean_db.commit()
        response = client.patch(
            f"/api/armory/calibers/{stocked.id}", json={"primer_size": ""}, headers=admin_headers
        )
        assert response.json()["caliber"]["primer_source"] is None
        clean_db.refresh(stocked)
        assert stocked.wikipedia_read_at is None

    def test_the_dropdowns_powders(self, client, normal_user, stocked):
        shown = client.get("/api/ammunition/powders", headers=normal_user["headers"])
        assert shown.status_code == 200
        assert shown.json() == [
            {
                "name": "Hodgdon Varget",
                "unit_price": 52.12,
                "url": None,
                "in_stock": True,
            }
        ]


class TestTheShippedFile:
    def test_a_typed_load_travels_and_a_read_primer_does_not(self, clean_db, tmp_path):
        typed = Caliber(
            name=".308 Winchester",
            status=ArmoryStatus.APPROVED,
            primer_size="Large rifle",
            primer_source="hand",
            powder_name="Hodgdon Varget",
            powder_charge_gr=44.0,
            powder_bullet_gr=168.0,
        )
        read = Caliber(
            name=".45 ACP",
            status=ArmoryStatus.APPROVED,
            primer_size="Large pistol",
            primer_source="wikipedia",
        )
        clean_db.add_all([typed, read])
        clean_db.commit()
        path = tmp_path / "armory.yaml"
        armory.write_export(clean_db, path)
        written = {c["name"]: c for c in yaml.safe_load(path.read_text())["calibers"]}
        assert written[".308 Winchester"]["reloading"] == {
            "primer": "Large rifle",
            "powder": "Hodgdon Varget",
            "charge_gr": 44.0,
            "bullet_gr": 168.0,
        }
        assert "reloading" not in written[".45 ACP"]
        assert not armory.plan_sync(clean_db, path)

    def test_read_back(self, clean_db):
        row = Caliber(name="x", primer_size="Small rifle", primer_source="wikipedia")
        armory.write_reloading(row, {"powder": "Hodgdon H335", "charge_gr": 25})
        assert (row.primer_size, row.primer_source, row.powder_charge_gr) == (
            "Small rifle",
            "wikipedia",
            25,
        )
        armory.write_reloading(row, {"primer": "Small rifle", "primer_magnum": True})
        assert (row.primer_magnum, row.primer_source, row.powder_name) == (True, "hand", None)
