"""Wikipedia articles for makers and models (app.services.wikipedia).

Proposed from Wikipedia's own search, judged by the article's categories, and
written onto a row only when somebody accepts them. Asked for on 2026-10-11.
"""

from __future__ import annotations

from app.models import ArmoryStatus, Caliber, FirearmModel, Manufacturer, ReferenceProposal
from app.services import wikipedia


class FakeWikipedia:
    """Answers search and category queries from two dictionaries."""

    def __init__(self, results, categories):
        self.results = results
        self.categories = categories
        self.asked = []

    def __call__(self, params):
        self.asked.append(params)
        if params.get("list") == "search":
            hits = self.results.get(params["srsearch"], [])
            return {"query": {"search": [{"title": t} for t in hits]}}
        titles = params["titles"].split("|")
        return {
            "query": {
                "pages": [
                    {
                        "title": t,
                        "categories": [{"title": c} for c in self.categories.get(t, [])],
                    }
                    for t in titles
                ]
            }
        }


def _rows(session):
    mauser = Manufacturer(name="Mauser", status=ArmoryStatus.APPROVED)
    k98 = FirearmModel(name="Karabiner 98k", status=ArmoryStatus.APPROVED, aliases="K98k")
    k98.manufacturers = [mauser]
    linked = FirearmModel(
        name="M1 Garand",
        status=ArmoryStatus.APPROVED,
        wikipedia_url="https://en.wikipedia.org/wiki/M1_Garand",
    )
    session.add_all([mauser, k98, linked])
    session.commit()
    return mauser, k98


FAKE = FakeWikipedia(
    results={
        "Mauser firearms": ["Mauser"],
        "Mauser Karabiner 98k": ["Karabiner 98k", "Mauser Model 1898"],
    },
    categories={
        "Mauser": ["Category:Firearm manufacturers of Germany"],
        "Karabiner 98k": ["Category:Bolt-action rifles", "Category:World War II infantry weapons"],
    },
)


class TestProposing:
    def test_a_row_without_a_link_gets_a_proposal_and_a_linked_one_none(self, clean_db):
        mauser, k98 = _rows(clean_db)
        counts = wikipedia.run(clean_db, FAKE, log=lambda _m: None)
        assert counts == {"asked": 2, "proposed": 2, "confident": 2, "nothing": 0}
        proposals = {
            (p.target_type, p.target_id): p for p in clean_db.query(ReferenceProposal).all()
        }
        assert proposals[("manufacturer", mauser.id)].url == "https://en.wikipedia.org/wiki/Mauser"
        model = proposals[("model", k98.id)]
        assert model.url == "https://en.wikipedia.org/wiki/Karabiner_98k"
        assert model.confident
        assert "Bolt-action rifles" in model.reason
        # Nothing is written to a row until somebody accepts it.
        assert k98.wikipedia_url is None

    def test_an_article_that_is_not_about_a_gun_is_not_proposed(self, clean_db):
        _rows(clean_db)
        paris = FakeWikipedia(
            {"Mauser firearms": ["Mauser (surname)"], "Mauser Karabiner 98k": ["98k (song)"]},
            {"Mauser (surname)": ["Category:German-language surnames"]},
        )
        counts = wikipedia.run(clean_db, paris, log=lambda _m: None)
        assert (counts["proposed"], counts["nothing"]) == (0, 2)

    def test_a_title_that_does_not_name_the_row_is_proposed_but_not_confident(self):
        found = wikipedia.candidate(
            FakeWikipedia(
                {"q": ["Gewehr 98"]}, {"Gewehr 98": ["Category:Bolt-action rifles of Germany"]}
            ),
            "q",
            ["Karabiner 98k", "K98k"],
            "model",
            set(),
        )
        assert (found.title, found.confident) == ("Gewehr 98", False)

    def test_a_rerun_skips_what_is_pending_and_never_repeats_a_rejection(self, clean_db):
        _rows(clean_db)
        wikipedia.run(clean_db, FAKE, log=lambda _m: None)
        again = wikipedia.run(clean_db, FAKE, log=lambda _m: None)
        assert again["asked"] == 0
        k98 = clean_db.query(ReferenceProposal).filter_by(target_type="model").one()
        wikipedia.reject(clean_db, [k98.id])
        # The search's second result is a gun article too, and would be the
        # next guess -- which is what filled the queue on 2026-10-12. A row a
        # person has said no to is not asked about again.
        second = FakeWikipedia(
            results=FAKE.results,
            categories={**FAKE.categories, "Mauser Model 1898": ["Category:Bolt-action rifles"]},
        )
        third = wikipedia.run(clean_db, second, log=lambda _m: None)
        assert third["asked"] == 0
        urls = {p.url for p in clean_db.query(ReferenceProposal).filter_by(target_type="model")}
        assert urls == {"https://en.wikipedia.org/wiki/Karabiner_98k"}

    def test_a_caliber_named_by_a_bare_size_is_never_asked_about(self, clean_db):
        clean_db.add_all(
            [
                Caliber(name=".44", status=ArmoryStatus.APPROVED),
                Caliber(name="6mm", status=ArmoryStatus.APPROVED),
                Caliber(name=".30 Caliber", status=ArmoryStatus.APPROVED),
            ]
        )
        clean_db.commit()
        counts = wikipedia.run(clean_db, FAKE, kinds=("caliber",), log=lambda _m: None)
        assert counts["asked"] == 0


class TestDeciding:
    def test_accepting_writes_the_link_and_is_audited(self, clean_db):
        _mauser, k98 = _rows(clean_db)
        wikipedia.run(clean_db, FAKE, log=lambda _m: None)
        ids = [p.id for p in clean_db.query(ReferenceProposal).all()]
        assert wikipedia.accept(clean_db, ids, None) == 2
        clean_db.refresh(k98)
        assert k98.wikipedia_url == "https://en.wikipedia.org/wiki/Karabiner_98k"
        assert wikipedia.pending(clean_db) == []

    def test_the_page_lists_accepts_and_rejects(self, client, admin_headers, clean_db):
        _rows(clean_db)
        wikipedia.run(clean_db, FAKE, log=lambda _m: None)
        listed = client.get("/api/armory/references", headers=admin_headers).json()
        assert {p["target_name"] for p in listed} == {"Mauser", "Karabiner 98k"}
        taken = client.post("/api/armory/references/accept-confident", headers=admin_headers)
        assert taken.json()["changed"] == 2
        assert client.get("/api/armory/references", headers=admin_headers).json() == []

    def test_only_an_administrator_may(self, client, normal_user):
        response = client.get("/api/armory/references", headers=normal_user["headers"])
        assert response.status_code == 403


class TestTheListingLinksTheMaker:
    def test_the_detail_carries_the_makers_article(self, client, admin_headers, clean_db):
        from app.models import Item, Site

        maker = Manufacturer(
            name="Mauser",
            status=ArmoryStatus.APPROVED,
            wikipedia_url="https://en.wikipedia.org/wiki/Mauser",
        )
        site = Site(slug="wk", name="Shop WK", base_url="https://wk.test/")
        clean_db.add_all([maker, site])
        clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key="k",
            url="https://wk.test/k",
            title="German K98k",
            manufacturer="Mauser",
            is_rifle=True,
        )
        clean_db.add(item)
        clean_db.commit()
        shown = client.get(f"/api/items/{item.id}", headers=admin_headers).json()
        assert shown["maker_wikipedia_url"] == "https://en.wikipedia.org/wiki/Mauser"


class TestJudgingAnArticle:
    def test_a_person_is_not_a_gun_or_a_firm(self):
        """ "Arisaka" found the colonel, who sits in rifle categories too."""
        found = wikipedia.candidate(
            FakeWikipedia(
                {"Arisaka firearms": ["Arisaka Nariakira"]},
                {
                    "Arisaka Nariakira": [
                        "Category:1841 births",
                        "Category:Firearm manufacturers of Japan",
                    ]
                },
            ),
            "Arisaka firearms",
            ["Arisaka"],
            "manufacturer",
            set(),
        )
        assert found is None

    def test_accents_and_an_encyclopedias_extra_words_still_name_the_row(self):
        assert wikipedia.names_it("J. G. Anschütz", ["Anschutz"])
        assert wikipedia.names_it("AA-52 machine gun", ["AA52"])
        assert wikipedia.names_it("Auto-Ordnance Corporation", ["Auto-Ordnance"])
        assert not wikipedia.names_it("ASTAR (company)", ["Astra"])
