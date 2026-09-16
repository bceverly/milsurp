/** Sign-in, session handling and the role boundary in the UI. */
import { test, expect } from "./fixtures.js";

const USERNAME = process.env.MILSURP_USER || "admin";
const PASSWORD = process.env.MILSURP_PASSWORD || "";

test.describe("sign in", () => {
  test("the login screen is what an unauthenticated visitor sees", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Milsurp Monitor" })).toBeVisible();
    await expect(page.locator('input[name="username"]')).toBeVisible();
    await expect(page.locator('input[name="password"]')).toHaveAttribute(
      "type",
      "password",
    );
  });

  test("a protected route redirects to the login screen", async ({ page }) => {
    await page.goto("/sites");
    await expect(page.locator('input[name="username"]')).toBeVisible();
  });

  test("the submit button stays disabled until both fields are filled", async ({
    page,
  }) => {
    await page.goto("/");
    const submit = page.getByRole("button", { name: "Sign in" });
    await expect(submit).toBeDisabled();
    await page.fill('input[name="username"]', "someone");
    await expect(submit).toBeDisabled();
    await page.fill('input[name="password"]', "something");
    await expect(submit).toBeEnabled();
  });

  test("bad credentials show an error and stay on the login screen", async ({ page }) => {
    await page.goto("/");
    await page.fill('input[name="username"]', "admin");
    await page.fill('input[name="password"]', "definitely-not-the-password");
    await page.click('button[type="submit"]');

    await expect(page.getByRole("alert")).toContainText(/incorrect/i);
    await expect(page.locator('input[name="username"]')).toBeVisible();
  });

  test("valid credentials land on the inventory", async ({ page }) => {
    await page.goto("/");
    await page.fill('input[name="username"]', USERNAME);
    await page.fill('input[name="password"]', PASSWORD);
    await page.click('button[type="submit"]');

    await expect(page.getByRole("heading", { name: "Inventory" })).toBeVisible();
    await expect(page.getByText(USERNAME, { exact: true })).toBeVisible();
  });

  test("the request-access form is hidden in dev mode", async ({ page }) => {
    // It is production-only; the server reports whether it is enabled.
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Request access" })).toHaveCount(0);
  });
});

test.describe("session", () => {
  test("survives a reload", async ({ signedIn }) => {
    await signedIn.reload();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });

  test("signing out returns to the login screen", async ({ signedIn }) => {
    await signedIn.locator("button.topbar__signout").click();
    await expect(signedIn.locator('input[name="username"]')).toBeVisible();
  });

  test("signing out actually ends the session", async ({ signedIn, context }) => {
    /**
     * Stronger than it used to be, and deliberately so. It used to check that
     * a string had been removed from sessionStorage, which the page could do
     * on its own while the server happily went on honoring the session. The
     * session is a cookie now, so only the server can end it -- and reloading
     * is what proves it did.
     */
    await signedIn.locator("button.topbar__signout").click();
    await expect(signedIn.locator('input[name="username"]')).toBeVisible();

    const names = (await context.cookies()).map((c) => c.name);
    expect(names).not.toContain("milsurp_session");

    // The real check: a fresh load is not signed back in.
    await signedIn.reload();
    await expect(signedIn.locator('input[name="username"]')).toBeVisible();
  });

  test("the session cookie is not reachable from JavaScript", async ({ signedIn }) => {
    /** The whole reason it moved out of sessionStorage: one XSS hole should
     * not hand over a working session. */
    const visible = await signedIn.evaluate(() => document.cookie);
    expect(visible).not.toContain("milsurp_session");
    // The CSRF token is readable on purpose -- the page has to echo it back.
    expect(visible).toContain("milsurp_csrf");
  });

  test("an admin sees the admin-only navigation", async ({ signedIn }) => {
    await expect(signedIn.getByRole("link", { name: "Sites" })).toBeVisible();
    await expect(signedIn.getByRole("link", { name: "Users" })).toBeVisible();
    await expect(signedIn.getByText("Admin", { exact: true })).toBeVisible();
  });
});
