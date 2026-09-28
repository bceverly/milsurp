/**
 * Switching off, or deleting, a selection of armory rows.
 *
 * The bar that appears with a selection could promote and send back; ruling on
 * a queue of scan-proposed junk still meant opening each row to switch it off.
 * Each test adds rows of its own, named for the run, because the database is
 * shared with the other armory specs.
 */
import { test, expect, openPage } from "./fixtures.js";

async function addModel(page, name) {
  await page.getByRole("button", { name: "Add model" }).click();
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Add, awaiting approval" }).click();
  await expect(page.locator("tbody tr", { hasText: name })).toHaveCount(1);
}

/** Search for the run's rows, so the table shows only them. */
async function showOnly(page, stem) {
  await page.getByLabel("Search").fill(stem);
  // Applied a moment after typing stops; until then the old table is up.
  await expect(page).toHaveURL(/[?&]q=/);
}

test.describe("armory bulk actions", () => {
  test("a selection can be switched off, and it leaves the queue", async ({
    signedIn,
  }) => {
    await openPage(signedIn, "Armory");
    const stem = `Bulk Off ${Date.now()}`;
    await addModel(signedIn, `${stem} A`);
    await addModel(signedIn, `${stem} B`);
    await showOnly(signedIn, stem);
    await expect(signedIn.locator("tbody tr", { hasText: stem })).toHaveCount(2);

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await signedIn.getByRole("button", { name: "Switch off" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("2 switched off");

    // Gone from Awaiting approval…
    await expect(signedIn.locator("tbody tr", { hasText: stem })).toHaveCount(0);
    // …and kept, under Disabled.
    await signedIn.getByLabel("Showing").selectOption("disabled");
    await expect(signedIn.locator("tbody tr", { hasText: stem })).toHaveCount(2);
  });

  test("a delete asks first, and can be called off", async ({ signedIn }) => {
    await openPage(signedIn, "Armory");
    const stem = `Bulk Del ${Date.now()}`;
    await addModel(signedIn, `${stem} A`);
    await addModel(signedIn, `${stem} B`);
    await showOnly(signedIn, stem);
    await expect(signedIn.locator("tbody tr", { hasText: stem })).toHaveCount(2);
    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();

    await signedIn.getByRole("button", { name: "Delete…" }).click();
    const question = signedIn.getByRole("group", { name: "Confirm delete" });
    await expect(question).toContainText("Switch off keeps it out");
    await question.getByRole("button", { name: "Cancel" }).click();
    await expect(signedIn.locator("tbody tr", { hasText: stem })).toHaveCount(2);

    await signedIn.getByRole("button", { name: "Delete…" }).click();
    await signedIn.getByRole("button", { name: "Delete 2 rows" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("2 deleted");
    await signedIn.getByLabel("Showing").selectOption("");
    await expect(signedIn.locator("tbody tr", { hasText: stem })).toHaveCount(0);
  });
});
