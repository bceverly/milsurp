"""The contract every site scraper implements.

Adding a vendor means writing one subclass of :class:`SiteScraper` in this
package and registering it. Everything else -- scheduling, the admin controls,
upserts, price history, images, digests -- is site-agnostic and needs no change.

The two reference implementations bracket the difficulty range:

* ``empire_arms`` is static hand-authored HTML fetched with ``requests``.
* ``royal_tiger`` is a WooCommerce/Elementor site with infinite scroll and
  "Load More" buttons that needs a real browser.
"""

from __future__ import annotations

import abc
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

from ..config import Config, ScrapingConfig


@dataclass
class ScrapedItem:
    """One listing as it appears on a vendor site, before it touches the DB."""

    # Stable within a site across scans. Prefer something the vendor controls
    # (product URL slug, image id) over anything derived from the title.
    external_key: str
    url: str
    title: str
    price: float | None = None
    currency: str = "USD"
    description: str | None = None
    category: str | None = None
    caliber: str | None = None
    country: str | None = None
    manufacturer: str | None = None
    condition: str | None = None
    is_sold: bool = False
    posted_at: datetime | None = None
    image_urls: list[str] = field(default_factory=list)
    # Anything site-specific worth keeping; merged into the description view.
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.external_key = (self.external_key or "").strip()[:255]
        self.title = normalize_whitespace(self.title or "")[:512]
        if self.description:
            self.description = normalize_whitespace(self.description)
        # De-duplicate image URLs while preserving discovery order.
        seen: set[str] = set()
        ordered: list[str] = []
        for url in self.image_urls:
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)
        self.image_urls = ordered


class ScrapeError(RuntimeError):
    """A scrape failed outright (as opposed to partially)."""


class ScrapeContext:
    """Services a scraper is handed for one run.

    Carries the HTTP session, the politeness delay, the progress callback and a
    cancellation flag, so an individual scraper never reaches for global state.
    """

    def __init__(
        self,
        config: Config,
        progress: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        needs_detail: Callable[[str], bool] | None = None,
    ) -> None:
        self.config = config
        self.scraping: ScrapingConfig = config.scraping
        self._progress = progress or (lambda _message: None)
        self._should_stop = should_stop or (lambda: False)
        # Supplied by the scan service; answers "have we already got the full
        # record for this key?" so a scraper can skip detail pages it has
        # already fetched. Defaults to True so a scraper used standalone (in a
        # test, say) still does the full job.
        self._needs_detail = needs_detail or (lambda _key: True)
        self.warnings: list[str] = []
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.scraping.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    # -- progress / control -------------------------------------------------
    def log(self, message: str) -> None:
        """Record a line of progress; surfaced in the scan detail view."""
        self._progress(message)

    def warn(self, message: str) -> None:
        """Record a non-fatal problem; marks the run PARTIAL rather than FAILED."""
        self.warnings.append(message)
        self._progress(f"WARNING: {message}")

    def needs_detail(self, external_key: str) -> bool:
        """True when this listing still needs its detail page fetched.

        Detail pages are one extra request each, so on a catalog of a thousand
        listings this is the difference between a scan that takes minutes and
        one that takes hours.
        """
        return self._needs_detail(external_key)

    @property
    def stopped(self) -> bool:
        return self._should_stop()

    def check_stop(self) -> None:
        if self.stopped:
            raise ScrapeCanceled("Scan canceled")

    # -- HTTP ---------------------------------------------------------------
    def _throttle(self) -> None:
        delay = self.scraping.request_delay
        if delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """GET with politeness delay and retries on transient failures."""
        timeout = kwargs.pop("timeout", self.scraping.request_timeout)
        last_error: Exception | None = None
        for attempt in range(self.scraping.max_retries):
            self.check_stop()
            self._throttle()
            try:
                response = self.session.get(url, timeout=timeout, **kwargs)
                self._last_request_at = time.monotonic()
                if response.status_code in (429, 500, 502, 503, 504):
                    response.raise_for_status()
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                self._last_request_at = time.monotonic()
                if attempt < self.scraping.max_retries - 1:
                    # Linear backoff; these sites are small and flaky rather
                    # than rate-limiting us aggressively.
                    time.sleep(self.scraping.request_delay * (attempt + 1) + 1.0)
            else:
                return response
        raise ScrapeError(
            f"GET {url} failed after {self.scraping.max_retries} attempts: {last_error}"
        )

    def get_text(self, url: str, **kwargs: Any) -> str:
        response = self.get(url, **kwargs)
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        return response.text

    def close(self) -> None:
        self.session.close()


class ScrapeCanceled(ScrapeError):
    """Raised when an operator stops a run mid-flight."""


class SiteScraper(abc.ABC):
    """Base class for a vendor scraper."""

    #: Stable identifier; binds the ``sites`` row to this class. Never rename.
    slug: str = ""
    #: Display name shown in the UI.
    name: str = ""
    #: Vendor home page.
    base_url: str = ""
    #: One-line description for the admin site list.
    description: str = ""
    #: True when a headless browser is required (Selenium + Chrome).
    requires_browser: bool = False
    #: Default cadence for a freshly seeded site row, in minutes.
    default_interval_minutes: int = 1440

    @abc.abstractmethod
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        """Yield or return every listing currently on the vendor's site.

        Anything omitted from the result is treated as de-listed, so a scraper
        must return the *complete* current inventory, not a delta. Raise
        :class:`ScrapeError` to fail the run; call ``ctx.warn()`` for problems
        that should downgrade it to PARTIAL instead.
        """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} slug={self.slug!r}>"


# ---------------------------------------------------------------------------
# Parsing helpers shared by scrapers
# ---------------------------------------------------------------------------
_WS_RE = re.compile(r"\s+")
_PRICE_RE = re.compile(r"[\d][\d,]*(?:\.\d{1,2})?")


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_price(text: str | None) -> float | None:
    """Pull a dollar amount out of noisy markup text.

    Returns ``None`` for "Call for price", empty strings and anything that does
    not contain a number.
    """
    if not text:
        return None
    match = _PRICE_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None
