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

// Per-run when the harness says so, for the same reason as the Playwright
// output directory: two runs merging into one .nyc_output report a coverage
// figure that belongs to neither of them.
const NYC_OUTPUT =
  process.env.MILSURP_E2E_NYC_DIR || resolve(process.cwd(), ".nyc_output");
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
    // Settled, not merely drawn: the heading appears before the listings have
    // loaded, and a test that clicks a nav link in that window has its click
    // swallowed by the re-render that follows. On a busy machine that window
    // is long enough to lose a click in most runs.
    await expect(page.getByText(/listings? match your filters/)).toBeVisible();
    await use(page);
  },
});

/**
 * Open a page from the navigation and wait until it is really there.
 *
 * Its own heading, matched exactly, is the signal -- the inventory the tests
 * start on carries headings like "US M1 Garand, Springfield Armory 1944", so
 * a loose match can pass on the wrong page. And the click is repeated until
 * the heading arrives: a click that lands while the page underneath is still
 * re-rendering can be lost, and clicking the link to a page already open is
 * harmless.
 */
export async function openPage(page, link, heading = link) {
  await expect(async () => {
    await revealInRail(page, link);
    await page.getByRole("link", { name: link, exact: true }).click();
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible({
      timeout: 3_000,
    });
  }).toPass({ timeout: 30_000 });
}

/**
 * Open the rail section holding *link*, if it is folded away.
 *
 * The rail starts with only the catalog open, so a link under Yours, Account
 * or Administration is hidden until its heading is clicked -- as a person
 * would do. A link that is already showing, or is not in the rail at all,
 * leaves the rail alone.
 */
export async function revealInRail(page, link) {
  const rail = page.getByRole("navigation", { name: "Main navigation" });
  if (await rail.getByRole("link", { name: link, exact: true }).isVisible()) return;
  for (const toggle of await rail.locator("button[aria-expanded='false']").all()) {
    const list = rail.locator(`#${await toggle.getAttribute("aria-controls")}`);
    const inside = list.getByRole("link", {
      name: link,
      exact: true,
      includeHidden: true,
    });
    if ((await inside.count()) > 0) {
      await toggle.click();
      return;
    }
  }
}

export { expect };
