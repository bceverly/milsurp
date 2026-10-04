/**
 * A maker's marks: the factory codes that name it only on its own models.
 *
 * "byf" on a K98k is Mauser Oberndorf and "SA" on a Garand is Springfield
 * Armory, but neither means anything on its own, so they are kept apart from
 * the maker's spellings and read only by the arsenal step -- see
 * app/services/arsenals.py. This is the field that curates them.
 */
import { test, expect, openPage } from "./fixtures.js";

const NAME = "Marks Test Arsenal";

async function showMakers(page) {
  await openPage(page, "Armory");
  await page.getByRole("tab", { name: "Manufacturers" }).click();
  await expect(page.getByRole("tab", { name: "Manufacturers" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByLabel("Showing").selectOption("");
}

async function openMaker(page) {
  await page.getByLabel("Search").fill(NAME);
  const name = page.getByRole("button", { name: NAME, exact: true });
  await expect(name).toBeVisible();
  await name.click();
  return page.getByRole("dialog");
}

test("a maker's marks are saved, shown and changed", async ({ signedIn }) => {
  await showMakers(signedIn);
  await signedIn.getByRole("button", { name: "Add manufacturer" }).click();
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill(NAME);
  await dialog.getByLabel("Marks").fill("zzq\nS/99");
  await dialog.getByRole("button", { name: "Add manufacturer" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  dialog = await openMaker(signedIn);
  await expect(dialog.getByLabel("Marks")).toHaveValue("zzq\nS/99");
  await dialog.getByLabel("Marks").fill("zzq");
  await dialog.getByRole("button", { name: /^Save/ }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  dialog = await openMaker(signedIn);
  await expect(dialog.getByLabel("Marks")).toHaveValue("zzq");
  await dialog
    .getByRole("button", { name: /^Cancel|^Close/ })
    .first()
    .click();

  // Leave the armory as found.
  await signedIn.getByRole("button", { name: `Delete ${NAME}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(signedIn.getByRole("button", { name: NAME, exact: true })).toHaveCount(0);
});
