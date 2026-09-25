/**
 * Visual regression: each main page, compared pixel by pixel with a baseline.
 *
 * The end-to-end suite checks that the right things are on a page. This checks
 * that they still look right: a stylesheet change that pushes the sidebar over
 * the content, a card that loses its image, or a page that renders every
 * element but in the wrong place passes every other test.
 *
 * **Why the baselines hold still.** scripts/test-visual.sh seeds the sample
 * listings with every date counted back from one fixed moment (FROZEN below),
 * and each test sets the browser clock to that moment before the page loads.
 * "Listed 3 days ago" and "Sep 1, 2026" then read the same next month as they
 * do today. The server's own clock is not frozen, which is why the moment is in
 * the past: anything the server works out from the real date, such as a
 * cooldown that has since expired, only ever moves further the same way.
 *
 * **When one fails** the report holds the expected, actual and diff images. If
 * the change was intended, `make test-visual-update` rewrites the baselines,
 * and the new images go in with the change that caused them.
 */
import { test, expect } from "@playwright/test";

const USERNAME = process.env.MILSURP_USER || "admin";
const PASSWORD = process.env.MILSURP_PASSWORD || "";
const FROZEN = new Date(process.env.MILSURP_VISUAL_NOW || "2026-09-01T15:00:00Z");

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FROZEN);
});

/** Wait until the page has stopped changing: data, photos and fonts. */
async function settle(page) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Loading…")).toHaveCount(0);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      [...document.images]
        .filter((img) => !img.complete)
        .map(
          (img) =>
            new Promise((done) => {
              img.addEventListener("load", done, { once: true });
              img.addEventListener("error", done, { once: true });
            }),
        ),
    );
  });
}

async function signIn(page) {
  await page.goto("/");
  await page.fill('input[name="username"]', USERNAME);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await expect(page.getByRole("heading", { name: "Inventory" })).toBeVisible();
  await expect(page.getByText(/listings? match your filters/)).toBeVisible();
}

async function open(page, path, heading) {
  await page.goto(path);
  await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  await settle(page);
}

test("sign-in", async ({ page }) => {
  await page.goto("/");
  await page.waitForSelector('input[name="username"]');
  await settle(page);
  await expect(page).toHaveScreenshot("sign-in.png");
});

test("inventory", async ({ page }) => {
  await signIn(page);
  await settle(page);
  await expect(page).toHaveScreenshot("inventory.png", { fullPage: true });
});

test("item detail", async ({ page }) => {
  await signIn(page);
  await page.locator(".item-card").first().click();
  await expect(page.locator(".detail")).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("item-detail.png", { fullPage: true });
});

// The rest are desktop only. On a phone they are the same components in one
// column, which the three above already cover, and every extra baseline is one
// more image to review when the shared styles change.
const PAGES = [
  ["/hot-deals", "Hot deals", "hot-deals"],
  ["/market", "Market", "market"],
  ["/sites", "Sites", "sites"],
  ["/armory", "Armory", "armory"],
  ["/settings", "Email digest", "email-digest"],
  ["/saved-searches", "Saved searches", "saved-searches"],
  ["/watchlist", "Watchlist", "watchlist"],
];

for (const [path, heading, name] of PAGES) {
  test(heading, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === "mobile", "desktop only; see above");
    await signIn(page);
    await open(page, path, heading);
    await expect(page).toHaveScreenshot(`${name}.png`, { fullPage: true });
  });
}
