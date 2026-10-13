"""Each model's own page on its maker's site (app.services.makerpages).

Asked for on 2026-10-12, in place of a search of the maker's site. The cases
are the ones the first pass over production's 218 models in modern production
got right and wrong, read from the makers' real sitemaps that day.
"""

from __future__ import annotations

from app.models import ArmoryStatus, FirearmModel, Manufacturer, ReferenceProposal
from app.services import makerpages, wikipedia

GLOCK = [
    "https://us.glock.com/en/products/law-enforcement/pistols/g19",
    "https://us.glock.com/en/products/commercial-firearms/pistols/g19",
    "https://us.glock.com/en/products/commercial-firearms/pistols/g19x",
    "https://us.glock.com/en/products/commercial-firearms/pistols/g43x-us",
    "https://us.glock.com/en/products/commercial-firearms/pistols/g43",
]
SMITH = [
    "https://www.smith-wesson.com/product/model-103-1-handcuffs",
    "https://www.smith-wesson.com/product/model-640",
    "https://www.smith-wesson.com/product/model-442",
    "https://www.smith-wesson.com/products/shield-ez",
    "https://www.smith-wesson.com/products/shield-plus",
]


class TestBestPage:
    def test_a_glock_number_is_its_g_number(self):
        found = makerpages.best_page(GLOCK, ["Glock 19"], ["Glock"])
        # The public page, not the agencies' one listing the same pistol.
        assert found.url.endswith("/commercial-firearms/pistols/g19")
        assert found.confident

    def test_a_suffix_does_not_take_the_shorter_name(self):
        found = makerpages.best_page(GLOCK, ["Glock 43X"], ["Glock"])
        assert found.url.endswith("/g43x-us")
        assert makerpages.best_page(GLOCK, ["Glock 43"], ["Glock"]).url.endswith("/g43")

    def test_a_number_inside_a_longer_number_is_not_a_match(self):
        """ "Model 10" took a page for handcuffs, "model-103-1-handcuffs", and
        "Model 64" the Model 640 -- a run-together name found inside a word."""
        smith = ["Smith & Wesson", "S&W"]
        assert makerpages.best_page(SMITH, ["Smith & Wesson Model 10"], smith) is None
        assert makerpages.best_page(SMITH, ["Smith & Wesson Model 64"], smith) is None
        assert makerpages.best_page(SMITH, ["Smith & Wesson Model 640"], smith).confident

    def test_a_review_or_a_notice_is_not_the_product(self):
        pages = [
            "https://www.kahr.com/kahr-arms-cw380-pistol-review/",
            "https://www.kahr.com/kahr-arms-introduces-the-ct380/",
            "https://www.taurususa.com/gx4safetynotice/",
            "https://www.taurususa.com/journal-entry/g3-trigger/",
        ]
        assert makerpages.best_page(pages, ["CW380"], ["Kahr"]) is None
        assert makerpages.best_page(pages, ["CT380"], ["Kahr"]) is None
        assert makerpages.best_page(pages, ["GX4"], ["Taurus"]) is None
        assert makerpages.best_page(pages, ["Taurus G3"], ["Taurus"]) is None

    def test_the_makers_name_and_the_catalogs_words_do_not_count_against_it(self):
        pages = ["https://www.taurususa.com/firearms/revolvers/taurus-judge/"]
        assert makerpages.best_page(pages, ["Taurus Judge"], ["Taurus"]).confident


class TestTheTitle:
    def test_a_page_is_called_by_its_name_not_its_file(self):
        """Every Ruger suggestion was titled "models.html" on the review tab."""
        assert makerpages._title("https://ruger.com/products/sp101/models.html") == "sp101"
        assert makerpages._title("https://shadowsystemscorp.com/cr920/") == "cr920"


class FakeSite:
    """robots.txt naming an index, the index naming two sitemaps, one per country."""

    PAGES = {
        "https://www.maker.test/robots.txt": "Sitemap: https://www.maker.test/sitemap.xml\n",
        "https://www.maker.test/sitemap.xml": (
            "<sitemapindex><sitemap><loc>https://www.maker.test/de-at/sitemap.xml</loc>"
            "</sitemap><sitemap><loc>https://www.maker.test/en-us/sitemap.xml</loc>"
            "</sitemap></sitemapindex>"
        ),
        "https://www.maker.test/de-at/sitemap.xml": (
            "<urlset><url><loc>https://www.maker.test/de-at/product/apx</loc></url></urlset>"
        ),
        "https://www.maker.test/en-us/sitemap.xml": (
            "<urlset><url><loc>https://www.maker.test/en-us/product/apx</loc></url></urlset>"
        ),
    }

    def __init__(self):
        self.asked = []

    def get_text(self, url, **_kwargs):
        from app.scrapers.base import ScrapeError

        self.asked.append(url)
        if url not in self.PAGES:
            raise ScrapeError(f"GET {url}: 404")
        return self.PAGES[url]


class TestTheSitemap:
    def test_the_makers_own_section_is_read_and_kept(self):
        """Beretta's robots.txt lists a sitemap per country, Austria's first,
        and the first pass matched every Beretta to a German page."""
        pages = makerpages.sitemap_pages(FakeSite(), "https://www.maker.test/en-us", print)
        assert pages == ["https://www.maker.test/en-us/product/apx"]


class TestProposingAndAccepting:
    def _model(self, session):
        maker = Manufacturer(
            name="Maker", website="https://www.maker.test/en-us", status=ArmoryStatus.APPROVED
        )
        model = FirearmModel(name="Maker APX", status=ArmoryStatus.APPROVED, modern_production=True)
        model.manufacturers = [maker]
        session.add_all([maker, model])
        session.commit()
        return model

    def test_a_find_is_proposed_and_accepting_writes_the_page(self, clean_db):
        model = self._model(clean_db)
        counts = makerpages.run(clean_db, FakeSite(), log=lambda _m: None)
        assert (counts["asked"], counts["proposed"]) == (1, 1)
        [proposal] = clean_db.query(ReferenceProposal).all()
        assert (proposal.field, proposal.target_id) == ("maker_page", model.id)
        assert wikipedia.accept(clean_db, [proposal.id], None) == 1
        clean_db.refresh(model)
        assert model.maker_url == "https://www.maker.test/en-us/product/apx"
        assert model.wikipedia_url is None

    def test_running_it_twice_proposes_nothing_twice(self, clean_db):
        """Two runs at once on 2026-10-13: the second failed on the first one's
        rows and lost its whole batch."""
        model = self._model(clean_db)
        makerpages.run(clean_db, FakeSite(), log=lambda _m: None)
        # As if a second run had drawn up its list before the first saved.
        clean_db.add(
            ReferenceProposal(
                field="maker_page",
                target_type="model",
                target_id=model.id,
                url="https://www.maker.test/en-us/other",
                title="other",
            )
        )
        clean_db.commit()
        again = makerpages.run(clean_db, FakeSite(), log=lambda _m: None)
        assert again["proposed"] == 0
        assert clean_db.query(ReferenceProposal).count() == 2

    def test_a_rejected_model_is_not_asked_about_again(self, clean_db):
        self._model(clean_db)
        makerpages.run(clean_db, FakeSite(), log=lambda _m: None)
        [proposal] = clean_db.query(ReferenceProposal).all()
        wikipedia.reject(clean_db, [proposal.id])
        again = makerpages.run(clean_db, FakeSite(), log=lambda _m: None)
        assert again["asked"] == 0

    def test_the_tabs_ask_for_one_kind_each(self, client, admin_headers, clean_db):
        self._model(clean_db)
        makerpages.run(clean_db, FakeSite(), log=lambda _m: None)
        makers = client.get(
            "/api/armory/references", params={"field": "maker_page"}, headers=admin_headers
        ).json()
        articles = client.get(
            "/api/armory/references", params={"field": "wikipedia"}, headers=admin_headers
        ).json()
        assert [row["field"] for row in makers] == ["maker_page"]
        assert articles == []


class TestTheTabsViews:
    """Showing on the Manufacturer pages tab (2026-10-13)."""

    def test_the_rejected_ones_are_listed_and_can_be_accepted_anyway(
        self, client, admin_headers, clean_db
    ):
        model = TestProposingAndAccepting()._model(clean_db)
        makerpages.run(clean_db, FakeSite(), log=lambda _m: None)
        [proposal] = clean_db.query(ReferenceProposal).all()
        wikipedia.reject(clean_db, [proposal.id])

        def listed(status):
            return client.get(
                "/api/armory/references",
                params={"field": "maker_page", "status": status},
                headers=admin_headers,
            ).json()

        assert listed("pending") == []
        assert [(row["id"], row["status"]) for row in listed("rejected")] == [
            (proposal.id, "rejected")
        ]
        taken = client.post(
            "/api/armory/references/accept", json={"ids": [proposal.id]}, headers=admin_headers
        ).json()
        assert taken["changed"] == 1
        clean_db.refresh(model)
        assert model.maker_url == "https://www.maker.test/en-us/product/apx"
        assert [row["status"] for row in listed("all")] == ["accepted"]
