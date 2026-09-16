#!/usr/bin/env python
"""Record one scan's HTTP responses so a parser can be tested without a vendor.

    scripts/record-fixtures.py atlantic-firearms
    scripts/record-fixtures.py --all
    scripts/record-fixtures.py --list

Runs a scraper for real -- robots.txt, the host cooldown register and the
politeness delay all apply, because this is the same ScrapeContext a scan uses
-- and saves every response it reads into ``backend/tests/fixtures/<slug>/``.
``backend/tests/test_recorded_scrapers.py`` then replays them.

**This is the one thing in the repository that deliberately touches vendor
sites, so it is a script an operator runs and never part of `make test`.** It
is polite by construction and still worth not running casually: twenty-eight
shops is twenty-eight catalogs.

Recording is capped (see ``--pages``) because a fixture only has to be big
enough to exercise the parser. A full 4,000-listing catalog would make a
repository nobody wants to clone and would prove nothing the first few pages do
not.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_config  # noqa: E402
from app.scrapers import SCRAPER_CLASSES, get_scraper  # noqa: E402
from app.scrapers.base import ScrapeCanceled, ScrapeContext  # noqa: E402

FIXTURES = ROOT / "backend" / "tests" / "fixtures"

#: Responses to keep per site.
#:
#: Enough to cross a page boundary and reach a detail fetch, which is where
#: parsers break, and no more: these pages are big. Atlantic Firearms serves
#: 1.3 MB per page, so six of them was a megabyte of repository for a test
#: that two pages answer just as well. Raise it for a site whose shape needs
#: it rather than as a default.
DEFAULT_PAGES = 4


def _bold(text: str) -> None:
    print(f"\033[1m{text}\033[0m")


def record(slug: str, *, limit: int) -> int:
    """Run one scraper, saving what it reads. Returns the number of pages."""
    config = get_config()
    scraper = get_scraper(slug)
    if getattr(scraper, "requires_browser", False):
        print(f"  {slug}: needs a headless browser; its fixture is a rendered page, not a scan.")
        return 0

    saved: list[dict[str, object]] = []
    seen: set[str] = set()

    # Stop through the application's own cancellation, not an exception.
    # Scrapers deliberately swallow a per-page failure -- one page of five is
    # one country range, not the catalog -- so an exception raised in here is
    # caught by the scraper and the scan carries on. `check_stop` is the path
    # built for "stop now", and every scraper already honors it.
    context = ScrapeContext(
        config=config,
        progress=lambda _message: None,
        should_stop=lambda: len(saved) >= limit,
    )
    real_get_text = context.get_text

    def taping(url: str, **kwargs: object) -> str:
        text = real_get_text(url, **kwargs)
        if url not in seen:
            seen.add(url)
            saved.append({"url": url, "text": text})
            print(f"    [{len(saved):>2}] {len(text):>8,} bytes  {url}")
        return text

    context.get_text = taping  # type: ignore[method-assign]

    try:
        for _item in scraper.scrape(context):
            pass
    except ScrapeCanceled:
        # The cap doing its job, not a failure. Reported as such, because a
        # recorder that prints an exception for its own success teaches
        # whoever runs it to ignore what it prints.
        pass
    except Exception as exc:
        # A vendor's bad day stops the recording rather than the script, and
        # whatever was read up to that point is still worth keeping.
        print(f"  {slug}: stopped early: {type(exc).__name__}: {exc}")

    if not saved:
        print(f"  {slug}: nothing recorded.")
        return 0

    directory = FIXTURES / slug
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.html.gz"):
        old.unlink()

    pages = []
    for index, entry in enumerate(saved, start=1):
        name = f"{index:04d}.html.gz"
        (directory / name).write_bytes(gzip.compress(str(entry["text"]).encode("utf-8"), 9))
        pages.append({"url": entry["url"], "file": name})

    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "pages": pages,
            },
            indent=2,
        )
        + "\n"
    )
    total = sum((directory / p["file"]).stat().st_size for p in pages)
    print(f"  {slug}: {len(pages)} page(s), {total / 1024:.0f} KB compressed.")
    return len(pages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", help="which sites to record")
    parser.add_argument("--all", action="store_true", help="every registered scraper")
    parser.add_argument("--list", action="store_true", help="show the slugs and stop")
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_PAGES,
        help=f"responses per site (default {DEFAULT_PAGES})",
    )
    args = parser.parse_args()

    known = sorted(cls.slug for cls in SCRAPER_CLASSES)
    if args.list:
        for slug in known:
            print(slug)
        return 0

    slugs = known if args.all else args.slugs
    if not slugs:
        parser.error("name at least one slug, or pass --all (see --list)")

    unknown = [slug for slug in slugs if slug not in set(known)]
    if unknown:
        parser.error(f"unknown slug(s): {', '.join(unknown)}")

    _bold(f"\nRecording {len(slugs)} site(s) into {FIXTURES.relative_to(ROOT)}\n")
    recorded = 0
    for slug in slugs:
        print(f"  {slug}…")
        recorded += 1 if record(slug, limit=args.pages) else 0
    _bold(f"\n{recorded} of {len(slugs)} site(s) recorded.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
