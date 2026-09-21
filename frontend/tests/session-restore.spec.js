/**
 * Being thrown out, and being put back.
 *
 * Losing a session is rarely something the reader did: it expires, or the
 * server has a bad few minutes and every call starts failing. Landing on the
 * inventory after signing back in loses their place every time, so the page
 * they were on travels with them to the sign-in screen and they are returned
 * to it.
 *
 * Except when that page is *why* they were thrown out. A page that asked the
 * server for more than it could give gets a gateway error from the proxy in
 * front, and sending somebody straight back to it hands them the same dead
 * screen with nothing explaining it. So the restored page is watched, and if
 * it does not come up they go to the inventory with a note naming the address
 * that would not open.
 */
import { test, expect } from "./fixtures.js";

const USERNAME = process.env.MILSURP_USER || "admin";
const PASSWORD = process.env.MILSURP_PASSWORD || "";

/** Sign in on a page that is already sitting on the login screen. */
async function signIn(page) {
  await page.waitForSelector('input[name="username"]');
  await page.fill('input[name="username"]', USERNAME);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
}

/** Drop the session the way the server dropping it looks from in here. */
async function loseTheSession(page) {
  await page.route("**/api/**", (route) => route.fulfill({ status: 401, body: "{}" }));
  await page.reload();
  await page.waitForSelector('input[name="username"]');
  await page.unroute("**/api/**");
}

test.describe("coming back from a forced sign-out", () => {
  test("lands on the page they were thrown off, not the inventory", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("link", { name: "Watchlist" }).click();
    await expect(signedIn).toHaveURL(/\/watchlist$/);

    await loseTheSession(signedIn);
    await signIn(signedIn);

    await expect(signedIn).toHaveURL(/\/watchlist$/);
    await expect(signedIn.getByRole("heading", { name: "Watchlist" })).toBeVisible();
  });

  test("but goes to the inventory when that page will not load", async ({ signedIn }) => {
    await signedIn.getByRole("link", { name: "Hot deals" }).click();
    await expect(signedIn).toHaveURL(/\/hot-deals$/);

    await loseTheSession(signedIn);

    // The page they are about to be returned to is the one in trouble. 504 is
    // what the proxy in front answers with when the application behind it has
    // stopped keeping up, which is exactly the state this exists for.
    await signedIn.route("**/api/hot-deals**", (route) =>
      route.fulfill({
        status: 504,
        contentType: "text/html",
        body: "<h1>Gateway Time-out</h1>",
      }),
    );
    await signIn(signedIn);

    await expect(signedIn).toHaveURL(/\/$/);
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });

  test("but pressing Sign out is not being thrown off anything", async ({ signedIn }) => {
    // The one case where the last page open is *not* worth restoring: they
    // have just said they were finished with it. Reopening it would be the
    // app arguing with them.
    await signedIn.getByRole("link", { name: "Watchlist" }).click();
    await expect(signedIn).toHaveURL(/\/watchlist$/);

    await signedIn.locator("button.topbar__signout").click();
    await expect(signedIn).toHaveURL(/\/login/);
    await signIn(signedIn);

    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });

  test("and says which address it could not open", async ({ signedIn }) => {
    // A silent redirect is indistinguishable from the app having forgotten
    // where they were, which is the thing this is meant to stop feeling like.
    await signedIn.getByRole("link", { name: "Hot deals" }).click();
    await expect(signedIn).toHaveURL(/\/hot-deals$/);

    await loseTheSession(signedIn);
    await signedIn.route("**/api/hot-deals**", (route) =>
      route.fulfill({
        status: 504,
        contentType: "text/html",
        body: "<h1>Gateway Time-out</h1>",
      }),
    );
    await signIn(signedIn);

    const note = signedIn.locator(".alert--warning");
    await expect(note).toBeVisible();
    await expect(note).toContainText("/hot-deals");
    await expect(note).toContainText(/would not load/i);
  });
});
