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
import { test, expect, openPage } from "./fixtures.js";

test.describe("notifications", () => {
  test.beforeEach(async ({ signedIn }) => {
    await openPage(signedIn, "Security settings");
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

/**
 * A server that *can* send, stood in for with Playwright routes.
 *
 * The e2e deployment has no push keys, so everything past "Unavailable" was
 * never drawn in a test: the device list, a test send, turning a device off,
 * and what the page says when the browser refuses. The routes answer as the
 * real endpoints do; the page is the thing under test.
 */
test.describe("notifications, on a server with keys", () => {
  const DEVICE = {
    id: 7,
    user_agent: "Firefox on Linux",
    created_at: "2026-09-01T12:00:00Z",
    last_used_at: null,
  };

  async function withKeys(page, subscriptions = [DEVICE]) {
    await page.route("**/api/push", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            json: { available: true, public_key: "BExampleKey_-", subscriptions },
          })
        : route.fallback(),
    );
  }

  async function open(page) {
    await page.goto("/security");
    const panel = page.locator(".panel", { hasText: "Notifications" }).first();
    await expect(panel).toBeVisible();
    return panel;
  }

  test("a registered device is listed, and has never been notified", async ({
    signedIn,
  }) => {
    await withKeys(signedIn);
    const panel = await open(signedIn);
    await expect(panel.getByText("1 device(s)")).toBeVisible();
    const row = panel.locator("tbody tr", { hasText: "Firefox on Linux" });
    await expect(row).toContainText("never");
    await expect(panel.getByRole("button", { name: "Send a test" })).toBeVisible();
  });

  test("a test is sent and the page says where it went", async ({ signedIn }) => {
    await withKeys(signedIn);
    await signedIn.route("**/api/push/test", (route) =>
      route.fulfill({ json: { subscriptions: [DEVICE] } }),
    );
    const panel = await open(signedIn);
    await panel.getByRole("button", { name: "Send a test" }).click();
    await expect(panel.locator(".alert--success")).toContainText("Sent to 1 device(s)");
  });

  test("a failed test says why rather than claiming success", async ({ signedIn }) => {
    await withKeys(signedIn);
    await signedIn.route("**/api/push/test", (route) =>
      route.fulfill({ status: 502, json: { detail: "The push service refused it." } }),
    );
    const panel = await open(signedIn);
    await panel.getByRole("button", { name: "Send a test" }).click();
    await expect(panel.getByRole("alert")).toContainText("The push service refused it.");
  });

  test("a device can be turned off", async ({ signedIn }) => {
    await withKeys(signedIn);
    let deleted = null;
    await signedIn.route("**/api/push/7", (route) => {
      deleted = route.request().method();
      return route.fulfill({ status: 200, json: {} });
    });
    const panel = await open(signedIn);
    await panel.getByRole("button", { name: "Turn off" }).click();
    await expect(panel.locator(".alert--success")).toContainText("Stopped");
    expect(deleted).toBe("DELETE");
  });

  test("a browser that blocks notifications is told so, not left guessing", async ({
    signedIn,
  }) => {
    // The prompt answered "denied" -- what a browser says when the site has
    // been blocked -- before the page loads, so the page's own code sees it.
    await signedIn.addInitScript(() => {
      if ("Notification" in window) {
        Notification.requestPermission = () => Promise.resolve("denied");
      }
    });
    await withKeys(signedIn, []);
    const panel = await open(signedIn);
    await expect(panel.getByText("Off")).toBeVisible();
    await panel.getByRole("button", { name: "Turn on for this device" }).click();
    await expect(panel.getByRole("alert")).toContainText("blocking notifications");
  });
});
