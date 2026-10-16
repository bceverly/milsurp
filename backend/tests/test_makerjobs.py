"""The reads of the manufacturers' own sites, started from Site settings
(app.services.makerjobs, 2026-10-13): the MSRP readers had never been run in
production because the only way to was a command on the server."""

from __future__ import annotations

from app.models import Item, ManufacturerJob, Site, utcnow
from app.services import makerjobs, makerpages, makersites


class TestAsking:
    def test_a_job_asked_for_is_waiting_and_a_run_clears_it(self, clean_db, monkeypatch):
        monkeypatch.setattr(
            makersites,
            "run",
            lambda *_a, **_k: {"models": 3, "proposed": 7, "refreshed": 1, "unread": 0},
        )
        assert makerjobs.requested(clean_db) == []
        makerjobs.ask(clean_db, "variants")
        assert makerjobs.requested(clean_db) == ["variants"]
        summary = makerjobs.run(clean_db, object(), "variants", log=lambda _m: None)
        assert summary.startswith("Read 3 model(s): 7 variant(s) proposed")
        row = clean_db.get(ManufacturerJob, "variants")
        assert (row.requested_at, row.last_status) == (None, "ok")
        assert makerjobs.requested(clean_db) == []

    def test_a_failure_is_recorded_not_raised(self, clean_db, monkeypatch):
        def broken(*_a, **_k):
            raise RuntimeError("the site moved")

        monkeypatch.setattr(makerpages, "run", broken)
        makerjobs.ask(clean_db, "pages")
        assert makerjobs.run(clean_db, object(), "pages", log=lambda _m: None) == (
            "Failed: the site moved"
        )
        assert clean_db.get(ManufacturerJob, "pages").last_status == "failed"


class TestWhileItRuns:
    """Asked for on 2026-10-16: whether a job is running, and how far it has
    got; its last time and status, success, warning or failure."""

    def test_running_shows_its_start_and_its_progress(self, clean_db, monkeypatch):
        seen = {}

        def reading(session, _ctx, *, log, **_k):
            log("Bud's Gun Shop: Glock (12 of 34 makers)")
            log("  Glock 19: 8 found on Bud's Gun Shop")  # a detail, not a heading
            row = session.get(ManufacturerJob, "variants")
            seen["running"] = (row.started_at is not None, row.progress)
            return {"models": 1, "proposed": 0, "refreshed": 0, "unread": 0}

        monkeypatch.setattr(makersites, "run", reading)
        makerjobs.ask(clean_db, "variants")
        makerjobs.run(clean_db, object(), "variants", log=lambda _m: None)
        assert seen["running"] == (True, "Bud's Gun Shop: Glock (12 of 34 makers)")
        row = clean_db.get(ManufacturerJob, "variants")
        assert (row.started_at, row.progress, row.last_status) == (None, None, "ok")

    def test_a_site_that_errs_is_a_warning(self, clean_db, monkeypatch):
        monkeypatch.setattr(
            makersites,
            "run",
            lambda *_a, **_k: {
                "models": 3,
                "proposed": 0,
                "refreshed": 2,
                "unread": 1,
                "errors": 1,
            },
        )
        makerjobs.ask(clean_db, "variants")
        summary = makerjobs.run(clean_db, object(), "variants", log=lambda _m: None)
        assert clean_db.get(ManufacturerJob, "variants").last_status == "warning"
        assert "1 maker site(s) answered with an error" in summary

    def test_a_run_the_service_restarted_under_is_interrupted(self, clean_db):
        row = makerjobs.job(clean_db, "variants")
        row.started_at = utcnow()
        row.progress = "Bud's Gun Shop: Sig Sauer (2 of 34 makers)"
        clean_db.commit()
        assert makerjobs.reap_interrupted(clean_db) == 1
        assert (row.started_at, row.last_status) == (None, "interrupted")
        assert "Sig Sauer (2 of 34 makers)" in row.last_summary
        assert makerjobs.reap_interrupted(clean_db) == 0

    def test_the_api_says_so(self, client, admin_headers, clean_db):
        row = makerjobs.job(clean_db, "variants")
        row.started_at = utcnow()
        row.progress = "Kimber: its own site (4 of 34 makers)"
        clean_db.commit()
        shown = client.get("/api/manufacturer-data", headers=admin_headers).json()
        variants = next(job for job in shown if job["name"] == "variants")
        assert variants["progress"] == "Kimber: its own site (4 of 34 makers)"
        assert variants["started_at"] is not None


class TestTheBarrels:
    """Site settings' "Re-read barrels" (2026-10-14): no site asked, every
    stored gun's barrel read again from its own words."""

    def test_it_reads_every_gun_again(self, clean_db):
        site = Site(slug="rb", name="Shop RB", base_url="https://rb.test/")
        clean_db.add(site)
        clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key="a",
            url="https://rb.test/a",
            title="Beretta 70 .32 ACP w/ Threaded Barrel",
            description='with a 3.5" barrel',
            is_pistol=True,
        )
        clean_db.add(item)
        clean_db.commit()
        assert item.barrel_inches is None
        makerjobs.ask(clean_db, "barrels")
        summary = makerjobs.run(clean_db, object(), "barrels", log=lambda _m: None)
        assert summary.startswith("Read 1 gun(s): 1 barrel length(s), 1 threaded")
        clean_db.refresh(item)
        assert (item.barrel_inches, item.barrel_threaded) == (3.5, True)
        assert clean_db.get(ManufacturerJob, "barrels").last_status == "ok"


class TestTheApi:
    def test_an_administrator_asks_and_sees_it_waiting(self, client, admin_headers, clean_db):
        shown = client.get("/api/manufacturer-data", headers=admin_headers).json()
        assert [row["name"] for row in shown] == ["variants", "pages", "barrels"]
        asked = client.post("/api/manufacturer-data/variants/run", headers=admin_headers)
        assert asked.status_code == 200, asked.text
        by_name = {row["name"]: row for row in asked.json()}
        assert by_name["variants"]["requested_at"] is not None
        assert by_name["pages"]["requested_at"] is None
        assert (
            client.post("/api/manufacturer-data/nonsense/run", headers=admin_headers).status_code
            == 404
        )

    def test_only_an_administrator(self, client, normal_user):
        assert (
            client.get("/api/manufacturer-data", headers=normal_user["headers"]).status_code == 403
        )


class TestTheSchedulerRunsIt:
    class Pool:
        def __init__(self):
            self.submitted = []

        def submit(self, fn, *args):
            self.submitted.append((fn.__name__, args))

            class Pending:
                def done(self):
                    return False

            return Pending()

    def test_a_request_goes_to_the_reference_worker(self, clean_db, app_config):
        from app.scheduler import Scheduler

        makerjobs.ask(clean_db, "pages")
        scheduler = Scheduler(app_config)
        scheduler._photo_pool, scheduler._background_pool = self.Pool(), self.Pool()
        scheduler._dispatch_maker_jobs()
        assert scheduler._background_pool.submitted == [("_run_maker_job", ("pages",))]
        assert scheduler._photo_pool.submitted == []
