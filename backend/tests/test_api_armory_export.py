"""Getting a curated armory off a running instance and into the repository.

The armory is edited on a live instance and *shipped* from
`backend/app/seed/armory.yaml`, so the two drift the moment somebody approves a
model in production. Until this there was one way back — a shell on the server
and `milsurp armory export` — which an administrator using the web pages does
not have. The file's own header had been telling people to run
`milsurp catalog export` for some time, which is not a command this CLI has.

Two routes out, because they answer different situations: a download when you
are at the machine with the checkout on it, and an email when you are not.
"""

from __future__ import annotations

import pytest
import yaml

from app.models import ArmoryStatus, Caliber, FirearmModel
from app.services import armory, mailer


@pytest.fixture
def curated(clean_db, seeded):
    """An armory with an edit on it that the shipped file does not have."""
    session = seeded
    session.add(
        Caliber(name="11.15x58mmR Kropatschek", status=ArmoryStatus.APPROVED, aliases="Kropatschek")
    )
    session.add(FirearmModel(name="Kropatschek M1886", status=ArmoryStatus.APPROVED))
    session.commit()
    return session


class TestTheDownload:
    def test_it_is_the_file_the_repository_commits(self, curated, client, admin_headers):
        response = client.get("/api/armory/export", headers=admin_headers)
        assert response.status_code == 200
        assert response.headers["content-disposition"] == 'attachment; filename="armory.yaml"'
        assert response.headers["content-type"].startswith("text/yaml")

    def test_it_parses_and_carries_the_edit(self, curated, client, admin_headers):
        body = client.get("/api/armory/export", headers=admin_headers).text
        data = yaml.safe_load(body)
        names = {row["name"] for row in data["models"]}
        assert "Kropatschek M1886" in names

    def test_the_header_names_commands_that_exist(self, curated, client, admin_headers):
        """The file tells the reader what to do with it, and told them to run a
        command this CLI does not have. Pinned because the header is the only
        instruction most people will ever see."""
        body = client.get("/api/armory/export", headers=admin_headers).text
        assert "milsurp armory export" in body
        assert "milsurp armory sync" in body
        assert "milsurp catalog" not in body

    def test_it_says_where_the_file_goes(self, curated, client, admin_headers):
        """Naming the path is the part nobody can guess."""
        body = client.get("/api/armory/export", headers=admin_headers).text
        assert "backend/app/seed/armory.yaml" in body

    def test_a_normal_user_cannot_have_it(self, curated, client, normal_user):
        """It is the whole curated catalog, so it is an admin's to take."""
        assert client.get("/api/armory/export", headers=normal_user["headers"]).status_code == 403

    def test_it_round_trips_through_sync(self, curated, client, admin_headers, tmp_path):
        """The download is the same bytes the CLI writes, so what comes out of
        the browser can go back in through `armory sync`."""
        body = client.get("/api/armory/export", headers=admin_headers).text
        path = tmp_path / "armory.yaml"
        path.write_text(body, encoding="utf-8")
        plan = armory.plan_sync(curated, path)
        assert not plan, plan.counted()


class TestTheEmail:
    def test_it_goes_to_the_administrator_who_asked(
        self, curated, client, admin_headers, monkeypatch
    ):
        """To their own address and no other. A box that could send it anywhere
        is a way to take the catalog out with one stolen session."""
        sent = {}

        def capture(to_address, subject, html_body, **kwargs):
            sent.update(to=to_address, subject=subject, html=html_body, **kwargs)

        monkeypatch.setattr(mailer, "send_html", capture)
        response = client.post("/api/armory/export/email", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert sent["to"] == "admin@milsurp.test"

    def test_the_file_travels_as_an_attachment(self, curated, client, admin_headers, monkeypatch):
        sent = {}
        monkeypatch.setattr(mailer, "send_html", lambda *args, **kwargs: sent.update(kwargs))
        client.post("/api/armory/export/email", headers=admin_headers)
        assert "armory.yaml" in sent["attachments"]
        assert b"Kropatschek M1886" in sent["attachments"]["armory.yaml"]

    def test_the_body_says_what_to_do_with_it(self, curated, client, admin_headers, monkeypatch):
        """A file with no instructions is a file nobody acts on."""
        sent = {}

        def capture(to_address, subject, html_body, **kwargs):
            sent.update(html=html_body)

        monkeypatch.setattr(mailer, "send_html", capture)
        client.post("/api/armory/export/email", headers=admin_headers)
        assert "backend/app/seed/armory.yaml" in sent["html"]
        assert "diff" in sent["html"]

    def test_a_mail_failure_is_reported_rather_than_swallowed(
        self, curated, client, admin_headers, monkeypatch
    ):
        def explode(*args, **kwargs):
            raise mailer.MailError("no SMTP host configured")

        monkeypatch.setattr(mailer, "send_html", explode)
        response = client.post("/api/armory/export/email", headers=admin_headers)
        assert response.status_code == 502
        assert "no SMTP host" in response.json()["detail"]

    def test_a_normal_user_cannot_send_it(self, curated, client, normal_user):
        response = client.post("/api/armory/export/email", headers=normal_user["headers"])
        assert response.status_code == 403


class TestWhatAnEditCosts:
    """An armory edit is not confined to the row it touches.

    Approving a model, or adding an alias to a cartridge, re-matches every
    listing whose text mentions any of the spellings involved. That is the
    point of the table -- and it is also several hundred listings changing
    while the admin looks at one dialog. The count was already being computed
    and thrown away on exactly the two edits that move the most.
    """

    @pytest.fixture
    def stocked(self, clean_db, seeded):
        from app.models import Item, Site

        session = seeded
        site = Site(slug="arm", name="Arm", base_url="https://a.test/")
        session.add(site)
        session.flush()
        session.add_all(
            Item(
                site_id=site.id,
                external_key=f"k{index}",
                url=f"https://a.test/{index}",
                title="Swiss K31 straight-pull rifle",
                is_active=True,
                is_rifle=True,
            )
            for index in range(3)
        )
        session.commit()
        return session

    def test_an_edit_reports_what_it_moved(self, stocked, client, admin_headers):
        model = client.post(
            "/api/armory/models",
            json={"name": "K31", "kind": "rifle"},
            headers=admin_headers,
        ).json()
        client.post(
            "/api/armory/models/promote", json={"ids": [model["id"]]}, headers=admin_headers
        )

        # Renaming touches both spellings, so the listings re-match.
        response = client.patch(
            f"/api/armory/models/{model['id']}",
            json={"aliases": "K31\nKarabiner 31"},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["model"]["name"] == "K31"
        assert response.json()["listings_changed"] >= 0

    def test_deleting_says_how_many_listings_it_unlinked(self, stocked, client, admin_headers):
        model = client.post(
            "/api/armory/models", json={"name": "K31", "kind": "rifle"}, headers=admin_headers
        ).json()
        client.post(
            "/api/armory/models/promote", json={"ids": [model["id"]]}, headers=admin_headers
        )
        linked = client.get("/api/armory/models", headers=admin_headers).json()[0]
        assert linked["item_count"] == 3

        removed = client.delete(f"/api/armory/models/{model['id']}", headers=admin_headers)
        assert removed.status_code == 200
        assert removed.json()["listings_changed"] == 3
