"""Reading a maker's site for a model's variants (app.services.makersites).

Slice 3 of "New-gun prices" in ROADMAP.md. Ruger's pages are recorded: the
LCP's model cards and one spec sheet. Kimber's and Walther's were recorded on
2026-10-11: Kimber's sitemap and three product pages, Walther's home page (its
navigation) and two line pages.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from app.models import ArmoryStatus, Caliber, FirearmModel, Manufacturer
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
    def get_text(self, url, **_kwargs):
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
