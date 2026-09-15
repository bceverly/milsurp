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
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
_DRIVERS_FOR = {
    "/usr/bin/google-chrome": ("/usr/bin/chromedriver", "/usr/local/bin/chromedriver"),
    "/usr/bin/google-chrome-stable": ("/usr/bin/chromedriver", "/usr/local/bin/chromedriver"),
    "/opt/google/chrome/chrome": ("/usr/bin/chromedriver", "/usr/local/bin/chromedriver"),
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


def _first_present(paths: tuple[str, ...]) -> str | None:
    """The first of *paths* that exists and can be run."""
    for path in paths:
        if os.access(path, os.X_OK):
            return path
    return None


def find_chrome() -> tuple[str | None, str | None]:
    """(browser, driver) discovered on this machine, either possibly None.

    The browser decides, and the driver follows it -- see _DRIVERS_FOR. A
    browser found with no driver beside it still returns: Selenium Manager can
    fetch a matching one, and letting it try is better than refusing to start.

    Only consulted where the configuration says nothing, so an installation
    that names its own paths is never second-guessed.
    """
    binary = _first_present(_CHROME_BINARIES)
    if binary is None:
        return None, None
    return binary, _first_present(_DRIVERS_FOR.get(binary, ()))


@contextmanager
def chrome(config: ScrapingConfig) -> Iterator[Any]:
    """Yield a configured headless Chrome driver, always quitting it after."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
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

    try:
        service = Service(driver_path) if driver_path else None
        driver = webdriver.Chrome(options=options, service=service)
    except Exception as exc:  # pragma: no cover - depends on host browser
        # Say what was looked for. "Unable to obtain driver for chrome" on a
        # machine where `apt install chromium-browser` has just reported
        # success is a message that sends somebody to reinstall the thing they
        # already have -- the browser is there, under a name Selenium does not
        # try.
        raise BrowserUnavailable(
            f"could not start headless Chrome: {exc}. "
            f"Browser: {binary or 'none found'}; driver: {driver_path or 'none found'}. "
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
