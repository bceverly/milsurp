"""The filtered result set, as a file.

Eleven thousand listings are worth something outside this application -- in a
spreadsheet, in a script, in anything that is not a browse page. The promise is
narrow and worth stating: **an export is what you are looking at**, so it takes
the same query parameters as the list endpoint and answers with the same rows.

The tests that matter are the ones about that promise: that a filter reaches
the file, and that the file's row count matches what the list endpoint reports
for the same query.
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from app.api.items import EXPORT_COLUMNS
from app.models import Item, Site


@pytest.fixture
def catalog(clean_db):
    site = clean_db.query(Site).first()
    if site is None:
        site = Site(slug="export-shop", name="Export Shop", base_url="https://example.com/")
        clean_db.add(site)
        clean_db.flush()
    for index, (title, caliber, price) in enumerate(
        [
            ("Mosin Nagant M91/30", "7.62x54R", 400.0),
            ("Swiss K31", "7.5x55mm Swiss", 800.0),
            ("Lee Enfield No4", ".303 British", 550.0),
        ]
    ):
        clean_db.add(
            Item(
                site_id=site.id,
                external_key=f"export-{index}",
                url=f"https://example.com/{index}",
                title=title,
                caliber=caliber,
                current_price=price,
                currency="USD",
                is_active=True,
            )
        )
    clean_db.commit()
    return site


def rows_of(response) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(response.text)))


class TestTheFileItself:
    def test_csv_is_the_default(self, client, catalog, admin_headers):
        response = client.get("/api/items/export", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")

    def test_it_arrives_as_a_download(self, client, catalog, admin_headers):
        """Without this the browser renders it instead of saving it, which is
        not what anybody clicking Export wants."""
        response = client.get("/api/items/export", headers=admin_headers)
        assert "attachment" in response.headers["content-disposition"]
        assert ".csv" in response.headers["content-disposition"]

    def test_the_columns_are_the_ones_declared(self, client, catalog, admin_headers):
        response = client.get("/api/items/export", headers=admin_headers)
        assert list(rows_of(response)[0]) == list(EXPORT_COLUMNS)

    def test_json_is_offered_too(self, client, catalog, admin_headers):
        response = client.get("/api/items/export?format=json", headers=admin_headers)
        assert response.status_code == 200
        body = json.loads(response.text)
        assert body and set(body[0]) == set(EXPORT_COLUMNS)

    def test_a_bad_format_is_refused(self, client, catalog, admin_headers):
        assert client.get("/api/items/export?format=pdf", headers=admin_headers).status_code == 422


class TestItIsWhatYouAreLookingAt:
    """The whole promise. A filter that reaches the list and not the file makes
    the export a different question's answer."""

    def test_a_caliber_filter_reaches_the_file(self, client, catalog, admin_headers):
        response = client.get(
            "/api/items/export?caliber=7.62x54R&availability=all", headers=admin_headers
        )
        titles = [row["title"] for row in rows_of(response)]
        assert titles == ["Mosin Nagant M91/30"]

    def test_a_search_term_does_too(self, client, catalog, admin_headers):
        response = client.get(
            "/api/items/export?search=Enfield&availability=all", headers=admin_headers
        )
        assert [row["title"] for row in rows_of(response)] == ["Lee Enfield No4"]

    def test_the_row_count_matches_the_list_endpoint(self, client, catalog, admin_headers):
        query = "availability=all&min_price=500"
        listed = client.get(f"/api/items?{query}&per_page=200", headers=admin_headers).json()
        exported = rows_of(client.get(f"/api/items/export?{query}", headers=admin_headers))
        assert len(exported) == listed["total"]
        assert {row["title"] for row in exported} == {item["title"] for item in listed["items"]}


class TestWhoMayAskAndForHowMuch:
    def test_it_needs_a_session(self, client, catalog):
        assert client.get("/api/items/export").status_code == 401

    def test_too_many_rows_is_refused_not_truncated(
        self, client, catalog, admin_headers, monkeypatch
    ):
        """An export that quietly stops is worse than one that says no: the
        file looks complete and is not."""
        import app.api.items as items_api

        monkeypatch.setattr(items_api, "EXPORT_LIMIT", 1)
        response = client.get("/api/items/export?availability=all", headers=admin_headers)
        assert response.status_code == 400
        assert "limit" in response.json()["detail"]
