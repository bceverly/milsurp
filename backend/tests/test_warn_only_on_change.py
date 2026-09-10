"""A warning is for something that changed.

Two conditions were making sites permanently PARTIAL over facts nobody could
act on, and a site that is always PARTIAL teaches whoever reads the scan list
that PARTIAL means nothing:

* **A photograph that has run out of retries.** Classic Firearms' four recorded
  scans were four PARTIALs, all of them one photograph of a BM-59 whose file
  their own CDN has 404'd since 7 September — while their product page still
  links it. The other eleven photographs are here.
* **A product page the shop will not serve.** One Bowman Arms parts kit sits in
  a category restricted to signed-in customers, and their server says so in as
  many words: "You Do Not Have Permission To Access This Page".

Neither is a fault. Both stay visible — in the scan log, and on the row — and
both still warn on the scan where they *first* happen.
"""

from __future__ import annotations

import pytest

from app.scrapers.base import VENDOR_ANSWERS, ScrapeError, vendors_answer


class TestTellingAShopsAnswerFromAFault:
    @pytest.mark.parametrize("status", sorted(VENDOR_ANSWERS))
    def test_a_refusal_or_a_removal_is_the_shops_answer(self, status):
        assert vendors_answer(ScrapeError("nope", status=status))

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
    def test_a_server_problem_is_not(self, status):
        """A 500 may be gone tomorrow and a 429 is a pace to slow to. Those are
        worth warning about."""
        assert not vendors_answer(ScrapeError("boom", status=status))

    def test_nor_is_a_failure_with_no_status_at_all(self):
        """A timeout or a dropped connection never got an answer."""
        assert not vendors_answer(ScrapeError("connection reset"))
        assert not vendors_answer(OSError("timed out"))

    def test_the_status_is_carried_rather_than_parsed_out_of_the_message(self):
        """The alternative is matching on the text of an error, which changes
        whenever somebody rewords it."""
        error = ScrapeError("GET https://shop.test/x failed after 4 attempts: 403", status=403)
        assert error.status == 403
        assert vendors_answer(error)


class TestASingleRefusedProductPageIsLoggedNotWarned:
    """Bowman Arms' gated parts kit. A run of them still warns — that guard is
    older than this and is what catches a shop refusing everything."""

    def scraper_with(self, ctx_factory, monkeypatch, exc):
        from app.scrapers.base import ScrapedItem
        from app.scrapers.bowman_arms import BowmanArmsScraper

        scraper = BowmanArmsScraper()
        scraper._detail_failures = 0
        scraper._gave_up_on_details = False
        context = ctx_factory()

        def refuse(_url, **_kwargs):
            raise exc

        monkeypatch.setattr(context, "get_text", refuse)
        item = ScrapedItem(
            external_key="bc-1",
            url="https://bowmanarms.com/deals-of-the-week/colt-653-parts-kit/",
            title="Colt 653 Parts Kit",
        )
        return scraper, context, item

    def test_a_403_does_not_downgrade_the_run(self, ctx_factory, monkeypatch):
        scraper, context, item = self.scraper_with(
            ctx_factory, monkeypatch, ScrapeError("403 Forbidden", status=403)
        )
        got = scraper.with_detail(context, item)

        assert got is not None, "the catalog entry must survive"
        assert context.warnings == []

    def test_but_it_is_still_said(self, ctx_factory, monkeypatch):
        """Silence would be worse: a listing quietly missing its description
        and gallery, with nothing anywhere explaining why."""
        lines: list[str] = []
        scraper, context, item = self.scraper_with(
            ctx_factory, monkeypatch, ScrapeError("403 Forbidden", status=403)
        )
        context._progress = lines.append
        scraper.with_detail(context, item)

        assert any("Could not read" in line for line in lines)

    def test_a_server_error_still_warns(self, ctx_factory, monkeypatch):
        """The distinction is the point. A 500 is the shop breaking, not the
        shop deciding."""
        scraper, context, item = self.scraper_with(
            ctx_factory, monkeypatch, ScrapeError("500 Server Error", status=500)
        )
        scraper.with_detail(context, item)

        assert context.warnings, "a fault must still downgrade the run"

    def test_a_run_of_refusals_still_warns(self, ctx_factory, monkeypatch):
        """Which is what catches a shop that has started refusing everything —
        the case this must not hide."""
        scraper, context, item = self.scraper_with(
            ctx_factory, monkeypatch, ScrapeError("403 Forbidden", status=403)
        )
        for _ in range(scraper.MAX_DETAIL_FAILURES):
            scraper.with_detail(context, item)

        assert context.warnings, "a whole catalog being refused must be reported"
        assert scraper._gave_up_on_details is True


class TestStopIsHeardWhileAScanIsWaiting:
    """Checkpoint Charlie's: pressing Stop did nothing for several minutes.

    Not a lost flag — a deaf one. They answer 429, the context slows to as much
    as five minutes between requests, and each failed request sleeps again
    between retries. The cancel flag was set the moment the button was pressed;
    the run simply was not looking at it until the sleep ended, and by then it
    had started another request.

    **A scan spends most of its life asleep**, so a wait that cannot be
    interrupted is a Stop button that does not work.
    """

    def test_a_long_wait_ends_as_soon_as_stop_is_pressed(self, ctx_factory):
        import time

        from app.scrapers.base import ScrapeCanceled

        stopped = False
        context = ctx_factory(should_stop=lambda: stopped)

        # Pressed a moment into a five-minute wait, which is the pace this
        # context reaches after a host refuses at every slower one.
        began = time.monotonic()
        stopped = True
        with pytest.raises(ScrapeCanceled):
            context.sleep(300)

        assert time.monotonic() - began < 1.0

    def test_a_wait_nobody_interrupts_still_waits(self, ctx_factory):
        import time

        context = ctx_factory()
        began = time.monotonic()
        context.sleep(0.4)
        assert time.monotonic() - began >= 0.35

    def test_it_checks_before_sleeping_at_all(self, ctx_factory):
        """A run already canceled must not serve out one more wait first."""
        import time

        from app.scrapers.base import ScrapeCanceled

        context = ctx_factory(should_stop=lambda: True)
        began = time.monotonic()
        with pytest.raises(ScrapeCanceled):
            context.sleep(300)
        assert time.monotonic() - began < 0.1

    def test_the_politeness_delay_goes_through_it(self):
        """The long one. Every wait in a scrape has to be interruptible or the
        button only works between requests — which on a slowed host is minutes
        apart."""
        import inspect

        from app.scrapers.base import ScrapeContext

        source = inspect.getsource(ScrapeContext._throttle)
        assert "self.sleep(" in source
        assert "time.sleep(" not in source

    def test_and_so_does_the_retry_backoff(self):
        import inspect

        from app.scrapers.base import ScrapeContext

        source = inspect.getsource(ScrapeContext.get)
        assert "self.sleep(" in source
        assert "time.sleep(" not in source

    def test_the_photo_loop_can_be_stopped_mid_wait_too(self):
        """Same shape, different loop: a host pacing photographs a minute apart
        leaves the download batch asleep almost all of the time."""
        import time

        from app.config import get_config
        from app.services.image_store import ImageStore

        store = ImageStore(get_config(), should_stop=lambda: True)
        began = time.monotonic()
        store._sleep(60)
        assert time.monotonic() - began < 0.1
