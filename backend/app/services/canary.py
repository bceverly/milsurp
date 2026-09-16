"""A standing check that every shop still answers us, and still parses.

Two different failures look identical from the outside, and neither one raises
anything: a vendor that starts refusing our requests, and a vendor whose markup
moved under a working request. Both end in a scan that stores no listings, and
a scan that stores no listings is indistinguishable from a shop that has sold
out of everything. Nothing in the system would ever say so.

That is not hypothetical. Six of the twenty-eight vendors -- ancestryguns,
apexgunparts, centerfiresystems, collectorsfirearms, ima-usa and jgsales --
answer 403 to a request they dislike, and a datacenter IP was enough to earn it
from all of them at once. A fifth of the catalog can go quiet in an afternoon.

**The probe is the real scrape, stopped early.** Not a HEAD of the home page,
which proves only that a web server is running, and not a recorded fixture,
which proves only that yesterday's HTML still parses. A scraper is a generator
(see :meth:`SiteScraper.scrape`), so consuming three listings and walking away
exercises the whole path -- robots.txt, the session's identity, the politeness
delay, the catalog fetch, the parser -- and then closes the generator. Whatever
a real scan would hit, this hits first, in about a page's worth of work.

What it deliberately does *not* do is write anything. No listings are stored,
no ``scans`` row is opened, nothing is de-listed. A canary that mutated the
catalog would be a scan, and a half-finished scan that marked every listing it
never reached as gone is precisely the accident :meth:`scrape` warns about.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from http import HTTPStatus

import requests

from ..config import Config
from ..scrapers import get_scraper
from ..scrapers.base import (
    Disallowed,
    HostResting,
    ScrapeCanceled,
    ScrapeContext,
    ScrapeError,
    SiteScraper,
    vendors_answer,
)
from . import backup, cooldown

#: Listings to see before calling a shop healthy. One would do -- the question
#: is "did anything parse at all" -- but a catalog whose first card is a banner
#: or a sold-out placeholder would answer it by accident, and three costs
#: nothing extra because they are all on the page already fetched.
DEFAULT_WANT = 3

#: Seconds a single shop may take before the probe gives up on it. Generous on
#: purpose: this is a ceiling that catches a hang, not a performance budget.
#: Sixteen-minute catalogs exist, and the point is to stop long before one.
DEFAULT_BUDGET = 90.0

#: How many paced requests a probe is assumed to need: robots.txt, the catalog,
#: and a little room. Multiplied by the gap the cooldown register is asking for
#: and added to the budget -- see sweep().
PACED_REQUESTS = 4

#: What a scraper needing a headless browser gets instead. Applied per scraper
#: rather than raising the default, which would let a genuinely hung HTTP shop
#: sit there eight times as long.
#:
#: Twelve minutes looks absurd next to the one-to-five seconds every other shop
#: takes, and it is the honest number. The early stop only helps a scraper that
#: yields as it reads; Royal Tiger drives all of its sections through Chrome
#: and collects them into a dict *before* the first yield, so a probe cannot
#: reach listing one until the whole grid pass is done. Real scans there run
#: 512-572s. A budget under that reports a timeout every night for a site whose
#: scans succeed -- which is the canary crying wolf about its own stopwatch,
#: and the fastest way to teach somebody to ignore it.
BROWSER_BUDGET = 720.0


class Verdict(str, enum.Enum):
    """What the probe found. Only ``OK`` is a pass.

    ``REFUSED`` and ``EMPTY`` are separated because they need different
    repairs and the distinction is invisible in the outcome. Refused is a
    conversation with the vendor -- an address, an identity, a rate. Empty is
    our parser being wrong about their page. Reporting both as "failed" would
    send whoever reads it to the wrong file.

    ``RESTING`` is the one that is our own doing: the host refused us at some
    point, the cooldown register put it in the penalty box, and nothing has
    asked it since. The first sweep this was run found checkpoint-charlies had
    been failing that way for three consecutive days, each scan dying on the
    cooldown rather than on anything the vendor did that morning. Calling that
    BROKE would send someone to read the scraper, which is fine.
    """

    OK = "ok"
    REFUSED = "refused"
    RESTING = "resting"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    BROKE = "broke"

    @property
    def healthy(self) -> bool:
        return self is Verdict.OK


@dataclass(frozen=True)
class Probe:
    """One shop's answer."""

    slug: str
    name: str
    verdict: Verdict
    items: int
    seconds: float
    #: The HTTP status behind a REFUSED, where there was one.
    status: int | None = None
    #: One line a human can act on. Empty when there is nothing to say.
    detail: str = ""

    @property
    def healthy(self) -> bool:
        return self.verdict.healthy


def probe(  # noqa: PLR0911 - one return per verdict, which is the whole shape
    config: Config,
    scraper: SiteScraper,
    *,
    want: int = DEFAULT_WANT,
    budget: float = DEFAULT_BUDGET,
) -> Probe:
    """Fetch the first few listings from one shop and report what happened.

    Never raises. A canary that can itself fail on shop three and take the
    remaining twenty-five with it is worse than no canary, because the sweep
    would report a partial picture as if it were the whole one.
    """
    started = time.monotonic()
    deadline = started + budget
    # needs_detail=False keeps the probe on the catalog page. A scraper is free
    # to skip its per-listing detail fetches when nobody needs them, which is
    # what turns "read the whole shop" into "read one page". The catalog parse
    # is the part that breaks when markup moves, and it is the part this reads.
    ctx = ScrapeContext(
        config,
        should_stop=lambda: time.monotonic() > deadline,
        needs_detail=lambda _key: False,
    )

    seen = 0
    try:
        for _item in scraper.scrape(ctx):
            seen += 1
            if seen >= want or time.monotonic() > deadline:
                break
    except ScrapeCanceled:
        # Our own doing: should_stop() is how the budget is enforced, and a
        # scraper that honors it raises this. Reporting it as BROKE would blame
        # the vendor for our stopwatch -- which is exactly what royal-tiger,
        # the one Selenium site, did on its first nightly.
        return _probe(
            scraper,
            Verdict.TIMEOUT,
            seen,
            started,
            detail=_gave_up(scraper, budget),
        )
    except HostResting as exc:
        # Our own register, not the vendor's answer: the cooldown is why we did
        # not ask. Caught before ScrapeError because it is a subclass of one.
        return _probe(scraper, Verdict.RESTING, seen, started, detail=str(exc))
    except Disallowed as exc:
        # robots.txt is a refusal like any other from the canary's point of
        # view: the listings do not arrive. Whether the file said no or could
        # not be read changes the repair, so exc's own wording is kept.
        return _probe(scraper, Verdict.REFUSED, seen, started, detail=str(exc))
    except ScrapeError as exc:
        status = getattr(exc, "status", None)
        # VENDOR_ANSWERS -- 401/403/404/410 -- is the shop stating a policy
        # rather than something breaking. That is exactly the six-vendor case.
        verdict = Verdict.REFUSED if vendors_answer(exc) else Verdict.BROKE
        return _probe(scraper, verdict, seen, started, status=status, detail=str(exc))
    except Exception as exc:  # deliberate: see the docstring -- this never raises
        return _probe(scraper, Verdict.BROKE, seen, started, detail=f"{type(exc).__name__}: {exc}")

    if seen:
        return _probe(scraper, Verdict.OK, seen, started)
    if time.monotonic() > deadline:
        return _probe(
            scraper,
            Verdict.TIMEOUT,
            seen,
            started,
            detail=_gave_up(scraper, budget),
        )
    # The quiet one. The shop answered, the scrape ran to the end, and not one
    # listing came out of it. Either they really are empty or we no longer know
    # how to read them, and only a human can tell which.
    return _probe(
        scraper, Verdict.EMPTY, seen, started, detail="the scrape finished and parsed nothing"
    )


def _gave_up(scraper: SiteScraper, budget: float) -> str:
    """Why a probe ran out of time, naming our own politeness where it applies.

    A reader looking at "gave up after 90s" will go and check the vendor. If
    the register is holding us to one request a minute, the vendor is not the
    thing to check.
    """
    gap = cooldown.pace_for(scraper.base_url)
    if gap:
        return (
            f"nothing parsed within {budget:.0f}s, of which most was our own "
            f"pacing: the cooldown register is asking for {gap:.0f}s between "
            f"requests to this host"
        )
    return f"nothing parsed within {budget:.0f}s"


def _probe(
    scraper: SiteScraper,
    verdict: Verdict,
    items: int,
    started: float,
    *,
    status: int | None = None,
    detail: str = "",
) -> Probe:
    return Probe(
        slug=scraper.slug,
        name=scraper.name or scraper.slug,
        verdict=verdict,
        items=items,
        seconds=time.monotonic() - started,
        status=status,
        detail=detail,
    )


def sweep(
    config: Config,
    slugs: Sequence[str],
    *,
    want: int = DEFAULT_WANT,
    budget: float = DEFAULT_BUDGET,
    skip_browser: bool = False,
    progress: Callable[[Probe], None] | None = None,
) -> list[Probe]:
    """Probe each slug in turn, in the order given.

    Sequential rather than parallel, and that is deliberate: the politeness
    delay and the robots cache are per-context, so twenty-eight threads would
    be twenty-eight simultaneous strangers arriving at shops that already
    dislike being crawled. The whole sweep is about a page per vendor.
    """
    results: list[Probe] = []
    for slug in slugs:
        scraper = get_scraper(slug)
        if scraper is None:
            results.append(
                Probe(
                    slug=slug,
                    name=slug,
                    verdict=Verdict.BROKE,
                    items=0,
                    seconds=0.0,
                    detail="no scraper is registered for this slug",
                )
            )
            continue
        if skip_browser and scraper.requires_browser:
            continue
        allowance = max(budget, BROWSER_BUDGET) if scraper.requires_browser else budget
        # A host the cooldown register is pacing has to be given time to be
        # asked slowly. Without this the budget is spent waiting out a delay
        # *we* imposed and the shop is reported as a timeout -- which is the
        # canary blaming a vendor for our own politeness, and it happened the
        # first night this ran in production: checkpointcharlies.com was on a
        # 60s gap after refusing a run of photo fetches, so two requests could
        # not fit in ninety seconds and never will.
        gap = cooldown.pace_for(scraper.base_url)
        result = probe(config, scraper, want=want, budget=allowance + gap * PACED_REQUESTS)
        results.append(result)
        if progress is not None:
            progress(result)
    return results


#: How old the off-machine backup record may get before it is worth saying.
#:
#: Two days. The job runs nightly, so this is two missed runs -- one is a
#: transient (the NAS rebooting, the network down for an hour) and two is a
#: pattern. Reporting on one would teach whoever reads this to ignore it, which
#: is the failure mode a nightly report can least afford.
STALE_BACKUP_HOURS = 48


@dataclass(frozen=True)
class BackupHealth:
    """Whether copies of the database are still leaving this machine."""

    #: None when no copy has ever been recorded, which is a different thing
    #: from an old one and is reported differently.
    age_hours: float | None
    configured: bool

    @property
    def stale(self) -> bool:
        return self.configured and (self.age_hours or 0) > STALE_BACKUP_HOURS

    @property
    def headline(self) -> str:
        if not self.configured:
            return "No off-machine copy has ever been recorded."
        if self.age_hours is None:  # pragma: no cover - configured implies a stamp
            return "No off-machine copy has ever been recorded."
        days = self.age_hours / 24
        return f"The last off-machine copy was {days:.1f} day(s) ago."


def backup_health(config: Config) -> BackupHealth:
    """Whether the off-machine copy is still happening.

    Beside the shop checks because it is the same kind of failure: something
    that should be happening quietly has stopped, and nothing announces it. A
    backup that stopped four nights ago and a vendor that stopped answering
    four nights ago are found the same way, and by the same nightly email.
    """
    age = backup.offsite_age_hours(config.backups.directory)
    return BackupHealth(age_hours=age, configured=age is not None)


# ---------------------------------------------------------------------------
# Is the site itself up?
# ---------------------------------------------------------------------------
#: Attempts per run, because one sample cannot see an intermittent fault.
#:
#: The outage this check exists for was bursty: a browse page opened two
#: hundred thumbnail requests, everything queued behind them, and a minute
#: later the site was answering in milliseconds again. A single probe would
#: have missed it more often than not. Three spread over a few seconds is
#: still cheap and catches a site that is up but struggling.
SITE_ATTEMPTS = 3

#: Seconds between them. Long enough not to be one burst of its own.
SITE_GAP = 2.0

#: How long a health check may take before it is worth saying something.
#:
#: The endpoint reads no database and normally answers in milliseconds -- 17ms
#: through the full public path from the host itself. Five seconds is therefore
#: not a threshold anything healthy approaches; it is the shape of a request
#: queueing behind something, which is what the last outage looked like from
#: the outside. Deliberately well under the proxy's own server timeout, so this
#: mail arrives before visitors start seeing gateway errors rather than after.
SITE_SLOW_SECONDS = 5.0

#: Give up on a single attempt here. Above the slow threshold so a slow answer
#: is still measured rather than turned into a timeout.
SITE_TIMEOUT = 20.0

#: How much of a connection error to quote.
#:
#: urllib3 wraps a refused connection in three nested exceptions and the repr
#: runs to three hundred characters of retry machinery. What a reader needs is
#: the first clause; the rest is an email nobody finishes.
SITE_DETAIL_CHARS = 110


@dataclass(frozen=True)
class SiteHealth:
    """Whether the application is serving the people it is for.

    Everything else in this module watches somebody else's website. This
    watches ours, from outside, over the same path a visitor takes -- proxy,
    nginx and app -- because that is the only way to find out what they get.

    It is here rather than in the app because an application cannot report its
    own absence. The canary is a separate process on a timer and mails through
    its own configuration, so it still has a voice when the service is down.
    """

    url: str
    #: Best status seen. None when nothing answered at all.
    status: int | None
    #: Slowest successful attempt, in seconds. None when none succeeded.
    slowest: float | None
    attempts: int
    failures: int
    detail: str = ""

    @property
    def down(self) -> bool:
        """Nothing answered correctly. The failure worth waking up for."""
        return self.status != HTTPStatus.OK

    @property
    def flapping(self) -> bool:
        """Some answered and some did not, which is its own kind of broken."""
        return not self.down and 0 < self.failures < self.attempts

    @property
    def slow(self) -> bool:
        return not self.down and (self.slowest or 0) > SITE_SLOW_SECONDS

    @property
    def unhappy(self) -> bool:
        return self.down or self.flapping or self.slow

    @property
    def headline(self) -> str:
        if self.down:
            what = f"HTTP {self.status}" if self.status else self.detail or "no answer"
            return f"The site is not answering at {self.url} ({what})."
        if self.flapping:
            return (
                f"The site answered {self.attempts - self.failures} of "
                f"{self.attempts} times at {self.url}."
            )
        if self.slow:
            return f"The site answered in {self.slowest:.1f}s at {self.url}."
        return f"The site is up ({self.slowest:.2f}s)."


def _short(text: str) -> str:
    """One line, short enough to read in a subject-adjacent position."""
    flat = " ".join(text.split())
    if len(flat) <= SITE_DETAIL_CHARS:
        return flat
    return flat[: SITE_DETAIL_CHARS - 1].rstrip() + "…"


def site_health(config: Config, *, sleep: Callable[[float], None] = time.sleep) -> SiteHealth:
    """Fetch our own health endpoint, the long way round.

    Through ``public_url`` rather than localhost on purpose. Localhost proves
    the Python process is alive, which is the half that was never in doubt:
    the last outage had the application answering in under a millisecond while
    visitors were being shown 504s by the proxy in front of it. A check that
    cannot see the difference would have reported everything fine.
    """
    url = (config.server.public_url or "").rstrip("/") + "/api/health"
    status: int | None = None
    slowest: float | None = None
    failed = 0
    detail = ""

    for attempt in range(SITE_ATTEMPTS):
        if attempt:
            sleep(SITE_GAP)
        started = time.monotonic()
        try:
            response = requests.get(url, timeout=SITE_TIMEOUT)
        except requests.RequestException as exc:
            failed += 1
            detail = detail or _short(f"{type(exc).__name__}: {exc}")
            continue
        elapsed = time.monotonic() - started
        if response.status_code == HTTPStatus.OK:
            status = HTTPStatus.OK
            slowest = elapsed if slowest is None else max(slowest, elapsed)
        else:
            failed += 1
            # Keep the first bad status only if nothing has answered properly;
            # a 200 anywhere in the run is the more useful headline.
            if status is None:
                status = response.status_code
            detail = detail or f"HTTP {response.status_code}"

    return SiteHealth(
        url=url,
        status=status,
        slowest=slowest,
        attempts=SITE_ATTEMPTS,
        failures=failed,
        detail=detail,
    )


def failures(results: Iterable[Probe]) -> list[Probe]:
    """The unhealthy probes, worst first.

    Ordered so the top of a report is the thing to read. REFUSED outranks
    EMPTY because a refusal is usually one cause behind many rows -- an
    address, an identity -- while an empty parse is one shop's own markup.
    """
    rank = {
        Verdict.REFUSED: 0,
        Verdict.BROKE: 1,
        Verdict.RESTING: 2,
        Verdict.TIMEOUT: 3,
        Verdict.EMPTY: 4,
    }
    return sorted(
        (r for r in results if not r.healthy),
        key=lambda r: (rank.get(r.verdict, 9), r.name.lower()),
    )
