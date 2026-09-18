/**
 * Notifications on this browser.
 *
 * Playwright cannot grant a real push subscription — that needs a live push
 * service — so what is held here is everything up to that boundary: that the
 * panel exists, that it tells the truth about whether the *server* can send,
 * and that the two "no" answers are not conflated. Sending somebody to change
 * a browser setting over a server that has no keys is the failure this page
 * most easily has.
 */
import { test, expect } from "./fixtures.js";

test.describe("notifications", () => {
  test.beforeEach(async ({ signedIn }) => {
    await signedIn.getByRole("link", { name: "Security settings" }).click();
    await expect(
      signedIn.getByRole("heading", { name: "Security settings" }),
    ).toBeVisible();
  });

  test("the panel says the server cannot send when it has no keys", async ({
    signedIn,
  }) => {
    // The e2e config generates no VAPID pair, so this is the honest state of
    // that deployment rather than a browser problem.
    const panel = signedIn.locator(".panel", { hasText: "Notifications" }).first();
    await expect(panel).toBeVisible();
    await expect(panel.getByText("Unavailable")).toBeVisible();
    await expect(panel).toContainText("no push keys");
    await expect(panel).toContainText("milsurp secrets");
  });

  test("and offers no button that could not work", async ({ signedIn }) => {
    const panel = signedIn.locator(".panel", { hasText: "Notifications" }).first();
    await expect(panel.getByRole("button", { name: /Turn on/ })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Send a test" })).toHaveCount(0);
  });

  test("the service worker is served from the root, where its scope needs it", async ({
    signedIn,
  }) => {
    // A worker under /assets/ could only control /assets/. This is the one
    // part of the feature a test can check without a push service.
    const response = await signedIn.request.get("/sw.js");
    expect(response.status()).toBe(200);
    const body = await response.text();
    expect(body).toContain("notificationclick");
    expect(body).toContain("showNotification");
  });
});
