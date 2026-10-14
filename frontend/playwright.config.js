/**
 * Playwright configuration.
 *
 * The suite drives the real application: the Python API and the built frontend,
 * started by scripts/test-frontend.sh, which passes the URL through
 * MILSURP_URL. The bundle is built with COVERAGE=1 so vite-plugin-istanbul
 * instruments it, and the coverage fixture in tests/fixtures.js harvests
 * window.__coverage__ after each test into .nyc_output/ for nyc to report.
 */
import { defineConfig, devices } from "@playwright/test";

// One app per worker, each on its own copy of the disposable database, when
// the harness starts several (scripts/test-frontend.sh, 2026-10-14): the suite
// writes as it goes, so two workers on one database would race. The config is
// evaluated again in every worker process, where TEST_PARALLEL_INDEX says
// which worker this is -- so every spec, fixture or not, talks to its own app.
const APPS = (process.env.MILSURP_URLS || "").split(/\s+/).filter(Boolean);
const BASE_URL = APPS.length
  ? APPS[Number(process.env.TEST_PARALLEL_INDEX || 0) % APPS.length]
  : process.env.MILSURP_URL || "http://127.0.0.1:8730";
const WORKERS = Math.max(1, APPS.length);

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.js",
  // Files in parallel, one worker per app; the tests within a file in order,
  // because several build on what the one before them left.
  fullyParallel: false,
  workers: WORKERS,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Headroom for a loaded machine, not for slow tests. A passing test takes
  // no longer for these; a run that shares its CPU with a backend suite or a
  // build (one did, September 2026) ran every test three to five times slower,
  // and four waits that normally finish inside two seconds crossed ten.
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["github"]] : [["list"]],
  // Per-run when the harness says so. Two concurrent runs sharing one output
  // directory delete each other's traces as they start, which fails a test
  // that never ran badly. See scripts/test-frontend.sh.
  outputDir: process.env.MILSURP_E2E_OUTPUT_DIR || "test-results",

  use: {
    baseURL: BASE_URL,
    // Artifacts only for failures: a green run should not leave a pile of
    // videos and traces behind.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
  },

  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
      // The responsive spec asserts the phone layout, so it belongs to the
      // mobile project alone — at 1440px the drawer and filter toggle are not
      // rendered at all.
      testIgnore: "**/responsive.spec.js",
    },
    {
      // The app is used on a phone as much as a desktop, so the responsive
      // layout is a first-class target rather than a spot check.
      name: "mobile",
      use: { ...devices["Pixel 7"] },
      testMatch: "**/responsive.spec.js",
    },
  ],
});
