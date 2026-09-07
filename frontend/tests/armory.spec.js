/**
 * The armory page.
 *
 * The behavior worth pinning down here is the approval gate: everything
 * arrives awaiting approval, promoting is what moves it into production, and
 * nothing in between is silent about which state a row is in.
 */
import { test, expect } from "./fixtures.js";

test.describe("armory", () => {
  test.beforeEach(async ({ signedIn }) => {
    // Exact: a listing card reading "US M1 Garand, Springfield Armory" is
    // also a link whose name contains "Armory".
    await signedIn.getByRole("link", { name: "Armory", exact: true }).click();
    await expect(signedIn.getByRole("heading", { name: "Armory" })).toBeVisible();
  });

  test("loads the shipped armory, all of it awaiting approval", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // The success line specifically. A standing banner counts what is
    // awaiting approval and appears only once there is something to count, so
    // a bare ".alert" matches one element or two depending on the timing.
    await expect(signedIn.locator(".alert--success")).toContainText(
      /awaiting approval|already has/,
    );

    const rows = signedIn.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    // The default view is the pending queue, so every chip in it says so.
    const chips = signedIn.locator("tbody .chip");
    await expect(chips.first()).toHaveText("Awaiting approval");
  });

  test("promoting a row moves it to production and it stops being pending", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // A named row rather than whichever happens to sort first: the name cell
    // also carries a reference link and a chip, so a name read back out of it
    // is not the string it went in as.
    await signedIn.getByLabel("Search").fill("Karabiner 98k");
    const name = "Karabiner 98k";
    const target = signedIn.locator("tbody tr", { hasText: name });
    await expect(target).toHaveCount(1);
    await expect(target.locator(".chip")).toHaveText("Awaiting approval");
    await target.locator('input[type="checkbox"]').check();
    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText(
      "moved into production",
    );

    // Gone from the pending queue…
    await expect(signedIn.locator("tbody tr", { hasText: name })).toHaveCount(0);
    // …and present in production, marked as such.
    await signedIn.getByLabel("Showing").selectOption("approved");
    const row = signedIn.locator("tbody tr", { hasText: name });
    await expect(row).toHaveCount(1);
    await expect(row.locator(".chip")).toHaveText("Production");
  });

  test("a model is one row carrying several makers", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByLabel("Search").fill("M1 Garand");
    const rows = signedIn.locator("tbody tr", { hasText: "M1 Garand" });
    await expect(rows).toHaveCount(1);
    // Springfield and Winchester both built it, on the one row.
    await expect(rows.first()).toContainText("Springfield");
  });

  test("calibers are a separate tab and carry their other spellings", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await signedIn.getByLabel("Search").fill("7.65mm Browning");
    // Searching by an alias finds the row it belongs to, which is the point.
    await expect(signedIn.locator("tbody tr", { hasText: ".32 ACP" })).toHaveCount(1);
  });

  test("select all approves the whole pending queue in two clicks", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // Wait for real data rather than the first row: while it is fetching, the
    // only row in the table is "Loading…", which is also a visible row.
    await expect(signedIn.locator("tbody tr", { hasText: "M1 Garand" })).toHaveCount(1);
    const pending = await signedIn.locator("tbody tr").count();
    expect(pending).toBeGreaterThan(1);

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await expect(signedIn.locator(".armory-bulk")).toContainText("everything listed");

    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();

    // The pending queue is the default view, and it is now empty.
    await expect(signedIn.locator("tbody")).toContainText("Nothing here");
    // And what was in it is in production. Counted by name rather than by
    // total, because earlier tests in this file promote a row of their own.
    await signedIn.getByLabel("Showing").selectOption("approved");
    await expect(signedIn.locator("tbody tr", { hasText: "M1 Garand" })).toHaveCount(1);
  });

  test("select all again clears the selection", async ({ signedIn }) => {
    // "Everything" rather than the pending queue, so this does not depend on
    // what the test above left behind.
    await signedIn.getByLabel("Showing").selectOption("");
    await expect(signedIn.locator("tbody tr", { hasText: "M1 Garand" })).toHaveCount(1);

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await expect(signedIn.locator(".armory-bulk")).toBeVisible();
    await signedIn.getByRole("checkbox", { name: "Clear selection" }).uncheck();
    await expect(signedIn.locator(".armory-bulk")).toHaveCount(0);
  });

  test("manufacturers can be approved the same way", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    // The makers that arrived with the shipped armory are awaiting approval
    // like everything else, and this tab selects them the same way.
    await expect(signedIn.locator("tbody tr", { hasText: "Rock-Ola" })).toHaveCount(1);

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("production");
  });

  test("manufacturers are a tab here, not a page of their own", async ({ signedIn }) => {
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    const rows = signedIn.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    // No flat models textbox on a maker any more: the models are rows.
    await signedIn.getByRole("button", { name: "Mauser", exact: true }).first().click();
    await expect(signedIn.getByLabel("Also written as")).toBeVisible();
    await expect(signedIn.getByLabel("Models")).toHaveCount(0);
  });

  test("a maker expands to the models the armory says it built", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();

    const row = signedIn.locator("tbody tr", { hasText: "Mauser" }).first();
    await row.getByRole("button", { name: /Expand/ }).click();
    const drilldown = signedIn.locator(".armory-drilldown");
    await expect(drilldown).toBeVisible();
    // Mauser built the K98k, and "+ Add model" is offered right there.
    await expect(drilldown).toContainText("Karabiner 98k");
    await expect(drilldown.getByRole("button", { name: "Add model" })).toBeVisible();
  });

  test("+ Add model from a maker pre-checks that maker", async ({ signedIn }) => {
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    const row = signedIn.locator("tbody tr", { hasText: "Mauser" }).first();
    await row.getByRole("button", { name: /Expand/ }).click();
    await signedIn
      .locator(".armory-drilldown")
      .getByRole("button", { name: "Add model" })
      .click();

    // Scoped to the makers list: "8mm Mauser" and "7x57mm Mauser" are
    // cartridges in the field above, and they contain the word too.
    const makers = signedIn.locator(".armory-checkboxes").last();
    const mauser = makers.locator("label.checkbox", { hasText: /^Mauser$/ });
    await expect(mauser.locator('input[type="checkbox"]')).toBeChecked();
  });

  test("a caliber can be added without leaving the model dialog", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Add model" }).first().click();
    const unique = `9x99mm Test ${Date.now()}`;
    await signedIn.getByPlaceholder("A cartridge not listed above").fill(unique);
    await signedIn.getByRole("button", { name: "Add caliber" }).click();
    // It appears in the list, already ticked for this model.
    const added = signedIn.locator("label.checkbox", { hasText: unique });
    await expect(added.locator('input[type="checkbox"]')).toBeChecked();
  });

  test("adding a model by hand also arrives awaiting approval", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Add model" }).click();
    const unique = `Test Model ${Date.now()}`;
    await signedIn.getByLabel("Name").fill(unique);
    await signedIn.getByLabel("Kind").selectOption("carbine");
    await signedIn.getByRole("button", { name: "Add, awaiting approval" }).click();

    const row = signedIn.locator("tbody tr", { hasText: unique });
    await expect(row).toHaveCount(1);
    await expect(row.locator(".chip")).toHaveText("Awaiting approval");
    await expect(row).toContainText("Carbine");
  });
});

test.describe("armory access", () => {
  // Outside the describe above, which signs in before every test — that is
  // what this one must not have done.
  test("is not reachable without signing in", async ({ page }) => {
    await page.goto("/armory");
    await expect(page.locator('input[name="username"]')).toBeVisible();
  });
});
