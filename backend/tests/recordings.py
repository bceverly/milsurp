"""Recorded vendor responses, and the context that replays them.

**Why these exist.** Every scraper here parses somebody else's markup, and the
only thing that ever proves a parser still works is running it against that
markup. Until now that meant either trimming a page into a string literal by
hand -- accurate, laborious, and only ever a fragment -- or asking the vendor,
which a test suite must not do: it is slow, it fails on their bad days rather
than ours, and it puts twenty-eight shops' servers in the path of `make test`.

A recording is one scan's worth of responses, saved as they arrived. Replaying
it exercises the real parser against the real page with no network at all.

**What a recording is not.** It is not a statement about what the shop sells
today, and a test written against one must not assert on prices or titles that
will drift. What it pins is *shape*: that the catalog still parses, that items
come back with the fields the rest of the application requires, and that a
change to a parser does not quietly stop finding half a shop's listings. A
recording going stale is expected -- re-record it; a recording that no longer
parses is the alarm this is for.

Recordings are gzipped because vendor pages are large: one of these shops keeps
its whole rifle catalog on a single 778 KB page, and eBayonet's country pages
run to 226 KB of Word-exported HTML.

Record with ``scripts/record-fixtures.py``; see its docstring.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.scrapers.base import ScrapeCanceled

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The file a recording's index lives in, inside its own directory.
MANIFEST = "manifest.json"


class NotRecorded(LookupError):
    """A scraper asked for a URL this recording does not hold.

    Its own error rather than a KeyError because the fix is specific and worth
    stating where it is read: the scraper now fetches something it did not when
    the recording was made, so the recording needs re-taking.
    """


@dataclass(frozen=True)
class Recording:
    """One scraper's saved responses."""

    slug: str
    recorded_at: str
    directory: Path
    #: url -> file name, in the order they were requested.
    pages: dict[str, str]

    def text(self, url: str) -> str:
        name = self.pages.get(url) or self.pages.get(url.rstrip("/"))
        if name is None:
            raise NotRecorded(
                f"{self.slug}: nothing recorded for {url}.\n"
                f"  The recording was taken {self.recorded_at} and holds "
                f"{len(self.pages)} page(s).\n"
                f"  If the scraper now asks for pages it did not then, re-record:\n"
                f"    scripts/record-fixtures.py {self.slug}"
            )
        return gzip.decompress((self.directory / name).read_bytes()).decode("utf-8")

    def __len__(self) -> int:
        return len(self.pages)


def available() -> list[str]:
    """Every slug whose *scan* can be replayed from a recording, sorted.

    Two exclusions, and both are the same mistake waiting to happen: replaying
    a scan runs the real scraper, and a scraper that drives a browser will go
    to the shop for its catalog no matter what is on disk beside it.

    * A manifest marked ``"kind": "rendered"`` holds a page the browser built.
      There is no server response that contains that catalog, so there is
      nothing for ``scrape()`` to read -- ``scrape()`` is what drives the
      browser. Royal Tiger's fixture is one of these, parsed directly by
      ``test_royal_tiger.py`` instead.
    * ``requires_browser`` is checked as well, against the scraper rather than
      the fixture, because the first version of this trusted the manifest alone
      and a mislabelled one sent the suite to fetch from the shop. A test that
      reaches the network is a test that fails on somebody else's bad day, and
      this particular shop is fragile enough that it should not be asked twice.
    """
    if not FIXTURES.is_dir():
        return []
    found = []
    for directory in sorted(FIXTURES.iterdir()):
        manifest = directory / MANIFEST
        if not directory.is_dir() or not manifest.is_file():
            continue
        if json.loads(manifest.read_text()).get("kind", "http") != "http":
            continue
        if _needs_a_browser(directory.name):
            continue
        found.append(directory.name)
    return found


def _needs_a_browser(slug: str) -> bool:
    """Whether replaying this scraper would open Chrome and reach the network."""
    from app.scrapers import get_scraper

    try:
        return bool(getattr(get_scraper(slug), "requires_browser", False))
    except Exception:  # pragma: no cover - an unregistered fixture directory
        return False


def load(slug: str) -> Recording:
    """Read one recording's index."""
    directory = FIXTURES / slug
    data: dict[str, Any] = json.loads((directory / MANIFEST).read_text())
    return Recording(
        slug=slug,
        recorded_at=str(data.get("recorded_at", "at an unknown time")),
        directory=directory,
        pages={entry["url"]: entry["file"] for entry in data.get("pages", [])},
    )


def replaying(context: Any, recording: Recording) -> Any:
    """Point a ScrapeContext at a recording instead of the network.

    Only ``get_text`` is replaced, because that is the single door every
    scraper goes through -- which is also why recording at that seam captures
    a whole scan without any scraper knowing about it.

    **Running off the end of a recording stops the scan rather than failing
    it.** Recordings are capped: these shops publish catalogs of thousands, and
    a fixture only has to be big enough to exercise the parser. So a replay
    reaches the last recorded page and the scraper asks for the next one, which
    is not an error -- it is the recording ending. It is reported the way the
    application already reports "stop here", and every scraper honors that.

    The cost is worth naming: a scraper that starts fetching pages it never
    used to will look like a short recording rather than announcing itself.
    What that cannot hide is the thing these tests are for -- a parser that has
    stopped finding listings in pages it *did* record still comes back empty,
    and the assertions read the items, not the page count.
    """

    def get_text(url: str, **_kwargs: Any) -> str:
        try:
            return recording.text(url)
        except NotRecorded as exc:
            raise ScrapeCanceled(str(exc)) from exc

    context.get_text = get_text  # type: ignore[method-assign]
    return context
