/**
 * "Request access" on the sign-in screen.
 *
 * The e2e server runs in dev mode, where the form is switched off (see
 * auth.spec.js), so its config is answered from a route here to draw it the
 * way production does. Google's reCAPTCHA script is never fetched: a stub
 * stands in for it, which is also the only way a test can see the token it
 * hands over reach the request.
 */
import { test, expect } from "./fixtures.js";

const RECAPTCHA_STUB = `
  window.grecaptcha = {
    ready: (callback) => callback(),
    execute: () => Promise.resolve("stub-token"),
  };
`;

async function offer(page, config) {
  await page.route("**/api/access-request/config", (route) =>
    route.fulfill({ json: config }),
  );
  await page.route("https://www.google.com/recaptcha/**", (route) =>
    route.fulfill({ contentType: "text/javascript", body: RECAPTCHA_STUB }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Request access" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

async function fillIn(dialog) {
  await dialog.getByLabel("First name").fill("Ada");
  await dialog.getByLabel("Last name").fill("Collector");
  await dialog.getByLabel("Email address").fill("ada@example.test");
  await dialog.getByLabel(/Anything else/).fill("I collect Swiss rifles.");
}

test.describe("requesting access", () => {
  test("the request is sent with the challenge's token, and acknowledged", async ({
    page,
  }) => {
    let sent = null;
    await page.route("**/api/access-request", (route) => {
      sent = route.request().postDataJSON();
      return route.fulfill({
        json: { message: "Thanks -- your request has been sent." },
      });
    });
    const dialog = await offer(page, { enabled: true, recaptcha_site_key: "site-key" });
    await expect(dialog).toContainText("Protected by reCAPTCHA");
    await fillIn(dialog);
    await dialog.getByRole("button", { name: "Send request" }).click();

    await expect(dialog.locator(".alert--success")).toContainText(
      "your request has been sent",
    );
    expect(sent).toMatchObject({
      first_name: "Ada",
      last_name: "Collector",
      email: "ada@example.test",
      message: "I collect Swiss rifles.",
      recaptcha_token: "stub-token",
    });
    await dialog.getByRole("button", { name: "Close" }).last().click();
    await expect(dialog).toHaveCount(0);
  });

  test("a refused request says why and keeps what was typed", async ({ page }) => {
    await page.route("**/api/access-request", (route) =>
      route.fulfill({
        status: 429,
        json: { detail: "Too many requests. Try again later." },
      }),
    );
    const dialog = await offer(page, { enabled: true, recaptcha_site_key: "site-key" });
    await fillIn(dialog);
    await dialog.getByRole("button", { name: "Send request" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Too many requests");
    await expect(dialog.getByLabel("First name")).toHaveValue("Ada");
  });

  test("without a challenge configured it sends no token", async ({ page }) => {
    let sent = null;
    await page.route("**/api/access-request", (route) => {
      sent = route.request().postDataJSON();
      return route.fulfill({ json: { message: "Sent." } });
    });
    const dialog = await offer(page, { enabled: true, recaptcha_site_key: null });
    await expect(dialog).not.toContainText("Protected by reCAPTCHA");
    await fillIn(dialog);
    await dialog.getByLabel(/Anything else/).fill("");
    await dialog.getByRole("button", { name: "Send request" }).click();
    await expect(dialog.locator(".alert--success")).toBeVisible();
    expect(sent.recaptcha_token).toBeNull();
    // An empty message goes as nothing rather than as an empty string.
    expect(sent.message).toBeNull();
  });

  test("cancel closes it without sending", async ({ page }) => {
    let sent = false;
    await page.route("**/api/access-request", (route) => {
      sent = true;
      return route.fulfill({ json: { message: "Sent." } });
    });
    const dialog = await offer(page, { enabled: true, recaptcha_site_key: null });
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    expect(sent).toBe(false);
  });
});
