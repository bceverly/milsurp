/**
 * The security page's sessions and password panels.
 *
 * Sessions are exercised for real: a second browser context signs in as the
 * same account, which is exactly what "another session" is. The password is
 * not changed for real -- every test in the suite signs in with it -- so the
 * one success case answers from a route, and the two refusals are real.
 */
import { test, expect } from "./fixtures.js";

const USERNAME = process.env.MILSURP_USER || "admin";
const PASSWORD = process.env.MILSURP_PASSWORD || "";

async function signInElsewhere(browser) {
  const context = await browser.newContext({ userAgent: "Second Browser/1.0" });
  const page = await context.newPage();
  await page.goto("/");
  await page.fill('input[name="username"]', USERNAME);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await expect(page.getByRole("heading", { name: "Inventory" })).toBeVisible();
  return context;
}

test.describe("sessions", () => {
  test("another session is listed and can be revoked", async ({ signedIn, browser }) => {
    const elsewhere = await signInElsewhere(browser);
    try {
      await signedIn.goto("/security");
      const other = signedIn
        .locator("tbody tr", { hasText: "Second Browser/1.0" })
        .first();
      await expect(other).toBeVisible();
      await other.getByRole("button", { name: "Revoke" }).click();
      await expect(
        signedIn.locator("tbody tr", { hasText: "Second Browser/1.0" }),
      ).toHaveCount(0);
      // This browser is untouched.
      await expect(signedIn.locator("tbody tr", { hasText: "This browser" })).toHaveCount(
        1,
      );
    } finally {
      await elsewhere.close();
    }
  });

  test("every other session can be ended at once", async ({ signedIn, browser }) => {
    const elsewhere = await signInElsewhere(browser);
    try {
      await signedIn.goto("/security");
      const everywhere = signedIn.getByRole("button", {
        name: "Sign out everywhere else",
      });
      await expect(everywhere).toBeVisible();
      await everywhere.click();
      await expect(everywhere).toHaveCount(0);
      await expect(signedIn.locator("tbody tr")).toHaveCount(1);
    } finally {
      await elsewhere.close();
    }
  });

  test("a failure to end one says so", async ({ signedIn, browser }) => {
    const elsewhere = await signInElsewhere(browser);
    try {
      await signedIn.route("**/api/auth/sessions/*", (route) =>
        route.request().method() === "DELETE"
          ? route.fulfill({
              status: 500,
              json: { detail: "Could not end that session." },
            })
          : route.fallback(),
      );
      await signedIn.goto("/security");
      await signedIn
        .locator("tbody tr", { hasText: "Second Browser/1.0" })
        .first()
        .getByRole("button", { name: "Revoke" })
        .click();
      await expect(signedIn.locator(".alert--danger")).toContainText(
        "Could not end that session.",
      );
    } finally {
      await signedIn.unroute("**/api/auth/sessions/*");
      await elsewhere.close();
    }
  });
});

test.describe("changing the password", () => {
  async function fill(page, current, next, confirm) {
    await page.goto("/security");
    // By its heading: once a change succeeds the form is replaced by a
    // message, and a panel found by "Current password" would vanish with it.
    const panel = page.locator(".panel", {
      has: page.getByRole("heading", { name: "Password", exact: true }),
    });
    await panel.getByLabel("Current password").fill(current);
    // Anchored, because the label carries its hint too ("New password Must be
    // at least 12 characters.") and a bare "New password" also matches the
    // confirmation field.
    await panel.getByLabel(/^New password/).fill(next);
    await panel.getByLabel("Confirm new password").fill(confirm);
    await panel.getByRole("button", { name: "Change password" }).click();
    return panel;
  }

  test("two different new passwords are caught before anything is sent", async ({
    signedIn,
  }) => {
    let sent = false;
    await signedIn.route("**/api/auth/password", (route) => {
      sent = true;
      return route.fallback();
    });
    const panel = await fill(
      signedIn,
      PASSWORD,
      "a-long-new-passphrase-one",
      "a-long-new-passphrase-two",
    );
    await expect(panel.getByRole("alert")).toContainText("do not match");
    expect(sent).toBe(false);
  });

  test("a wrong current password is refused by the server, and says so", async ({
    signedIn,
  }) => {
    const panel = await fill(
      signedIn,
      "not-the-password-at-all",
      "a-long-new-passphrase-one",
      "a-long-new-passphrase-one",
    );
    await expect(panel.getByRole("alert")).toBeVisible();
    await expect(panel.getByRole("button", { name: "Change password" })).toBeVisible();
  });

  test("a change that succeeds says what it did to other sessions", async ({
    signedIn,
  }) => {
    await signedIn.route("**/api/auth/password", (route) =>
      route.fulfill({ status: 200, json: {} }),
    );
    const panel = await fill(
      signedIn,
      PASSWORD,
      "a-long-new-passphrase-one",
      "a-long-new-passphrase-one",
    );
    await expect(panel.locator(".alert--success")).toContainText("Password changed");
  });
});
