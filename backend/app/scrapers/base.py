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
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import requests

from ..config import Config, ScrapingConfig
from ..robots import RobotsCache
from ..services import cooldown


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
    #: True when ``image_urls`` is this listing's *entire* gallery, so anything
    #: already stored and not listed here has genuinely been removed by the
    #: vendor. False when it is only what the catalog grid showed — a single
    #: low-resolution preview, which must never be allowed to displace a
    #: gallery a detail fetch has already collected.
    #:
    #: Defaults to True because most scrapers only ever emit complete records.
    #: A scraper that emits a listing twice — cheap preview first, full record
    #: after its detail page — sets it False on the first pass.
    images_are_complete: bool = True
    #: Images the scraper produced itself, as ``(stable_key, png_bytes)``.
    #:
    #: Most vendors publish photographs at a URL, which ``image_urls`` covers.
    #: Hunter's Lodge publishes one scanned flyer and nothing else, so each
    #: listing's picture is a crop cut out of that scan — bytes that exist only
    #: in memory. The key stands in for a URL when naming the stored file, so
    #: it has to be stable: the same crop of the same flyer must produce the
    #: same key on every scan, or each run would orphan the last one's files.
    generated_images: list[tuple[str, bytes]] = field(default_factory=list, repr=False)
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
        already_seen: Callable[[str], bool] | None = None,
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
        #: One robots.txt per site per scan, fetched through this context's own
        #: session so it is asked for under the same identity the rules are
        #: then applied to.
        self.robots = RobotsCache(self._fetch_robots)
        #: Per host, a pace slower than the one we started with, because the
        #: host asked for it with a 429. See _slow_down().
        self._slowed: dict[str, float] = {}
        #: Hosts that went on refusing after the pace hit its ceiling. Past
        #: that point a 429 is not "you are too fast", because there is no
        #: slower left to go — so retrying it only wastes the run's time.
        self._refusing: set[str] = set()
        # Answers "do we hold any listing whose key starts with this?", for a
        # scraper whose keys are not predictable one at a time. Defaults to
        # False, so a scraper used standalone does the full job.
        self._already_seen = already_seen or (lambda _prefix: False)
        self.warnings: list[str] = []
        #: Set by report_unchanged(); read by the scan service.
        self.unchanged = False
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

    def report_unchanged(self, reason: str) -> None:
        """Declare that the vendor has published nothing new since last time.

        A scraper normally has to return the *complete* current inventory,
        because anything it omits is treated as de-listed. That is the wrong
        contract for a vendor whose catalog is a single scanned flyer replaced
        every month or two: re-deriving forty listings from an unchanged image
        would be minutes of OCR to arrive back exactly where we started, and
        returning nothing instead would de-list the whole catalog.

        Calling this says "I have checked, and there is nothing new" — the run
        finishes successfully having changed nothing, and de-listing is skipped
        for that run.
        """
        self.unchanged = True
        self.log(reason)

    def needs_detail(self, external_key: str) -> bool:
        """True when this listing still needs its detail page fetched.

        Detail pages are one extra request each, so on a catalog of a thousand
        listings this is the difference between a scan that takes minutes and
        one that takes hours.
        """
        return self._needs_detail(external_key)

    def already_seen(self, key_prefix: str) -> bool:
        """True when some listing already stored has a key starting with this.

        For a source whose listings cannot be enumerated without doing the
        expensive work first. Hunter's Lodge derives its whole catalog from one
        scanned page, so the question worth asking before reading it is not
        "have we got listing 37" but "have we read this flyer at all" — and
        since a listing's key is derived from its own text, there is no
        particular key to ask about.
        """
        return self._already_seen(key_prefix)

    @property
    def stopped(self) -> bool:
        return self._should_stop()

    def check_stop(self) -> None:
        if self.stopped:
            raise ScrapeCanceled("Scan canceled")

    # -- HTTP ---------------------------------------------------------------
    def _throttle(self, url: str) -> None:
        """Wait out the politeness delay, or the site's own, whichever is longer.

        A Crawl-delay in robots.txt is the site telling us what it can take.
        Collectors Firearms asks for ten seconds, which turns a pass over their
        catalog from minutes into half an hour — and that is the site's call to
        make, not ours.
        """
        delay = self._delay_for(url)
        if delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def _delay_for(self, url: str) -> float:
        """The pace to keep with this host: ours, theirs, or the one a 429 set."""
        return max(
            self.scraping.request_delay,
            self._crawl_delay_for(url),
            self._slowed.get(_host_of(url), 0.0),
        )

    def _crawl_delay_for(self, url: str) -> float:
        if not self.scraping.obey_robots:
            return 0.0
        return self.robots.for_url(url).crawl_delay(self.scraping.user_agent) or 0.0

    def keep_at_least(self, url: str, seconds: float) -> None:
        """Hold this host to a pace no faster than ``seconds`` for this scan.

        For a site measured to refuse traffic that its own robots.txt says is
        acceptable. Never lowers a pace already set, so it cannot undo a 429.
        """
        host = _host_of(url)
        self._slowed[host] = min(max(self._slowed.get(host, 0.0), seconds), MAX_REQUEST_DELAY)

    def allowed(self, url: str) -> bool:
        """Whether robots.txt permits fetching this URL.

        Public because a scraper often knows a cheaper thing to do than fetch
        and fail — falling back from a query-string API to path pagination,
        say.
        """
        if not self.scraping.obey_robots:
            return True
        return self.robots.for_url(url).allows(url, self.scraping.user_agent)

    def _fetch_robots(self, url: str) -> requests.Response:
        """Fetch a robots.txt, without consulting robots.txt about it."""
        return self.session.get(url, timeout=self.scraping.request_timeout)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """GET with politeness delay and retries on transient failures."""
        if not self.allowed(url):
            raise Disallowed(url, reachable=self.robots.for_url(url).reachable)

        # Somebody — possibly another process — was told to go away by this
        # host recently. Waiting it out inside a scan would stall the run for
        # up to an hour, so this fails and lets the caller decide: a catalog
        # page ends the section, a product page costs that listing its gallery.
        resting = cooldown.paused_for(url)
        if resting > 0:
            raise HostResting(url, resting)
        timeout = kwargs.pop("timeout", self.scraping.request_timeout)
        last_error: Exception | None = None
        for attempt in range(self.scraping.max_retries):
            self.check_stop()
            self._throttle(url)
            try:
                response = self.session.get(url, timeout=timeout, **kwargs)
                self._last_request_at = time.monotonic()
                if response.status_code == TOO_MANY_REQUESTS:
                    self._slow_down(url, response)
                    if _host_of(url) in self._refusing:
                        # Only *now* is it worth telling the other processes.
                        #
                        # A single 429 means "slow down", and this context
                        # already knows how to do that on its own. Publishing a
                        # cooldown on the first one would have a scan abandon a
                        # whole vendor over a hiccup. Being refused at the
                        # slowest pace available is a different statement, and
                        # it is the one worth sharing — it is what a scheduler
                        # starting in a minute, or a `make photos` run, needs
                        # to know before it walks into the same wall.
                        cooldown.refused(
                            url,
                            f"{TOO_MANY_REQUESTS} at the slowest pace available",
                            _retry_after(response),
                        )
                        # Already as slow as this context goes, and still
                        # refused. Fail now rather than sleeping through three
                        # more attempts at a pace that has been shown not to
                        # help.
                        raise ScrapeError(
                            f"GET {url}: {TOO_MANY_REQUESTS} at the slowest pace available "
                            f"({self._delay_for(url):.0f}s between requests). The site is "
                            f"refusing this request rather than asking us to slow down."
                        )
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                self._last_request_at = time.monotonic()
                if attempt < self.scraping.max_retries - 1:
                    time.sleep(self._backoff(url, exc, attempt))
            else:
                # It answered, so whatever it was refusing before, it is not
                # refusing now. Without this the flag outlives the condition
                # and a much later 429 — a real rate limit, arriving after an
                # hour of successful requests — would fail on the first ask
                # instead of being given the chance to slow down.
                self._refusing.discard(_host_of(url))
                cooldown.succeeded(url)
                return response
        raise ScrapeError(
            f"GET {url} failed after {self.scraping.max_retries} attempts: {last_error}"
        )

    def _backoff(self, url: str, error: Exception, attempt: int) -> float:
        """How long to wait before trying again.

        A rate limit and a flaky server want opposite things. A 500 usually
        clears on the next request, so a second or two is right. A 429 is the
        site saying we are asking too often, and retrying it in a second or two
        is asking too often again — so it waits at least the new, slower pace
        this context has just adopted, and honors Retry-After when the site
        gives one.
        """
        response = getattr(error, "response", None)
        if response is not None and response.status_code == TOO_MANY_REQUESTS:
            stated = _retry_after(response)
            return max(stated or 0.0, self._delay_for(url)) * (attempt + 1)
        return self.scraping.request_delay * (attempt + 1) + 1.0

    def _slow_down(self, url: str, response: requests.Response) -> None:
        """Take a 429 as a standing instruction, not a one-off.

        Collectors Firearms publishes ``Crawl-delay: 10`` and still returned
        429 after sixteen minutes at exactly that pace — their limiter counts
        over a window that ten seconds a request eventually fills. Retrying the
        one request and carrying on at the same rate walks straight back into
        it, so the pace for the rest of the scan slows instead, doubling with
        each further refusal.

        It is never reset. A scan that has been told to slow down twice has no
        business speeding up again before it ends.
        """
        host = _host_of(url)
        current = self._slowed.get(host) or max(
            self.scraping.request_delay, self._crawl_delay_for(url)
        )
        stated = _retry_after(response)
        if current >= MAX_REQUEST_DELAY:
            # It was already at the ceiling before this refusal, so slowing
            # down is no longer an available response.
            self._refusing.add(host)
        slower = min(max(current * 2, stated or 0.0, MIN_BACKOFF_AFTER_429), MAX_REQUEST_DELAY)
        self._slowed[host] = slower
        self.warn(
            f"{host} returned 429; slowing to one request every {slower:.0f}s"
            + (f" (it asked for {stated:.0f}s)" if stated else "")
        )

    def get_text(self, url: str, **kwargs: Any) -> str:
        response = self.get(url, **kwargs)
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        return response.text

    def close(self) -> None:
        self.session.close()


#: The status that means "you are asking too often".
TOO_MANY_REQUESTS = 429

#: Where a 429 puts the pace when the site does not say. Ten seconds was not
#: enough for the shop this was written for, and it is the slowest Crawl-delay
#: any of them publish.
MIN_BACKOFF_AFTER_429 = 30.0

#: However insistent a site is, a scan that would take days is not a scan. Past
#: this the run should fail and say so rather than crawl on invisibly.
MAX_REQUEST_DELAY = 300.0


def _host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def _retry_after(response: requests.Response) -> float | None:
    """The Retry-After header in seconds, if the site sent a usable one."""
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)


class HostResting(ScrapeError):
    """This host asked to be left alone and the time is not up yet.

    A subclass of ScrapeError so every existing handler already does something
    sensible with it — the storefront walks fall back to the catalog, and a
    scan reports PARTIAL rather than pretending it read everything.
    """

    def __init__(self, url: str, seconds: float) -> None:
        self.seconds = seconds
        super().__init__(
            f"{_host_of(url)} asked to be left alone; {seconds:.0f}s still to wait "
            f"before anything asks it for {url}"
        )


class Disallowed(ScrapeError):
    """robots.txt forbids this URL, or could not be read to find out.

    A subclass of ScrapeError so an unguarded fetch fails the scan loudly
    rather than being mistaken for an empty catalog, and a type of its own so a
    scraper with an alternative route can catch just this.

    The two cases behave identically -- both refuse the request, because a rule
    we could not read is not a rule we may ignore -- and read very differently
    in a warning. Saying "robots.txt disallows" when the file was never fetched
    sends whoever reads the scan log looking for a rule that does not exist,
    which is exactly what one dropped connection did to a SARCO run.
    """

    def __init__(self, url: str, *, reachable: bool = True) -> None:
        super().__init__(
            f"robots.txt disallows {url}"
            if reachable
            else f"could not read robots.txt for {url}, so it was not fetched"
        )
        self.url = url
        #: Whether the rules were actually read. False means we never found out.
        self.reachable = reachable


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
    #: Whether this vendor's descriptions are prose about the listing they
    #: belong to. Nearly always true, and false for a source where the text
    #: bleeds: Hunter's Lodge derives its whole catalog from one scanned page,
    #: so a listing's "description" carries whatever was printed beside it.
    #: That is fine to read and useless to derive facts from — it filed hand-
    #: woven blankets under 8mm Mauser and put a Japanese Arisaka in Sweden.
    #:
    #: Only the *derived* fields honor this. The description is still stored,
    #: still shown and still read by the rifle/handgun rules; it is only barred
    #: from being treated as evidence about this listing's caliber, country,
    #: maker and condition.
    descriptions_are_reliable: bool = True
    #: Default cadence for a freshly seeded site row, in minutes.
    default_interval_minutes: int = 1440

    @abc.abstractmethod
    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        """Yield or return every listing currently on the vendor's site.

        Anything omitted from the result is treated as de-listed, so a scraper
        must return the *complete* current inventory, not a delta. Raise
        :class:`ScrapeError` to fail the run; call ``ctx.warn()`` for problems
        that should downgrade it to PARTIAL instead.

        **Prefer a generator for anything slow.** The scan service consumes
        this lazily and commits in batches, so a scraper that yields keeps
        whatever it has already produced when a scan is interrupted, while one
        that builds a list and returns it at the end loses the lot. On a
        sixteen-minute catalog that is the whole difference between resuming
        and starting over.

        A key may be yielded **more than once**; the last version wins, exactly
        as a re-scrape would. That is what lets a scraper emit a cheap listing
        from the catalog grid straight away and then emit it again once an
        expensive detail fetch has filled in the description and gallery.

        De-listing only happens when this iterable is exhausted normally, so an
        interrupted scrape can never mark the listings it never reached as
        gone.
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
