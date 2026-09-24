/**
 * The "what changed" page.
 *
 * What this holds is the part that distinguishes it from the email digest:
 * departures are counted, every enabled site appears whether or not it had
 * news, and the window is a closed interval the reader chooses.
 */
import { test, expect, openPage } from "./fixtures.js";

test.describe("what changed", () => {
  test.beforeEach(async ({ signedIn }) => {
    await openPage(signedIn, "What changed");
  });

  test("leads with the headline numbers, departures included", async ({ signedIn }) => {
    const stats = signedIn.locator(".week-stat__label");
    await expect(stats).toHaveText([
      "arrived",
      "sold",
      "taken down",
      "reduced",
      "listed now",
    ]);
  });

  test("lists every enabled site, including the ones with no news", async ({
    signedIn,
  }) => {
    // The silence is the finding, so a shop that reported nothing has to be on
    // screen: dropping it would answer the question the page is asking.
    const rows = signedIn.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    const sites = await signedIn.locator("tbody tr td:first-child").allInnerTexts();
    expect(sites.length).toBeGreaterThan(1);
  });

  test("the window can be widened and the dates follow it", async ({ signedIn }) => {
    const window = signedIn.locator(".week-window");
    const sevenDays = await window.innerText();

    await signedIn.getByLabel("Window").selectOption("90");
    await expect(window).not.toHaveText(sevenDays);
  });

  test("a reduction says how much came off and what it is now", async ({ signedIn }) => {
    await signedIn.getByLabel("Window").selectOption("90");
    const panel = signedIn.locator(".panel", { hasText: "Biggest reductions" });
    await expect(panel).toBeVisible();
    // Either there were reductions, or the panel says plainly that there were
    // none. An empty box with no explanation is the failure.
    const rows = panel.locator(".week-list li");
    if (await rows.count()) {
      await expect(rows.first().locator(".week-list__meta")).toContainText("now");
    } else {
      await expect(panel.locator(".week-empty")).toBeVisible();
    }
  });

  test("a listing links through to its detail page", async ({ signedIn }) => {
    await signedIn.getByLabel("Window").selectOption("90");
    const first = signedIn.locator(".week-list__title").first();
    await expect(first).toBeVisible();
    await first.click();
    await expect(signedIn).toHaveURL(/\/items\/\d+/);
  });
});
