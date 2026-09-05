/**
 * Shared Playwright fixtures.
 *
 * Two jobs:
 *
 *  1. `signedIn` — a page that has already authenticated, so individual specs
 *     do not each re-type the login form.
 *  2. Coverage collection — the bundle under test is instrumented by
 *     vite-plugin-istanbul (COVERAGE=1), which leaves an object on
 *     `window.__coverage__`. It is read after each test and appended to
 *     .nyc_output/, which is what `nyc report` consumes. Without this the
 *     instrumentation would produce nothing.
 */
import { test as base, expect } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

const NYC_OUTPUT = resolve(process.cwd(), ".nyc_output");
const USERNAME = process.env.MILSURP_USER || "admin";
const PASSWORD = process.env.MILSURP_PASSWORD || "";

/** Read window.__coverage__ and write it where nyc will find it. */
async function collectCoverage(page) {
  if (page.isClosed()) return;
  let coverage = null;
  try {
    coverage = await page.evaluate(() => window.__coverage__ || null);
  } catch {
    // The page navigated or closed mid-teardown; nothing to collect.
    return;
  }
  if (!coverage) return;
  mkdirSync(NYC_OUTPUT, { recursive: true });
  writeFileSync(
    resolve(NYC_OUTPUT, `playwright-${randomUUID()}.json`),
    JSON.stringify(coverage),
  );
}

export const test = base.extend({
  // Wrap the built-in page so every test contributes coverage, whether or not
  // it uses the signedIn fixture.
  page: async ({ page }, use) => {
    await use(page);
    await collectCoverage(page);
  },

  /** A page already signed in as the seeded admin account. */
  signedIn: async ({ page }, use) => {
    await page.goto("/");
    await page.waitForSelector('input[name="username"]');
    await page.fill('input[name="username"]', USERNAME);
    await page.fill('input[name="password"]', PASSWORD);
    await page.click('button[type="submit"]');
    await expect(page.getByRole("heading", { name: "Inventory" })).toBeVisible();
    await use(page);
  },
});

export { expect };
