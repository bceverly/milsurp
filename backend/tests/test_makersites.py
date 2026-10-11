"""Reading a maker's site for a model's variants (app.services.makersites).

Slice 3 of "New-gun prices" in ROADMAP.md. Ruger's pages are recorded: the
LCP's model cards and one spec sheet.
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
