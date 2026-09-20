"""Headless-Chrome helper for sites that only render their catalog in JS.

Kept in its own module so Selenium is imported lazily: the application, its
tests and the ``requests``-based scrapers all run fine on a machine with no
Chrome installed. Only a scraper whose ``requires_browser`` is true pays for it.

The two hard-won behaviors from the standalone Royal Tiger scanner live here:

* **Infinite scroll** that only fires when the scroll position actually moves,
  which means nudging back up before hitting the bottom again.
* **"Load More"** buttons that are absent from the DOM until scrolled near, are
  sometimes ``<a>`` and sometimes ``<button>``, and intercept normal clicks so a
  JavaScript click is needed as a fallback.
"""

from __future__ import annotations

import contextlib
import os
import re

# A browser's and a driver's own `--version`, invoked below with a fixed argv
# and no shell.
import subprocess  # nosec B404
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..config import ScrapingConfig
from .base import ScrapeError

# Selectors tried in order when looking for a "Load More" control.
LOAD_MORE_SELECTORS = (
    "a.jet-filters-load-more__btn",
    "button.jet-filters-load-more__btn",
    ".jet-filters-load-more__btn",
    "a[href*='#jet-load-more']",
    ".elementor-button[href*='load-more']",
)
LOAD_MORE_XPATH = (
    "//*[contains(translate(normalize-space(text()),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'load more')]"
)


class BrowserUnavailable(ScrapeError):
    """Selenium or Chrome is not installed on this machine."""


#: Where a Chrome or Chromium binary actually lives, in the order to try.
#:
#: Selenium Manager finds a browser on its own, and looks for "chrome" and
#: "google-chrome". Ubuntu ships neither: `apt install chromium-browser`
#: installs a *snap* -- the deb is a transitional shim -- and the real binary
#: is /snap/bin/chromium. So the install succeeds, the browser works, and
#: Selenium reports "Unable to obtain driver for chrome", which reads as
#: nothing being installed at all.
_CHROME_BINARIES = (
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome",
    "/snap/bin/chromium",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)

#: The driver that goes with each browser, in the order to try.
#:
#: **Paired, not a separate list, and that is the whole of the lesson here.**
#: The first version of this searched for a browser and a driver independently,
#: found /snap/bin/chromium and /usr/bin/chromedriver, and handed Selenium a
#: driver that cannot drive that browser: on Ubuntu /usr/bin/chromedriver is a
#: shim for the snap and dies under confinement with "Service
#: /usr/bin/chromedriver unexpectedly exited. Status code was: 46". The canary
#: reported Royal Tiger broken for it, on a machine where Chromium works.
#:
#: A driver has to match the browser it drives, so the browser is chosen first
#: and the driver follows from it.
#:
#: **And /usr/local/bin comes before /usr/bin for the packaged browsers**, which
#: is the second half of the same lesson and was missing for a while. The
#: comment above knew /usr/bin/chromedriver is a snap shim on Ubuntu; the order
#: below still reached for it first. On a box with Google Chrome installed from
#: its .deb and a real driver placed at /usr/local/bin/chromedriver by hand, the
#: shim won and died with "Status code was: 1" -- a second afternoon lost to the
#: same file. /usr/local/bin is where an administrator puts something on
#: purpose, and on this question their deliberate act outranks whatever apt left
#: behind. `is_snap_driver` below is the belt to this braces.
_DRIVERS_FOR = {
    "/usr/bin/google-chrome": ("/usr/local/bin/chromedriver", "/usr/bin/chromedriver"),
    "/usr/bin/google-chrome-stable": ("/usr/local/bin/chromedriver", "/usr/bin/chromedriver"),
    "/opt/google/chrome/chrome": ("/usr/local/bin/chromedriver", "/usr/bin/chromedriver"),
    # The snap ships its own, namespaced. Nothing else can drive it.
    "/snap/bin/chromium": ("/snap/bin/chromium.chromedriver",),
    "/usr/bin/chromium": (
        "/usr/lib/chromium/chromedriver",
        "/usr/bin/chromedriver",
    ),
    "/usr/bin/chromium-browser": (
        "/usr/lib/chromium-browser/chromedriver",
        "/usr/bin/chromedriver",
    ),
}


def _no_new_privileges() -> bool:
    """Whether this process may no longer gain privileges through execve().

    Read rather than assumed, because the answer decides which of two very
    different messages is the true one. Systemd's ``NoNewPrivileges=true`` sets
    it, and the shipped unit does -- deliberately, since a scraper runs a
    vendor's JavaScript and is the process on this machine you least want able
    to escalate.
    """
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("NoNewPrivs:"):
                return line.split()[1] == "1"
    except OSError:
        pass
    return False


def _snap_cannot_run_here(binary: str | None) -> bool:
    """Whether a snap browser has been chosen in a process that cannot start one.

    **A snap is not an ordinary executable.** ``snap-confine`` builds the
    sandbox before the browser starts, and to do that it needs privileges it
    picks up from file capabilities -- ``cap_sys_admin`` and ``cap_sys_chroot``
    among them. ``NoNewPrivileges=true`` is precisely a promise that no
    executable will ever pick those up, so ``snap-confine`` dies on the spot
    and Selenium reports only what it saw: "Service /snap/bin/chromium
    .chromedriver unexpectedly exited. Status code was: 46."

    The unit forbids it twice more for good measure -- ``RestrictNamespaces``
    denies the mount namespace the sandbox is made of, and
    ``SystemCallFilter=@system-service`` covers neither ``mount`` nor
    ``pivot_root``. So this is not a misconfiguration to be tuned around: a
    snap browser and this service unit cannot both be right, and the hardening
    is the half worth keeping.
    """
    return bool(binary) and str(binary).startswith("/snap/") and _no_new_privileges()


def is_snap_driver(path: str) -> bool:
    """Whether *path* is really the snap's chromedriver wearing another name.

    Ubuntu's ``chromium-chromedriver`` leaves a shim at /usr/bin/chromedriver
    that hands off to /snap/bin/chromium.chromedriver. It is a perfectly good
    driver *for the snap* and cannot drive anything else, so pairing it with
    Google Chrome produces a process that exits immediately and a message that
    blames the browser.

    Both shapes are checked because both exist: a symlink into /snap, and a
    small wrapper script that execs the snap. Anything unreadable, or big
    enough to be a real binary, is taken at face value -- a false "this is a
    snap" would hide a working driver, which is the worse mistake.
    """
    try:
        target = Path(path).resolve()
        if str(target).startswith("/snap/"):
            return True
        if target.stat().st_size > _SHIM_MAX_BYTES:
            return False
        head = target.read_bytes()[:_SHIM_MAX_BYTES]
    except OSError:
        return False
    return head.startswith(b"#!") and b"/snap/" in head


#: A wrapper script is a few hundred bytes; a chromedriver is fifteen megabytes.
#: Anything above this is read as the real thing without opening it.
_SHIM_MAX_BYTES = 8192


#: A version as both binaries print it: "Google Chrome 153.0.8010.36" and
#: "ChromeDriver 153.0.8010.52 (78e5e45...)".
_VERSION_RE = re.compile(r"\b(\d+)\.(\d+)\.(\d+)\.(\d+)\b")

#: How long to wait for a ``--version`` to answer. Both binaries print and exit
#: in under a tenth of a second measured here; anything slower is a hung
#: process, and a hung process must not hold up a scan.
_VERSION_TIMEOUT = 10.0


def major_version(path: str) -> int | None:
    """The major version *path* reports, or None when it will not say.

    Deliberately **not** cached. This runs twice per browser scrape, costs
    about a tenth of a second, and the whole point of it is to notice a change
    that happened underneath a running process -- which is exactly what
    ``apt upgrade`` does to Chrome on a machine whose scheduler has been up for
    a week. A cached answer would be stale precisely when it mattered.
    """
    try:
        # Fixed argv, no shell, and one flag. `path` is a browser or driver
        # location -- from the tables above, or from config.yaml, which is a
        # file only root can write on a production install.
        result = subprocess.run(  # noqa: S603  # nosec B603
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_RE.search(f"{result.stdout} {result.stderr}")
    return int(match.group(1)) if match else None


def driver_matches(browser: str, driver: str) -> bool:
    """Whether *driver* is new enough to drive *browser*.

    **This is the one that `sudo apt upgrade` breaks.** Chrome and ChromeDriver
    are versioned together and released together, and a driver only drives the
    major version it was built for. Chrome updates itself through apt; a driver
    an administrator unpacked into /usr/local/bin by hand does not. So an
    ordinary upgrade quietly leaves the two a major version apart, Chrome exits
    the moment the driver speaks to it, and Selenium reports the least helpful
    sentence it has: *"session not created: Chrome instance exited. Examine
    ChromeDriver verbose log to determine the cause."* Every path in that
    message is correct and none of them is the problem -- the canary reported
    Royal Tiger broken on a machine where Chrome works perfectly well.

    An unknown version is a match. Only a version we *read from both* and found
    to disagree is rejected: a false mismatch would throw away a working driver
    on a host whose binaries decline to introduce themselves, and that is the
    worse mistake. It is the same judgment `is_snap_driver` makes.
    """
    theirs = major_version(browser)
    ours = major_version(driver)
    if theirs is None or ours is None:
        return True
    return theirs == ours


def _first_present(paths: tuple[str, ...]) -> str | None:
    """The first of *paths* that exists and can be run."""
    for path in paths:
        if os.access(path, os.X_OK):
            return path
    return None


def _first_usable_driver(browser: str, paths: tuple[str, ...]) -> str | None:
    """The first driver that exists *and* could plausibly drive *browser*.

    A snap driver is skipped for a browser that is not itself a snap. That is
    the invariant this module is built on, stated once here rather than trusted
    to the ordering of a dictionary.

    **And a driver a major version behind its browser is skipped too**, which
    is the same invariant in its other form: a driver has to match the browser
    it drives, and "match" is a version as much as it is a packaging. Returning
    None here is not giving up -- see find_chrome. Selenium Manager fetches a
    driver that does match, which is the right answer and the one an
    administrator would otherwise be woken up to perform by hand after every
    Chrome release.
    """
    browser_is_snap = browser.startswith("/snap/")
    for path in paths:
        if not os.access(path, os.X_OK):
            continue
        if is_snap_driver(path) and not browser_is_snap:
            continue
        if not driver_matches(browser, path):
            continue
        return path
    return None


def find_chrome() -> tuple[str | None, str | None]:
    """(browser, driver) discovered on this machine, either possibly None.

    The browser decides, and the driver follows it -- see _DRIVERS_FOR. A
    browser found with no driver beside it still returns: Selenium Manager can
    fetch a matching one, and letting it try is better than refusing to start.
    That is also what happens when every driver on the machine is too old for
    the browser, which is the ordinary state of a host a day after Chrome
    updated -- the driver is reported as absent rather than as present and
    broken, because absent is the condition Selenium Manager repairs.

    Only consulted where the configuration says nothing, so an installation
    that names its own paths is never second-guessed.
    """
    binary = _first_present(_CHROME_BINARIES)
    if binary is None:
        return None, None
    return binary, _first_usable_driver(binary, _DRIVERS_FOR.get(binary, ()))


def _let_selenium_manager_cache(config: ScrapingConfig) -> None:
    """Point Selenium Manager at somewhere it is actually allowed to write.

    Reached only when no driver was found on the machine, which since the
    version check above is also the ordinary state of a host whose Chrome has
    just been upgraded. Selenium Manager downloads the matching driver and
    keeps it, and that recovery is the whole answer to `apt upgrade` --
    *provided it has somewhere to keep it*.

    Under the shipped unit it does not. Its default is ~/.cache/selenium;
    ProtectHome=true hides the account's home, ProtectSystem=strict makes the
    rest of the filesystem read-only, and only ReadWritePaths survives. So the
    download would fail on a machine with a working browser, network and
    Selenium -- and the message would blame Chrome.

    SE_CACHE_PATH is Selenium Manager's own override and is left alone if an
    administrator has already set one. A directory that cannot be created is
    not fatal: without it Selenium Manager falls back to its default, which is
    where it would have looked anyway.
    """
    if os.environ.get("SE_CACHE_PATH") or config.driver_cache_path is None:
        return
    cache = Path(config.driver_cache_path)
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    os.environ["SE_CACHE_PATH"] = str(cache)


def _version_mismatch(binary: str | None, driver_path: str | None) -> str:
    """A sentence naming a browser and driver that are a version apart, or "".

    Only ever reached once the start has already failed, so it may run the two
    binaries again without costing a working scan anything. It exists for the
    case discovery cannot fix on its own: a driver named in config.yaml is
    never second-guessed -- somebody chose it -- so a pinned one that has gone
    stale is still handed to Selenium, still fails, and used to do so behind
    "Chrome instance exited", which names neither version.
    """
    if not binary or not driver_path:
        return ""
    theirs = major_version(binary)
    ours = major_version(driver_path)
    if theirs is None or ours is None or theirs == ours:
        return ""
    return (
        f" They are {abs(theirs - ours)} major version(s) apart: the browser is "
        f"{theirs} and the driver is {ours}, and a driver only drives the major "
        f"version it was built for. An upgrade of Chrome that left the driver "
        f"behind is the usual cause. Update the driver, or clear "
        f"scraping.selenium.chromedriver_path so Selenium Manager fetches the "
        f"matching one."
    )


@contextmanager
def chrome(config: ScrapingConfig) -> Iterator[Any]:
    """Yield a configured headless Chrome driver, always quitting it after."""
    try:
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        from selenium import webdriver
    except ImportError as exc:  # pragma: no cover - depends on host packages
        raise BrowserUnavailable(
            "selenium is not installed; run 'make install' or disable this site."
        ) from exc

    options = Options()
    if config.headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # Sites behind bot protection reject the default automation fingerprint.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"user-agent={config.user_agent}")
    found_binary, found_driver = find_chrome()
    binary = config.chrome_binary or found_binary
    driver_path = config.chromedriver_path or found_driver
    if binary:
        options.binary_location = binary
    if not driver_path:
        _let_selenium_manager_cache(config)

    try:
        service = Service(driver_path) if driver_path else None
        driver = webdriver.Chrome(options=options, service=service)
    except Exception as exc:  # pragma: no cover - depends on host browser
        # Say what was looked for. "Unable to obtain driver for chrome" on a
        # machine where `apt install chromium-browser` has just reported
        # success is a message that sends somebody to reinstall the thing they
        # already have -- the browser is there, under a name Selenium does not
        # try.
        # The snap case first, because when it applies every other sentence
        # below is a wild goose chase: the paths are right, the driver matches
        # its browser, and none of that is the problem.
        if _snap_cannot_run_here(binary):
            raise BrowserUnavailable(
                f"could not start headless Chrome: {exc}. The only browser found "
                f"was the snap at {binary}, and a snap cannot start inside this "
                f"service: snap-confine needs privileges that the unit's "
                f"NoNewPrivileges=true forbids it from acquiring, and "
                f"RestrictNamespaces=true denies the mount namespace its sandbox "
                f"is made of. Nothing in config.yaml can bridge that. Install a "
                f"non-snap browser -- Google Chrome's .deb, or chromium from a "
                f"PPA -- and this will find it at /usr/bin/google-chrome without "
                f"further configuration. The alternative, loosening the unit, "
                f"un-hardens the one process on the machine that runs a "
                f"stranger's JavaScript."
            ) from exc
        raise BrowserUnavailable(
            f"could not start headless Chrome: {exc}. "
            f"Browser: {binary or 'none found'}; driver: {driver_path or 'none found'}."
            f"{_version_mismatch(binary, driver_path)} "
            f"A driver must match its browser: the snap at /snap/bin/chromium "
            f"is driven only by /snap/bin/chromium.chromedriver. "
            f"Looked in {', '.join(_CHROME_BINARIES)}. Set scraping.selenium."
            f"chrome_binary and chromedriver_path in config.yaml, install Google "
            f"Chrome, or disable this site in the admin UI."
        ) from exc

    try:
        driver.set_page_load_timeout(config.request_timeout * 2)
        yield driver
    finally:
        # Best-effort cleanup: if the driver already died there is nothing to
        # quit, and raising here would mask the real scrape failure.
        with contextlib.suppress(Exception):
            driver.quit()


def wait_for_any(driver: Any, selectors: tuple[str, ...], timeout: int = 15) -> str | None:
    """Wait until one of ``selectors`` matches; return the one that did."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions
    from selenium.webdriver.support.ui import WebDriverWait

    deadline = time.monotonic() + timeout
    for selector in selectors:
        remaining = max(1, int(deadline - time.monotonic()))
        # A selector that does not appear is the normal case here: the point of
        # this helper is to discover which of several templates a page uses.
        with contextlib.suppress(Exception):
            WebDriverWait(driver, remaining).until(
                expected_conditions.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            return selector
    return None


def scroll_until_stable(
    driver: Any,
    harvest: Callable[[str], int],
    *,
    max_iterations: int = 40,
    idle_rounds: int = 6,
    settle_seconds: float = 3.0,
    check_stop: Callable[[], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    """Drive an infinite-scroll listing until it stops producing new items.

    ``harvest`` is called with the current page source after each scroll and
    returns the running total of unique items found; the loop ends once that
    total has not moved for ``idle_rounds`` consecutive iterations.

    Scrolling happens *before* harvesting: the page needs time to append its
    next batch, and parsing first would consistently miss the final batch.
    """
    log = log or (lambda _m: None)
    last_total = 0
    idle = 0

    for iteration in range(1, max_iterations + 1):
        if check_stop:
            check_stop()

        window_height = driver.execute_script("return window.innerHeight;")
        page_height = driver.execute_script("return document.body.scrollHeight;")

        # Small steps trigger lazy loading more reliably than one jump to the
        # bottom, which some listing widgets ignore entirely.
        driver.execute_script("window.scrollBy(0, 600);")
        time.sleep(1.5)

        position = driver.execute_script("return window.pageYOffset;")
        page_height = driver.execute_script("return document.body.scrollHeight;")
        if position + window_height >= page_height - 200:
            # At the bottom, nudge up and back down: the scroll handler only
            # fires on movement, so a second scrollTo(bottom) alone is a no-op.
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(settle_seconds)
            driver.execute_script("window.scrollBy(0, -150);")
            time.sleep(0.75)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(settle_seconds)
        else:
            time.sleep(settle_seconds)

        total = harvest(driver.page_source)
        if total == last_total:
            idle += 1
            if idle >= idle_rounds:
                log(f"No new items after {idle} scrolls; finished at {total}.")
                break
        else:
            log(f"Scroll {iteration}: {total} items so far.")
            idle = 0
            last_total = total

    return last_total


def click_load_more(driver: Any) -> bool:
    """Find and click a "Load More" control. False when there is none left.

    The button is often below the fold and absent from the accessibility tree
    until scrolled into view, so scrolling comes first and visibility is only
    judged afterward.
    """
    from selenium.webdriver.common.by import By

    button = None
    for selector in LOAD_MORE_SELECTORS:
        # Each selector is one candidate template; missing ones are expected.
        with contextlib.suppress(Exception):
            button = driver.find_element(By.CSS_SELECTOR, selector)
            break
    if button is None:
        try:
            button = driver.find_element(By.XPATH, LOAD_MORE_XPATH)
        except Exception:
            return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        time.sleep(1.5)
    except Exception:
        return False

    try:
        if not button.is_displayed() or not button.is_enabled():
            return False
    except Exception:
        # Stale element: the widget re-rendered, so there may still be more.
        return False

    try:
        button.click()
    except Exception:
        # Overlays and sticky headers intercept real clicks; dispatch directly.
        try:
            driver.execute_script("arguments[0].click();", button)
        except Exception:
            return False
    return True


def load_more_until_stable(
    driver: Any,
    harvest: Callable[[str], int],
    *,
    max_clicks: int = 100,
    settle_seconds: float = 4.0,
    check_stop: Callable[[], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    """Click "Load More" until it disappears or stops adding items."""
    log = log or (lambda _m: None)
    total = harvest(driver.page_source)
    for click in range(1, max_clicks + 1):
        if check_stop:
            check_stop()
        if not click_load_more(driver):
            log(f"No Load More button remaining; finished at {total} items.")
            break
        time.sleep(settle_seconds)
        new_total = harvest(driver.page_source)
        if new_total == total:
            log(f"Load More click {click} added nothing; finished at {total} items.")
            break
        total = new_total
        log(f"Load More click {click}: {total} items so far.")
    return total
