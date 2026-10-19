/**
 * The Armory's Serial tables tab (2026-10-19): the published serial-to-date
 * tables, a range to a row, added, edited and deleted here. Which listings a
 * range dates is the server's business (app/services/serials.py).
 */
import { test, expect } from "./fixtures.js";
import { addModel, openArmoryModels } from "./armory-helpers.js";

test("a serial range is added, edited and deleted", async ({ signedIn }) => {
  await openArmoryModels(signedIn);
  await addModel(signedIn, "Serial Table Rifle");

  await signedIn.getByRole("tab", { name: /^Serial tables/ }).click();
  await expect(signedIn).toHaveURL(/#serial-tables$/);
  const tab = signedIn.getByTestId("serials-tab");
  // No approval, so no Showing box.
  await expect(signedIn.getByLabel("Showing")).toHaveCount(0);

  await tab.getByRole("button", { name: "Add a range" }).click();
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Model").fill("Serial Table Rifle");
  await dialog.getByLabel("First serial").fill("2,000");
  await dialog.getByLabel("Last serial").fill("1999");
  await dialog.getByLabel("Made from").fill("1943");
  await dialog.getByLabel("Source").fill("TM 9-1275, page 12");
  await dialog.getByRole("button", { name: "Add" }).click();
  // The server refuses a range that runs backward, and says why.
  await expect(dialog).toContainText("The first serial is after the last.");
  await dialog.getByLabel("First serial").fill("1,000");
  await dialog.getByRole("button", { name: "Add" }).click();
  await expect(dialog).toHaveCount(0);

  const row = tab.locator("tbody tr", { hasText: "Serial Table Rifle" });
  await expect(row).toContainText("1,000 – 1,999");
  await expect(row).toContainText("1943");
  await expect(row).toContainText("TM 9-1275, page 12");
  await expect(signedIn.getByRole("tab", { name: /^Serial tables/ })).toHaveText(
    /^Serial tables \(\d+\)$/,
  );

  await row.getByRole("button", { name: "Edit Serial Table Rifle 1000" }).click();
  dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Made to").fill("1944");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(row).toContainText("1943–1944");

  await row.getByRole("button", { name: "Delete Serial Table Rifle 1000" }).click();
  await signedIn.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(row).toHaveCount(0);
});
