/**
 * Playwright configuration for the visual regression tests.
 *
 * Separate from playwright.config.js because the two suites want opposite
 * things. The end-to-end suite changes the database as it goes and runs on an
 * instrumented bundle; these tests compare pixels, so they want a database
 * nothing writes to, the production bundle, and a browser that renders the
 * same way on every machine.
 *
 * That last one is why the browser runs in a container. Font rendering differs
 * between a developer's desktop and a CI runner, which is enough to fail a
 * pixel comparison while the page is actually fine. scripts/test-visual.sh starts
 * the official Playwright image, pinned to the version in package.json, and
 * passes its address through MILSURP_PW_ENDPOINT. Without it the tests use a
 * local browser, which is fine for trying something out and no good for
 * baselines.
 *
 * Run through `make test-visual`; `make test-visual-update` rewrites the
 * baselines after an intended change.
 */
import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.MILSURP_URL || "http://127.0.0.1:8730";
const ENDPOINT = process.env.MILSURP_PW_ENDPOINT;

export default defineConfig({
  testDir: "./tests/visual",
  testMatch: "**/*.visual.js",
  // One file of baselines per page, named by the test, with no platform
  // suffix: the container is the platform, so there is only ever one.
  snapshotPathTemplate: "{testDir}/baselines/{projectName}/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  reporter: process.env.CI ? [["list"], ["github"]] : [["list"]],
  outputDir: process.env.MILSURP_E2E_OUTPUT_DIR || "test-results-visual",

  expect: {
    timeout: 15_000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      // Anti-aliasing can still move a few pixels on a page that did not
      // change. 0.2% of a 1440x900 page is about 2,600 pixels, which absorbs
      // that noise, while a moved button, a changed color or a missing
      // section are each far larger.
      maxDiffPixelRatio: 0.002,
    },
  },

  use: {
    baseURL: BASE_URL,
    // Every date on screen is formatted in the browser's locale and zone, and
    // the container's defaults are not a developer's.
    locale: "en-US",
    timezoneId: "UTC",
    trace: "retain-on-failure",
    screenshot: "off",
    video: "off",
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
    ...(ENDPOINT ? { connectOptions: { wsEndpoint: ENDPOINT } } : {}),
  },

  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
