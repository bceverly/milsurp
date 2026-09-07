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

const BASE_URL = process.env.MILSURP_URL || "http://127.0.0.1:8730";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.js",
  // The suite writes to a shared database, so tests must not race each other.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
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
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
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
