/**
 * The Email digest page: which sites it covers, and what it has sent.
 *
 * The digest settings themselves are covered in workflows.spec.js. This holds
 * the site picker's shortcuts, a save the server refuses, and the delivery
 * log -- reading a sent digest back is how somebody checks what actually went
 * out, and nothing drew it in a test because the e2e server sends no mail.
 * The log answers from routes shaped as the real endpoints are.
 */
import { test, expect, openPage } from "./fixtures.js";

const SENT = {
  id: 41,
  sent_at: "2026-09-20T12:00:00Z",
  subject: "Milsurp Monitor: 3 new listings",
  status: "sent",
  new_item_count: 3,
  price_drop_count: 1,
  error_message: null,
  has_body: true,
};

async function open(page) {
  await openPage(page, "Email digest");
}

function sitesPanel(page) {
  return page.locator(".panel", {
    has: page.getByRole("heading", { name: "Sites", exact: true }),
  });
}

test.describe("which sites the digest covers", () => {
  test("select all, clear, and a single tick are all counted", async ({ signedIn }) => {
    await open(signedIn);
    const panel = sitesPanel(signedIn);
    // None ticked means every site, including ones added later.
    await expect(panel.getByText("All sites")).toBeVisible();

    await panel.getByRole("button", { name: "Select all" }).click();
    await expect(panel.getByText(/^\d+ selected$/)).toBeVisible();
    await expect(panel.getByRole("button", { name: "Select all" })).toBeDisabled();

    await panel.getByRole("button", { name: "Clear" }).click();
    await expect(panel.getByText("All sites")).toBeVisible();
    await expect(panel.getByRole("button", { name: "Clear" })).toBeDisabled();

    await panel.getByRole("checkbox").first().check();
    await expect(panel.getByText("1 selected")).toBeVisible();
    await panel.getByRole("checkbox").first().uncheck();
    await expect(panel.getByText("All sites")).toBeVisible();
  });

  test("a save the server refuses says why", async ({ signedIn }) => {
    await signedIn.route("**/api/preferences/email", (route) =>
      route.request().method() === "GET"
        ? route.fallback()
        : route.fulfill({
            status: 400,
            json: { detail: "That frequency is not offered." },
          }),
    );
    await open(signedIn);
    await signedIn.getByRole("button", { name: /^Save/ }).click();
    await expect(signedIn.getByRole("alert")).toContainText(
      "That frequency is not offered.",
    );
  });
});

test.describe("what the digest has sent", () => {
  test("a sent digest can be read back", async ({ signedIn }) => {
    await signedIn.route("**/api/preferences/email/history?**", (route) =>
      route.fulfill({ json: [SENT] }),
    );
    await signedIn.route("**/api/preferences/email/history/41", (route) =>
      route.fulfill({ json: { body_text: "3 new listings at Royal Tiger Imports." } }),
    );
    await open(signedIn);
    const row = signedIn.locator("tbody tr", { hasText: SENT.subject });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Read" }).click();

    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toContainText("3 new listings at Royal Tiger Imports.");
    await dialog.getByRole("button", { name: "Close" }).last().click();
    await expect(dialog).toHaveCount(0);
  });

  test("one that cannot be fetched says so in the dialog", async ({ signedIn }) => {
    await signedIn.route("**/api/preferences/email/history?**", (route) =>
      route.fulfill({ json: [SENT] }),
    );
    await signedIn.route("**/api/preferences/email/history/41", (route) =>
      route.fulfill({ status: 404, json: { detail: "That message is no longer kept." } }),
    );
    await open(signedIn);
    await signedIn
      .locator("tbody tr", { hasText: SENT.subject })
      .getByRole("button", { name: "Read" })
      .click();
    await expect(signedIn.getByRole("dialog").getByRole("alert")).toContainText(
      "no longer kept",
    );
  });
});
