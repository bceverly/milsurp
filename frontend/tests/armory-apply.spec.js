/**
 * Applying the shipped armory: the plan first, then the change.
 *
 * "Load shipped armory" only adds what is missing, so a cleaned-up file
 * reached nobody who already had the rows. "Apply shipped armory…" shows
 * what would change -- it overwrites -- and only then does it. The responses
 * are drawn from what the server would say rather than applied for real:
 * this database is shared with every other armory test, and applying the
 * shipped file would promote rows they expect to find awaiting approval.
 */
import { test, expect, openPage } from "./fixtures.js";

const PLAN = {
  added: 1,
  updated: 2,
  calibers: [
    { name: ".52", action: "update", fields: ["status"] },
    { name: "7.62x54R", action: "update", fields: ["aliases"] },
  ],
  models: [{ name: "Carcano M91 Cavalry Carbine", action: "add", fields: [] }],
  manufacturers: [],
};

async function openArmory(page) {
  await openPage(page, "Armory");
}

test.describe("apply the shipped armory", () => {
  test("shows the plan and applies it", async ({ signedIn }) => {
    let applied = false;
    await signedIn.route("**/api/armory/sync/plan", (route) =>
      route.fulfill({ json: PLAN }),
    );
    await signedIn.route("**/api/armory/sync", (route) => {
      applied = true;
      return route.fulfill({
        json: {
          changed: 3,
          items_restamped: 12,
          message: "Added 1 and changed 2 row(s) from the shipped armory.",
        },
      });
    });
    await openArmory(signedIn);
    await signedIn.getByRole("button", { name: "Apply shipped armory…" }).click();

    const dialog = signedIn.getByRole("dialog");
    await expect(dialog.getByTestId("armory-apply-summary")).toContainText("1 to add");
    await expect(dialog.getByTestId("armory-apply-summary")).toContainText("2 to change");
    await expect(dialog).toContainText("Calibers (2)");
    await expect(dialog).toContainText(".52 — status");
    await expect(dialog).toContainText("Carcano M91 Cavalry Carbine");
    expect(applied).toBe(false);

    await dialog.getByRole("button", { name: "Apply 3 change(s)" }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    await expect(signedIn.getByText("Added 1 and changed 2 row(s)")).toBeVisible();
    expect(applied).toBe(true);
  });

  test("a long list says how many more", async ({ signedIn }) => {
    const many = Array.from({ length: 45 }, (_, i) => ({
      name: `.${10 + i} test`,
      action: "update",
      fields: ["aliases"],
    }));
    await signedIn.route("**/api/armory/sync/plan", (route) =>
      route.fulfill({
        json: { ...PLAN, updated: 45, added: 0, calibers: many, models: [] },
      }),
    );
    await openArmory(signedIn);
    await signedIn.getByRole("button", { name: "Apply shipped armory…" }).click();
    await expect(signedIn.getByRole("dialog")).toContainText("and 5 more");
  });

  test("an armory that already matches has nothing to apply", async ({ signedIn }) => {
    await signedIn.route("**/api/armory/sync/plan", (route) =>
      route.fulfill({
        json: { added: 0, updated: 0, calibers: [], models: [], manufacturers: [] },
      }),
    );
    await openArmory(signedIn);
    await signedIn.getByRole("button", { name: "Apply shipped armory…" }).click();
    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toContainText("already matches the shipped file");
    await expect(dialog.getByRole("button", { name: /^Apply/ })).toHaveCount(0);
    await dialog.getByRole("button", { name: "Done" }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
  });

  test("failures are said, not swallowed", async ({ signedIn }) => {
    await signedIn.route("**/api/armory/sync/plan", (route) =>
      route.fulfill({ json: PLAN }),
    );
    await signedIn.route("**/api/armory/sync", (route) =>
      route.fulfill({ status: 500, json: { detail: "The file could not be read" } }),
    );
    await openArmory(signedIn);
    await signedIn.getByRole("button", { name: "Apply shipped armory…" }).click();
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByRole("button", { name: "Apply 3 change(s)" }).click();
    await expect(dialog.getByRole("alert")).toContainText("could not be read");
    await expect(dialog.getByRole("button", { name: "Apply 3 change(s)" })).toBeEnabled();
  });

  test("a plan that will not load says so", async ({ signedIn }) => {
    await signedIn.route("**/api/armory/sync/plan", (route) =>
      route.fulfill({ status: 500, json: { detail: "No shipped armory" } }),
    );
    await openArmory(signedIn);
    await signedIn.getByRole("button", { name: "Apply shipped armory…" }).click();
    await expect(signedIn.getByRole("dialog").getByRole("alert")).toContainText(
      "No shipped armory",
    );
  });
});
