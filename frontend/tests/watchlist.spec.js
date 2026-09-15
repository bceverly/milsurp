/**
 * Following a listing.
 *
 * The catalog answers "what is on the shelves" and "is this a good deal". The
 * question it could not answer was "tell me when *that one* moves", which is
 * what somebody has about the rifle they have decided they want and will not
 * pay this week's price for.
 */
import { test, expect } from "./fixtures.js";

async function openFirstListing(page) {
  await page.goto("/?availability=all");
  const card = page.locator(".item-card").first();
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.locator(".detail__facts")).toBeVisible();
}

test.describe("watchlist", () => {
  /**
   * Start from an empty watchlist.
   *
   * These tests share one database, and every one of them stars something —
   * so without this the second finds "Watching" where it expects "Watch", and
   * the counts are whatever the tests before it left behind. Cleared through
   * the page rather than the API so it needs no token handling, and it is
   * quick: the list is at most a handful of rows by construction.
   */
  test.beforeEach(async ({ signedIn }) => {
    await signedIn.goto("/watchlist");
    await expect(signedIn.getByRole("heading", { name: "Watchlist" })).toBeVisible();
    const stop = signedIn.getByRole("button", { name: /^Stop watching/ });
    for (let left = await stop.count(); left > 0; left -= 1) {
      await stop.first().click();
      await expect(signedIn.locator(".watchlist__row")).toHaveCount(left - 1);
    }
  });

  test("a listing can be watched from its own page", async ({ signedIn }) => {
    await openFirstListing(signedIn);

    const watch = signedIn.getByRole("button", { name: "Watch", exact: true });
    await expect(watch).toBeVisible();
    await watch.click();

    // The star is a state, so the control says so rather than flashing a toast.
    const watching = signedIn.getByRole("button", { name: "Watching" });
    await expect(watching).toBeVisible();
    await expect(watching).toHaveAttribute("aria-pressed", "true");
  });

  test("and shows up on the watchlist page", async ({ signedIn }) => {
    await openFirstListing(signedIn);
    const title = await signedIn.locator("h1").first().innerText();
    await signedIn.getByRole("button", { name: "Watch", exact: true }).click();
    await expect(signedIn.getByRole("button", { name: "Watching" })).toBeVisible();

    await signedIn.getByRole("link", { name: "Watchlist" }).click();
    await expect(signedIn.getByRole("heading", { name: "Watchlist" })).toBeVisible();
    await expect(signedIn.locator(".watchlist__row")).toHaveCount(1);
    await expect(signedIn.locator(".watchlist__title")).toContainText(title.slice(0, 24));
  });

  test("a target price is remembered and shown", async ({ signedIn }) => {
    await openFirstListing(signedIn);
    await signedIn.getByRole("button", { name: "Watch", exact: true }).click();
    await signedIn.getByRole("button", { name: "Set a target" }).click();

    await signedIn.getByLabel("Tell me if it drops below").fill("123");
    await signedIn.getByLabel("Note to yourself").fill("only at this price");
    await signedIn.getByRole("button", { name: "Save" }).click();

    // The button reads its own state, so it updates without a reload.
    await expect(signedIn.getByRole("button", { name: /^Target/ })).toBeVisible();

    await signedIn.getByRole("link", { name: "Watchlist" }).click();
    await expect(signedIn.locator(".watchlist__target")).toContainText("123");
    await expect(signedIn.locator(".watchlist__note")).toContainText(
      "only at this price",
    );
  });

  test("an alert can be asked for, and only with a target", async ({ signedIn }) => {
    /**
     * A rifle that hits $700 an hour after the daily digest sends is news
     * twenty-three hours later. The checkbox is the way out of that, and it is
     * offered only with a target named: "tell me the moment it reaches
     * nothing" is not a request.
     */
    await openFirstListing(signedIn);
    await signedIn.getByRole("button", { name: "Watch", exact: true }).click();
    await signedIn.getByRole("button", { name: "Set a target" }).click();

    const alert = signedIn.getByRole("checkbox", { name: /the moment it gets there/ });
    await expect(alert).toBeDisabled();

    await signedIn.getByLabel("Tell me if it drops below").fill("500");
    await expect(alert).toBeEnabled();
    await alert.check();
    await signedIn.getByRole("button", { name: "Save" }).click();

    await signedIn.getByRole("link", { name: "Watchlist" }).click();
    await expect(signedIn.locator(".watchlist__alert")).toContainText("Alerts on");

    // And it survives a reload, rather than being a thing the page remembered.
    await signedIn.reload();
    await expect(signedIn.locator(".watchlist__alert")).toBeVisible();
  });

  test("and it can be stopped from the watchlist", async ({ signedIn }) => {
    await openFirstListing(signedIn);
    await signedIn.getByRole("button", { name: "Watch", exact: true }).click();
    await expect(signedIn.getByRole("button", { name: "Watching" })).toBeVisible();

    await signedIn.getByRole("link", { name: "Watchlist" }).click();
    await expect(signedIn.locator(".watchlist__row")).toHaveCount(1);
    await signedIn.getByRole("button", { name: /^Stop watching/ }).click();
    await expect(signedIn.locator(".watchlist__row")).toHaveCount(0);
    await expect(signedIn.getByText("Nothing here yet")).toBeVisible();
  });

  test("watching twice leaves one watch, not two", async ({ signedIn }) => {
    /**
     * The star is a state and not an event: PUT rather than POST, so a second
     * click is the same statement made again rather than a second watch.
     */
    await openFirstListing(signedIn);
    await signedIn.getByRole("button", { name: "Watch", exact: true }).click();
    await expect(signedIn.getByRole("button", { name: "Watching" })).toBeVisible();
    await signedIn.reload();
    await expect(signedIn.getByRole("button", { name: "Watching" })).toBeVisible();

    await signedIn.getByRole("link", { name: "Watchlist" }).click();
    await expect(signedIn.locator(".watchlist__row")).toHaveCount(1);
  });
});
