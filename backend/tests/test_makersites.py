"""Reading a maker's site for a model's variants (app.services.makersites).

Slice 3 of "New-gun prices" in ROADMAP.md. Ruger's pages are recorded: the
LCP's model cards and one spec sheet. Kimber's and Walther's were recorded on
2026-10-11: Kimber's sitemap and three product pages, Walther's home page (its
navigation) and two line pages.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from app.models import (
    ArmoryStatus,
    Caliber,
    FirearmKind,
    FirearmModel,
    Manufacturer,
    ModelVariant,
)
from app.scrapers.base import ScrapeError
from app.services import makersites

PAGES = Path(__file__).parent / "fixtures" / "makers"
MODELS = "https://ruger.com/products/lcp/models.html"


def page(name):
    return gzip.decompress((PAGES / name).read_bytes()).decode("utf-8")


class RugerSite:
    """Serves the recorded LCP models page, and the one recorded spec sheet for
    every spec sheet asked about."""

    def __init__(self):
        self.asked = []

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        if url == MODELS:
            return page("ruger-lcp-models.html.gz")
        if "specSheets/3701" in url:
            return page("ruger-lcp-3701.html.gz")
        raise ScrapeError(f"GET {url}: not recorded")

    def keep_at_least(self, *_args):
        pass


def _lcp(session):
    ruger = Manufacturer(name="Ruger", status=ArmoryStatus.APPROVED)
    auto = Caliber(name=".380 ACP", aliases="380 Auto", status=ArmoryStatus.APPROVED)
    lcp = FirearmModel(
        name="LCP", status=ArmoryStatus.APPROVED, modern_production=True, maker_url=MODELS
    )
    lcp.manufacturers = [ruger]
    session.add_all([ruger, auto, lcp])
    session.commit()
    return lcp


class TestTheRugerReader:
    def test_each_model_card_is_a_variant_with_its_sheet(self, clean_db):
        lcp = _lcp(clean_db)
        found = makersites.RugerReader().read(RugerSite(), lcp, [lcp])
        by_part = {f.maker_part: f for f in found}
        first = by_part["3701"]
        assert first.msrp == 259.0
        assert first.upc == "736676037018"
        assert first.barrel_inches == 2.75
        assert first.finish == "Black"
        assert first.caliber == "380 Auto"
        assert first.label == 'LCP 380 Auto 2.75" Black (Model 3701)'
        # A sheet that could not be read still leaves the card's own facts.
        assert by_part["3752"].msrp == 339.0

    def test_found_variants_arrive_pending_and_a_rerun_refreshes_them(self, clean_db):
        lcp = _lcp(clean_db)
        found = makersites.RugerReader().read(RugerSite(), lcp, [lcp])
        counts = makersites.record(clean_db, lcp, found)
        clean_db.commit()
        assert counts["proposed"] == len(found)
        assert {v.status for v in lcp.variants} == {ArmoryStatus.PENDING}
        assert {v.source for v in lcp.variants} == {"maker-site"}
        assert next(v for v in lcp.variants if v.maker_part == "3701").caliber.name == ".380 ACP"

        again = makersites.record(clean_db, lcp, found)
        assert again == {"proposed": 0, "refreshed": len(found)}


class MovedRugerSite(RugerSite):
    """Ruger on 2026-10-13: the recorded page answers "Page Not Found", and the
    rifle's new generation is named in the menu by its variety alone."""

    GONE = "https://ruger.com/products/americanRifle/models.html"
    NEW = "https://ruger.com/products/americanRifleGenII/models.html"

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        if url == self.GONE:
            return "<html><title>Page Not Found</title><body>Sorry</body></html>"
        if url == makersites.RugerReader.home:
            return (
                '<ul><li><a href="/products/americanRifleGenII/models.html">Standard</a></li>'
                '<li><a href="/products/americanRimfireTarget/models.html">Target</a></li></ul>'
            )
        if url == self.NEW:
            return page("ruger-lcp-models.html.gz")
        return super().get_text(url)


class TestAMovedRugerPage:
    def _rifle(self, session):
        rifle = FirearmModel(
            name="Ruger American Rifle",
            status=ArmoryStatus.APPROVED,
            modern_production=True,
            maker_url=MovedRugerSite.GONE,
        )
        rifle.manufacturers = [Manufacturer(name="Ruger", status=ArmoryStatus.APPROVED)]
        session.add(rifle)
        session.commit()
        return rifle

    def test_a_dead_page_falls_back_to_the_menu_and_the_new_lines_address(self, clean_db):
        rifle = self._rifle(clean_db)
        site = MovedRugerSite()
        found = makersites.RugerReader().read(site, rifle, [rifle])
        assert found
        assert MovedRugerSite.NEW in site.asked
        assert not any("americanRimfire" in url for url in site.asked)


SW_PAGE = """<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{
"products":[
 {"id":1,"name":"M&P®9 SHIELD® PLUS 3.1 INCH FDE","price":549,"upc":"022188901153","sku":"14280",
  "custom_url":{"url":"/m-p-9-shield-plus"}},
 {"id":2,"name":"M&P®9 M2.0® 4.25 INCH TUNGSTEN GRAY","price":949,"upc":"022188908718","sku":"14700",
  "custom_url":{"url":"/m-p-9-m2-0"}},
 {"id":3,"name":"MODEL 610 10MM REVOLVER 6.5\\" BARREL","price":1199,"upc":"022188877731","sku":"12463",
  "custom_url":{"url":"/model-610"}},
 {"id":4,"name":"MODEL 10 CLASSIC NO INTERNAL LOCK","price":1019,"upc":"022188899818","sku":"12038",
  "custom_url":{"url":"/model-10"}}
]}}}</script></html>"""


class SmithWessonSite:
    def __init__(self):
        self.asked = []

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        return SW_PAGE if "/products/" in url else ""


class TestTheSmithWessonReader:
    def models(self, session):
        sw = Manufacturer(name="Smith & Wesson", status=ArmoryStatus.APPROVED)
        rows = []
        for name, aliases in (
            ("Smith & Wesson M&P9", "M&P9"),
            ("Smith & Wesson M&P Shield", "M&P Shield"),
            ("Model 10", None),
        ):
            row = FirearmModel(
                name=name, aliases=aliases, status=ArmoryStatus.APPROVED, modern_production=True
            )
            row.manufacturers = [sw]
            rows.append(row)
        session.add_all([sw, *rows])
        session.commit()
        return rows

    def test_each_product_goes_to_the_model_it_names_most_specifically(self, clean_db):
        mp9, shield, model10 = self.models(clean_db)
        reader = makersites.SmithWessonReader()
        site = SmithWessonSite()
        siblings = [mp9, shield, model10]
        assert [f.upc for f in reader.read(site, shield, siblings)] == ["022188901153"]
        [m2] = reader.read(site, mp9, siblings)
        assert (m2.msrp, m2.barrel_inches, m2.finish) == (949.0, 4.25, "Gray")
        assert m2.url == "https://www.smith-wesson.com/product/m-p-9-m2-0"
        # The 610's "10" is the cartridge's, not the model's.
        assert [f.maker_part for f in reader.read(site, model10, siblings)] == ["12038"]

    def test_the_rifles_are_read_too(self, clean_db):
        """The M&P FPC carbine found nothing while only pistols and revolvers
        were read (2026-10-13)."""
        mp9, shield, model10 = self.models(clean_db)
        site = SmithWessonSite()
        makersites.SmithWessonReader().read(site, mp9, [mp9, shield, model10])
        assert "https://www.smith-wesson.com/products/rifles" in site.asked

    def test_a_number_must_follow_its_word(self):
        assert makersites._carries(["model", "10", "classic"], ["model", "10"])
        assert not makersites._carries(["model", "610", "10", "mm"], ["model", "10"])
        assert makersites._carries(["m", "p", "9", "shield", "plus"], ["m", "p", "shield"])


def _modern(session, maker_name, *names):
    maker = Manufacturer(name=maker_name, status=ArmoryStatus.APPROVED)
    rows = []
    for name, aliases in names:
        row = FirearmModel(
            name=name, aliases=aliases, status=ArmoryStatus.APPROVED, modern_production=True
        )
        row.manufacturers = [maker]
        rows.append(row)
    session.add_all([maker, *rows])
    session.commit()
    return rows


KIMBER = "https://www.kimberamerica.com/"
KIMBER_PAGES = {
    KIMBER + "sitemap.xml": "kimber-sitemap.xml.gz",
    KIMBER + "micro9-stainless-rosewood-lg": "kimber-micro9-stainless-rosewood-lg.html.gz",
    KIMBER + "k6s-dasa-2": "kimber-k6s-dasa-2.html.gz",
    KIMBER + "custom-ii-walnut": "kimber-custom-ii-walnut.html.gz",
}


class RecordedSite:
    """Serves the recorded pages it is given, and refuses everything else."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def get_text(self, url, **_kwargs):
        self.asked.append(url)
        if url in self.pages:
            return page(self.pages[url])
        raise ScrapeError(f"GET {url}: not recorded")

    def keep_at_least(self, *_args):
        pass


class TestTheKimberReader:
    def test_a_product_page_is_one_variant(self):
        found = makersites.kimber_product(page("kimber-micro9-stainless-rosewood-lg.html.gz"), "u")
        assert (found.maker_part, found.upc, found.msrp) == ("3700482", "669278374826", 939.0)
        assert (found.barrel_inches, found.finish, found.caliber) == (3.15, "Stainless", "9 mm")
        assert found.label == "Kimber Micro 9 Stainless (Rosewood LG) 9 mm (3700482)"

    def test_a_revolver_and_a_page_with_no_upc(self):
        found = makersites.kimber_product(page("kimber-k6s-dasa-2.html.gz"), "u")
        assert (found.maker_part, found.upc, found.msrp) == ("3400021CA", None, 1117.0)
        assert (found.barrel_inches, found.finish) == (2.0, "Stainless")

    def test_a_family_page_with_no_product_number_is_not_a_variant(self):
        assert makersites.kimber_product(page("kimber-custom-ii-walnut.html.gz"), "u") is None

    def test_only_pages_naming_the_model_are_asked_for(self, clean_db):
        micro9, custom, k6s = _modern(
            clean_db,
            "Kimber",
            ("Kimber Micro 9", "Micro 9\nMicro9"),
            ("Kimber Custom II", "Custom II"),
            ("Kimber K6s", "K6s"),
        )
        site = RecordedSite(KIMBER_PAGES)
        reader = makersites.KimberReader()
        found = reader.read(site, micro9, [micro9, custom, k6s])
        assert "3700482" in {f.maker_part for f in found}
        asked = [u.removeprefix(KIMBER) for u in site.asked]
        assert asked[0] == "sitemap.xml"
        assert all(u.startswith(("micro-9", "micro9")) for u in asked[1:])
        assert "micro-9-stainless-raptor" in asked
        # One sitemap for every model the reader is asked about.
        reader.read(site, k6s, [micro9, custom, k6s])
        assert site.asked.count(KIMBER + "sitemap.xml") == 1

    def test_the_model_named_first_owns_a_product(self):
        def owner(slug, models):
            found = makersites._earliest_owner(
                makersites._tokens(slug.replace("-", " ")), models, frozenset({"kimber"})
            )
            return found.name if found else None

        class Row:
            def __init__(self, name, *spellings):
                self.name = name
                self.spellings = [name, *spellings]

        rows = [
            Row("Kimber Micro 9", "Micro 9", "Micro9"),
            Row("Kimber Raptor II", "Raptor II", "Stainless Raptor"),
            Row("Kimber Stainless II", "Stainless II"),
            Row("Kimber Stainless Target II", "Stainless Target II"),
        ]
        assert owner("micro-9-stainless-raptor", rows) == "Kimber Micro 9"
        assert owner("stainless-target-ii", rows) == "Kimber Stainless Target II"
        assert owner("stainless-ii-texas-edition", rows) == "Kimber Stainless II"
        assert owner("micro9-khx", rows) == "Kimber Micro 9"
        assert owner("custom-crimson-carry-ii", rows) is None


WALTHER = "https://waltherarms.com/"


class TestTheWaltherReader:
    def test_a_line_page_is_a_grid_of_variants(self):
        found = makersites.walther_tiles(page("walther-ppk-s.html.gz"), WALTHER + "legacy/ppk-s")
        first = found[0]
        assert (first.maker_part, first.msrp, first.barrel_inches, first.finish) == (
            "4796004",
            969.0,
            3.3,
            "Stainless",
        )
        assert first.label == 'Walther PPK/S 3.3" Stainless 7RD .380 ACP (4796004)'
        assert first.url == WALTHER + "legacy/ppk-s/ppk-s-3-3-in-stainless-7rd-380-acp"

    def test_the_line_and_its_sub_lines_come_from_the_navigation(self, clean_db):
        [pdp] = _modern(clean_db, "Walther", ("Walther PDP", "PDP"))
        site = RecordedSite(
            {
                WALTHER: "walther-home.html.gz",
                WALTHER + "defense/pdp/standard": "walther-pdp-standard.html.gz",
            }
        )
        reader = makersites.WaltherReader()
        pages = reader.line_pages(site, pdp)
        assert WALTHER + "defense/pdp" in pages
        assert WALTHER + "defense/pdp/pro/pro-x" in pages
        assert not any("feature" in p for p in pages)
        # A sub-line that cannot be read is passed over; the rest still count.
        found = makersites.WaltherReader().read(site, pdp, [pdp])
        assert len(found) == len({f.maker_part for f in found}) > 5
        assert {f.msrp for f in found} >= {699.0, 799.0}


class TestARecordedPageIsTheMakersOwn:
    """CodeQL alerts #46 and #47 (2026-10-12): a recorded page was trusted as
    the maker's when its address merely contained "ruger.com"."""

    def test_by_host_not_by_substring(self):
        assert makersites._on_site("https://ruger.com/products/lcp/models.html", "ruger.com")
        assert makersites._on_site("https://www.ruger.com/x", "ruger.com")
        assert makersites._on_site("https://WWW.Ruger.com/x", "ruger.com")
        assert not makersites._on_site("https://elsewhere.example/?ruger.com", "ruger.com")
        assert not makersites._on_site("https://ruger.com.example.net/x", "ruger.com")
        assert not makersites._on_site("https://notruger.com/x", "ruger.com")
        assert not makersites._on_site(None, "waltherarms.com")


class TestAMovedVariantStaysMoved:
    def test_the_next_run_refreshes_it_where_it_was_moved(self, clean_db):
        """The M&P40 Shield M2.0 went to the M&P M2.0 and was moved to the
        Shield on 2026-10-14; the next run must not propose it again."""
        sw = Manufacturer(name="Smith & Wesson", status=ArmoryStatus.APPROVED)
        m2 = FirearmModel(name="M&P M2.0", status=ArmoryStatus.APPROVED, modern_production=True)
        shield = FirearmModel(
            name="M&P Shield", status=ArmoryStatus.APPROVED, modern_production=True
        )
        m2.manufacturers = [sw]
        shield.manufacturers = [sw]
        clean_db.add_all([sw, m2, shield])
        clean_db.flush()
        moved = ModelVariant(
            model_id=shield.id, label="M&P40 SHIELD M2.0", maker_part="13101", msrp=399.0
        )
        clean_db.add(moved)
        clean_db.commit()
        found = makersites.Found(
            maker_part="13101",
            label="M&P40 SHIELD M2.0",
            caliber=None,
            barrel_inches=None,
            finish=None,
            upc=None,
            msrp=429.0,
            url=None,
        )
        counts = makersites.record(clean_db, m2, [found])
        clean_db.commit()
        assert counts == {"proposed": 0, "refreshed": 1}
        assert m2.variants == []
        clean_db.refresh(moved)
        assert (moved.model_id, moved.msrp) == (shield.id, 429.0)


class TestProductsNoModelNames:
    """2026-10-14: the M&P 5.7 and M&P22X have no model, and the M&P M2.0's
    catch-all spelling "S&W M&P |" claimed them; an M2.0 listing would have
    shown their prices as its own versions."""

    def test_a_model_switched_off_is_not_flagged_back_on(self, clean_db):
        sw, _m2 = self._sw(clean_db)
        old686 = clean_db.query(FirearmModel).filter_by(name="Smith & Wesson Model 686").one()
        old686.enabled = False
        clean_db.commit()
        said = []
        found = [makersites.Found(maker_part="6", label='MODEL 686 PLUS 6" BARREL')]
        makersites._propose_models(clean_db, sw, {"Model 686 Plus": found}, said.append)
        assert not old686.modern_production
        assert old686.variants == []
        assert any("not in use" in line for line in said)

    def test_a_catch_all_spelling_owns_nothing(self):
        assert makersites._specific(["m", "p", "9"])
        assert makersites._specific(["m", "p", "shield"])
        assert not makersites._specific(["m", "p"])

    @pytest.mark.parametrize(
        ("product", "line"),
        [
            ("M&P 5.7 10RD COMPLIANT", "M&P 5.7"),
            ("M&P22X 10RD COMPLIANT", "M&P22X"),
            ("PERFORMANCE CENTER MODEL 940-3", "Model 940-3"),
            ("S&W SD40 2.0 2-Tone 10RD COMPLIANT", "SD40"),
            ("S&W RESPONSE 9MM 10RD COMPLIANT", "Response"),
            ("[DISCONTINUED]M&P9 M2.0 METAL IN GOLD", "M&P9 M2.0 Metal"),
        ],
    )
    def test_a_products_line(self, product, line):
        assert makersites._line_name(product) == line

    def _sw(self, session):
        sw = Manufacturer(
            name="Smith & Wesson", status=ArmoryStatus.APPROVED, country="United States"
        )
        m2 = FirearmModel(
            name="Smith & Wesson M&P M2.0",
            aliases="M&P M2.0\nS&W M&P |",
            status=ArmoryStatus.APPROVED,
            modern_production=True,
        )
        old686 = FirearmModel(
            name="Smith & Wesson Model 686", status=ArmoryStatus.APPROVED, modern_production=False
        )
        m2.manufacturers = [sw]
        old686.manufacturers = [sw]
        session.add_all([sw, m2, old686])
        session.commit()
        return sw, m2

    def test_a_family_is_proposed_once_and_a_decided_model_not_at_all(self, clean_db):
        sw, m2 = self._sw(clean_db)
        reader = makersites.SmithWessonReader()
        reader._catalog = [
            {"name": "M&P®5.7 10RD COMPLIANT", "sku": "1", "price": 699},
            {"name": "M&P®5.7 FDE", "sku": "2", "price": 729},
            {"name": "MODEL 1854 LEVER-ACTION RIFLE 44 MAGNUM", "sku": "3", "price": 1279},
            {"name": "MODEL 1854 STEALTH HUNTER 45 COLT", "sku": "4", "price": 1399},
            {"name": "MODEL 1854 - AMERICA 250", "sku": "5", "price": 1599},
            {"name": 'MODEL 686 PLUS 6" BARREL', "sku": "6", "price": 1029},
            {"name": "M&P9 M2.0 METAL", "sku": "7", "price": 949},
        ]
        assert reader._owner(reader._catalog[0], [m2]) is None
        assert reader._owner(reader._catalog[6], [m2]) is m2
        said = []
        lines = reader.unowned(object(), [m2])
        assert makersites._propose_models(clean_db, sw, lines, said.append) == 2
        proposed = {
            m.name: m
            for m in clean_db.query(FirearmModel).filter(
                FirearmModel.status == ArmoryStatus.PENDING
            )
        }
        assert set(proposed) == {"Smith & Wesson M&P 5.7", "Smith & Wesson Model 1854"}
        assert len(proposed["Smith & Wesson Model 1854"].variants) == 3
        # Stated as every modern row is: the maker's country, and the kind
        # the one product naming one says; the M&P 5.7's say none.
        lever = proposed["Smith & Wesson Model 1854"]
        assert (lever.kind, lever.country) == (FirearmKind.RIFLE, "United States")
        assert proposed["Smith & Wesson M&P 5.7"].kind is None
        assert all(
            v.status == ArmoryStatus.PENDING for v in proposed["Smith & Wesson M&P 5.7"].variants
        )
        # The Model 686 was never flagged as made; its product on the site
        # flags it, and its version is read under it (2026-10-14).
        old686 = clean_db.query(FirearmModel).filter_by(name="Smith & Wesson Model 686").one()
        assert old686.modern_production
        assert [v.maker_part for v in old686.variants] == ["6"]
        assert any("Model 686: flagged as still made" in line for line in said)

        # A second run proposes nothing new: the models now exist.
        again = reader.unowned(object(), [m2, *proposed.values()])
        assert makersites._propose_models(clean_db, sw, again, said.append) == 0


ARMSCOR = "https://www.armscor.com/"
ARMSCOR_LIST = ARMSCOR + "firearms-list/"
ARMSCOR_PAGES = {
    ARMSCOR + "sitemap.xml": "armscor-sitemap.xml.gz",
    **{
        ARMSCOR_LIST + slug: f"armscor-{slug}.html.gz"
        for slug in (
            "pro-ultra-match-6-45acp-8rd",
            "tac-ultra-cs-9mm-8rd",
            "mapp-ms-9mm-10rd",
            "vr80-5rd-12ga",
            "all-generations-12ga-pump-action-28-barrel-5rd-standard-black-finish",
        )
    },
}


def armscor(slug):
    return makersites.armscor_product(page(f"armscor-{slug}.html.gz"), ARMSCOR_LIST + slug)


class TestTheArmscorReader:
    """Rock Island Armory, added and its pages recorded on 2026-10-15."""

    def test_a_1911_from_its_specification_table(self):
        line, found = armscor("tac-ultra-cs-9mm-8rd")
        assert line == "1911"
        assert found.maker_part == "51700"
        assert found.label == "Rock Island Armory TAC Ultra CS 9MM 8rd (51700)"
        assert (found.caliber, found.kind, found.frame_size) == (
            "9MM",
            FirearmKind.PISTOL,
            "Subcompact",
        )
        assert found.msrp and found.barrel_inches

    def test_another_line_is_the_model_its_name_starts_with(self):
        line, found = armscor("mapp-ms-9mm-10rd")
        assert (line, found.frame_size) == ("MAPP", "Compact")
        line, found = armscor("vr80-5rd-12ga")
        assert (line, found.kind, found.frame_size) == ("VR80", FirearmKind.SHOTGUN, None)

    def test_discontinued_and_unnamed_products_are_not_read(self):
        assert armscor("pro-ultra-match-6-45acp-8rd") is None
        assert (
            armscor("all-generations-12ga-pump-action-28-barrel-5rd-standard-black-finish") is None
        )

    @pytest.mark.parametrize(
        ("name", "series", "line"),
        [
            ('PRO Ultra Match 6" 45ACP 8rd', "Pro", "1911"),
            ("CAL. 380 M1911 BABY ROCK Titanium Blue", "Baby Rock", "1911"),
            ("M1911 A2 Tac Ultra FS HC - 10mm Auto", "RIA-USA", "1911"),
            ("RIA5.0E 9mm 17rd Grey Ghost", "RIA-USA", "RIA 5.0"),
            ("STK200 9MM 15rd", "STK", "STK200"),
            ("M206 Spurless 38Spl 6rd", "Revolvers", "M206"),
            ("Melik 9mm 17rd Two Tone", "Derya", None),
            ("Single Shot Real Tree Timber 12GA 1rd", "Single Shot", None),
        ],
    )
    def test_the_lines(self, name, series, line):
        assert makersites.armscor_line(name, series) == line

    def test_a_run_reads_the_1911_and_proposes_the_rest(self, clean_db):
        (r1911,) = _modern(clean_db, "Rock Island Armory", ("Rock Island 1911", "RIA 1911"))
        r1911.manufacturers[0].country = "Philippines"
        clean_db.commit()
        site = RecordedSite(ARMSCOR_PAGES)
        said = []
        totals = makersites.run(clean_db, site, maker="Rock Island Armory", log=said.append)
        assert [v.maker_part for v in r1911.variants] == ["51700"]
        proposed = {
            m.name: m
            for m in clean_db.query(FirearmModel).filter(
                FirearmModel.status == ArmoryStatus.PENDING
            )
        }
        assert set(proposed) == {"Rock Island Armory MAPP", "Rock Island Armory VR80"}
        assert totals["models_proposed"] == 2
        vr80 = proposed["Rock Island Armory VR80"]
        assert (vr80.kind, vr80.country) == (FirearmKind.SHOTGUN, "Philippines")
        # The sitemap once, and each product page once, whatever the models.
        assert site.asked.count(ARMSCOR + "sitemap.xml") == 1
        assert len(site.asked) == len(set(site.asked))


BUDS = "https://www.budsgunshop.com/"
BUDS_G19 = (
    BUDS
    + "products/pistols/glock-19-gen6-optic-ready-9mm-15plus1-4-02-inch-blue-black-pistol-186901"
)
BUDS_G17 = BUDS + "products/pistols/glock-17-gen-4-9mm-17-plus-1-4-49-inch-black-pistol-411561085"


class BudsSite(RecordedSite):
    """Bud's Gun Shop as recorded on 2026-10-15: the first page of Glock's
    in-stock handguns, one new pistol's page and one police trade-in's. Any
    other product page, list page or category is not there."""

    def __init__(self):
        super().__init__(
            {
                BUDS
                + "categories/firearms/handguns?brand=Glock&availability=in+stock&page=1": (
                    "buds-list1.html.gz"
                ),
                BUDS_G19: "buds-g19.html.gz",
                BUDS_G17: "buds-g17.html.gz",
            }
        )


class TestTheBudsReader:
    """For makers whose own site cannot be read or does not say (2026-10-15)."""

    def test_a_product_page(self):
        new = makersites.buds_product(page("buds-g19.html.gz"))
        assert (new["new"], new["upc"], new["model"], new["msrp"], new["barrel"]) == (
            True,
            "764503068256",
            "P61950203",
            745.0,
            4.02,
        )
        used = makersites.buds_product(page("buds-g17.html.gz"))
        assert used["new"] is False

    def test_the_tiles(self):
        cards = makersites.buds_cards(page("buds-list1.html.gz"))
        g19 = next(c for c in cards if c.url == BUDS_G19)
        assert (g19.msrp, g19.barrel_inches) == (745.0, 4.02)
        # Featured products of other makers share the page.
        assert any(c.name.startswith("Smith & Wesson") for c in cards)

    def test_a_brand_by_any_of_the_makers_spellings(self):
        def firm(name, aliases=None):
            return Manufacturer(name=name, aliases=aliases)

        assert makersites.buds_brand(firm("Glock")) == "Glock"
        assert makersites.buds_brand(firm("Heckler Koch")) == "HK"
        assert makersites.buds_brand(firm("Springfield")) == "Springfield Armory"
        assert makersites.buds_brand(firm("Sig Sauer", "SIG")) == "Sig Sauer"
        assert makersites.buds_brand(firm("Mauser")) is None

    @pytest.mark.parametrize(
        ("name", "owner", "line"),
        [
            ("Glock 19 Gen6 Optic Ready 9mm Blue/Black Pistol", "Glock 19", "19"),
            ("Glock 19X V-Series 9mm FDE Pistol", None, "19X"),
            ("Glock 17V C4 Optics Cut 9mm Pistol", "Glock 17", "17"),
            ("Glock 17C Compensated Gen5 9mm Black Pistol", None, "17C"),
            ("Glock Branded Range Bag", None, None),
        ],
    )
    def test_a_product_goes_to_the_whole_designation(self, name, owner, line):
        rows = [FirearmModel(name="Glock 19"), FirearmModel(name="Glock 17")]
        reader = makersites.BudsReader("Glock", "Glock")
        found = reader._owner(name, rows)
        assert (found.name if found else None, reader.line(name)) == (owner, line)

    def test_a_run_for_a_maker_with_no_reader_of_its_own(self, clean_db):
        g19, g17 = _modern(clean_db, "Glock", ("Glock 19", "G19"), ("Glock 17", None))
        site = BudsSite()
        said = []
        makersites.run(clean_db, site, maker="Glock", log=said.append)
        (version,) = g19.variants
        assert (version.maker_part, version.upc, version.msrp, version.source) == (
            "P61950203",
            "764503068256",
            745.0,
            "budsgunshop",
        )
        assert version.status == ArmoryStatus.PENDING
        # The police trade-in is not a version of anything.
        assert g17.variants == []
        assert BUDS_G17 in site.asked
        # A line no model names has a few pages read, not all (2026-10-16):
        # the 43X's, with no 43X model here, and none for a product whose
        # name has no designation.
        products = [u for u in site.asked if "/products/" in u]
        assert 0 < sum("glock-43x" in u for u in products) <= 3
        assert len(products) < len(
            [
                c
                for c in makersites.buds_cards(page("buds-list1.html.gz"))
                if c.name.startswith("Glock")
            ]
        )
        # A second run takes the MSRP from the tile: no product page again.
        site.asked.clear()
        makersites.run(clean_db, site, maker="Glock", log=said.append)
        assert BUDS_G19 not in site.asked
