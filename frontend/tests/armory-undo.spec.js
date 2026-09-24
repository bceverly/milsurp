/**
 * Undoing an armory change from the audit log.
 *
 * The Undo button appears only where the server says the change can be put
 * back — an armory edit or deletion that recorded what the row held first.
 * Everything else in the log has no "before", and a button that answers with
 * an error is worse than no button.
 */
import { test, expect, openPage } from "./fixtures.js";

/**
 * Load the shipped armory and wait for it to say it has.
 *
 * Every test here starts from it, and not waiting was a race each time: the
 * load's own reload replaces the table, so a search typed, a row ticked or a
 * tab chosen before it lands is done to a table about to vanish. Under a
 * loaded machine that went from rare to four failures in one run.
 */
async function loadShipped(page) {
  await page.getByRole("button", { name: "Load shipped armory" }).click();
  await expect(page.locator(".alert--success")).toBeVisible();
}

test.describe("armory undo", () => {
  test("an edit can be undone, and the undo is itself logged", async ({ signedIn }) => {
    await openPage(signedIn, "Armory");
    await loadShipped(signedIn);
    await expect(signedIn.locator(".alert--success")).toBeVisible();

    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    // The row's name *is* the edit control on this page; there is no separate
    // Edit button.
    const opener = signedIn.locator("tbody tr td:nth-child(2) button").first();
    await expect(opener).toBeVisible();
    const original = (await opener.innerText()).trim();
    await opener.click();

    await signedIn.getByLabel("Name", { exact: true }).fill(`${original} (typo)`);
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    // The edit says what it cost, which is what makes somebody want the undo.
    await expect(signedIn.locator(".alert--success")).toContainText("Saved");

    await openPage(signedIn, "Audit log");
    const entry = signedIn.locator("tbody tr", { hasText: "Armory row changed" }).first();
    await expect(entry).toBeVisible();
    await entry.getByRole("button", { name: "Undo" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("put back");

    // The undo is logged too, so "actually, put it back again" is the same
    // operation on a newer event — and that newer event is not itself
    // revertible, so it offers no button.
    const undone = signedIn
      .locator("tbody tr", { hasText: "Armory change undone" })
      .first();
    await expect(undone).toBeVisible();
    await expect(undone.getByRole("button", { name: "Undo" })).toHaveCount(0);
  });

  test("and the name really is back", async ({ signedIn }) => {
    await openPage(signedIn, "Armory");
    await loadShipped(signedIn);
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();

    const opener = signedIn.locator("tbody tr td:nth-child(2) button").first();
    const original = (await opener.innerText()).trim();
    await opener.click();
    await signedIn.getByLabel("Name", { exact: true }).fill("Definitely Wrong");
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);

    await openPage(signedIn, "Audit log");
    await signedIn
      .locator("tbody tr", { hasText: "Armory row changed" })
      .first()
      .getByRole("button", { name: "Undo" })
      .click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();

    await openPage(signedIn, "Armory");
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await expect(signedIn.locator("tbody tr td:nth-child(2) button").first()).toHaveText(
      original,
    );
  });
});
