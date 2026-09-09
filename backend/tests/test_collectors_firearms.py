"""Collectors Firearms: which sections a run reads, and which it skips.

Their catalog is nine sections behind a thirty-second crawl delay, so a full
pass is hours. The scraper reads their category sitemap first and skips any
section whose ``lastmod`` predates our last successful scan.

These tests are about the one decision that saving turns on -- **is it safe to
not read this?** -- because getting it wrong is silent both ways: skip a
section we have never read and its listings never arrive; fail to declare a
skipped section unread and its listings are de-listed as though the shop had
emptied them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scrapers.collectors_firearms import CollectorsFirearmsScraper

#: Two sections edited long ago, two edited since. Only the paths matter.
SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset>
  <url>
    <loc>https://collectorsfirearms.com/product-category/rifles/foreign-military-rifles/</loc>
    <lastmod>2026-09-01T10:00:00+00:00</lastmod>
  </url>
  <url>
    <loc>https://collectorsfirearms.com/product-category/antique-long-guns/u-s-military-antique-long-guns/</loc>
    <lastmod>2026-09-01T10:00:00+00:00</lastmod>
  </url>
  <url>
    <loc>https://collectorsfirearms.com/product-category/modern-handguns/lugers/</loc>
    <lastmod>2026-09-09T10:00:00+00:00</lastmod>
  </url>
</urlset>
"""

LAST_SUCCESS = datetime(2026, 9, 8, 8, 33, tzinfo=UTC)


@pytest.fixture
def ctx(ctx_factory):
    """A context that answers the sitemap request and nothing else."""

    def build(*, stored_categories=(), last_success_at=LAST_SUCCESS, sitemap=SITEMAP):
        context = ctx_factory(last_success_at=last_success_at, stored_categories=stored_categories)
        context.get_text = lambda url, **_: sitemap  # type: ignore[method-assign]
        return context

    return build


class TestWhichSectionsAreSkipped:
    def unchanged(self, context):
        """The section URLs the scraper believes have not moved."""
        return CollectorsFirearmsScraper()._changed_since(context)

    def test_a_section_the_shop_edited_after_our_last_scan_is_not_skipped(self, ctx):
        lugers = "https://collectorsfirearms.com/product-category/modern-handguns/lugers/"
        assert lugers not in self.unchanged(ctx())

    def test_a_section_untouched_since_then_is_a_candidate_to_skip(self, ctx):
        rifles = "https://collectorsfirearms.com/product-category/rifles/foreign-military-rifles/"
        assert rifles in self.unchanged(ctx())

    def test_with_no_previous_success_every_section_is_walked(self, ctx):
        """There is no "since" to compare against, so the question cannot be
        asked and the honest answer is to read everything."""
        assert self.unchanged(ctx(last_success_at=None)) is None

    def test_an_unreadable_sitemap_walks_every_section_too(self, ctx, ctx_factory):
        """One failed request must not turn into nine unread sections."""
        context = ctx_factory(last_success_at=LAST_SUCCESS)

        def refuse(_url, **_kwargs):
            raise OSError("connection reset")

        context.get_text = refuse  # type: ignore[method-assign]
        assert self.unchanged(context) is None


class TestUnchangedIsNotTheSameAsAlreadyRead:
    """The bug this class exists for, in the words of the run that had it:

        [15:28:15] U.S. Military Antique Long Guns: unchanged since the last
                   scan; skipping it.

    It was unchanged. It was also 132 listings that had never been read: the
    section was added as a source *after* the last successful scan, so there
    was nothing stored under it and nothing to compare. Skipping on
    "unchanged" alone closes the trap permanently, because a section nobody
    opens never changes either -- it would have been skipped again on every
    future run, and five more new sections were still ahead of that one.
    """

    def sections_read(self, context, monkeypatch):
        """Which sections a run would actually walk."""
        scraper = CollectorsFirearmsScraper()
        walked = []

        def record(_ctx, source, _seen):
            walked.append(source["category"])
            return iter(())

        monkeypatch.setattr(scraper, "_walk", record)
        list(scraper._stream(context))
        return walked

    def test_an_unchanged_section_we_have_never_read_is_read_anyway(self, ctx, monkeypatch):
        walked = self.sections_read(ctx(stored_categories=()), monkeypatch)
        assert "U.S. Military Antique Long Guns" in walked
        assert "Foreign Military Rifles" in walked

    def test_and_the_reason_is_logged_rather_than_left_to_be_inferred(self, ctx, monkeypatch):
        lines = []
        context = ctx(stored_categories=())
        context._progress = lines.append
        self.sections_read(context, monkeypatch)
        assert any("nothing is stored from it yet; reading it" in line for line in lines)

    def test_once_it_has_been_read_the_saving_applies_as_before(self, ctx, monkeypatch):
        """The optimization is not being thrown away -- it is being made to
        wait until it is true."""
        walked = self.sections_read(
            ctx(stored_categories={"Foreign Military Rifles", "U.S. Military Antique Long Guns"}),
            monkeypatch,
        )
        assert "Foreign Military Rifles" not in walked
        assert "U.S. Military Antique Long Guns" not in walked
        assert "Lugers" in walked

    def test_a_skipped_section_is_still_declared_unread(self, ctx, monkeypatch):
        """Which is what stops the reconcile de-listing everything in it."""
        context = ctx(stored_categories={"Foreign Military Rifles"})
        self.sections_read(context, monkeypatch)
        assert "Foreign Military Rifles" in context.unread_categories

    def test_a_section_that_is_read_is_not_declared_unread(self, ctx, monkeypatch):
        context = ctx(stored_categories=())
        self.sections_read(context, monkeypatch)
        assert context.unread_categories == set()


class TestTheContextAnswersTheQuestion:
    def test_nothing_known_means_nothing_has_been_read(self, ctx_factory):
        """A scraper used standalone reads every section, which is the safe
        direction: reading twice costs time, never reading costs a gap."""
        context = ctx_factory()
        assert context.holds_category("Lugers") is False

    def test_a_stored_section_is_reported_as_read(self, ctx_factory):
        context = ctx_factory(stored_categories={"Lugers"})
        assert context.holds_category("Lugers") is True

    def test_a_listing_with_no_category_cannot_answer_it(self, ctx_factory):
        context = ctx_factory(stored_categories={"Lugers"})
        assert context.holds_category(None) is False
        assert context.holds_category("") is False
