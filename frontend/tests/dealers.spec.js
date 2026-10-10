/**
 * Your FFL dealers: entered by hand, and the cheapest one prices everything.
 */
import { test, expect, openPage } from "./fixtures.js";

async function addDealer(page, { name, address, url, fee }) {
  await page.getByRole("button", { name: "Add a dealer" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  if (address) await dialog.getByLabel("Address").fill(address);
  if (url) await dialog.getByLabel("Website").fill(url);
  await dialog.getByLabel("Transfer fee").fill(fee);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("dealers are added, the lowest marked, changed and removed", async ({
  signedIn,
}) => {
  await openPage(signedIn, "FFL dealers");
  await expect(signedIn.getByText("No dealers yet")).toBeVisible();

  // A fee that is not a dollar amount is refused in the form.
  await signedIn.getByRole("button", { name: "Add a dealer" }).click();
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill("Nobody");
  await dialog.getByLabel("Transfer fee").fill("-3");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog.locator(".alert--error")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();

  await addDealer(signedIn, {
    name: "Corner Guns",
    address: "12 Main St\nSpringfield",
    url: "cornerguns.example",
    fee: "40",
  });
  await addDealer(signedIn, { name: "Kitchen Table FFL", fee: "15" });

  const table = signedIn.getByTestId("dealers-table");
  const corner = table.locator("tr", { hasText: "Corner Guns" });
  const kitchen = table.locator("tr", { hasText: "Kitchen Table FFL" });
  await expect(corner.getByRole("link", { name: /cornerguns\.example/ })).toHaveAttribute(
    "href",
    "https://cornerguns.example",
  );
  await expect(corner).toContainText("12 Main St");
  await expect(kitchen).toContainText("Lowest");
  await expect(corner).not.toContainText("Lowest");

  // Raised above the other, the lowest moves.
  await kitchen.getByRole("button", { name: "Kitchen Table FFL", exact: true }).click();
  dialog = signedIn.getByRole("dialog");
  await expect(dialog.getByLabel("Transfer fee")).toHaveValue("15");
  await dialog.getByLabel("Transfer fee").fill("60");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);
  await expect(corner).toContainText("Lowest");
  await expect(kitchen).not.toContainText("Lowest");

  // Leave the account as found.
  for (const name of ["Corner Guns", "Kitchen Table FFL"]) {
    await signedIn.getByRole("button", { name: `Remove ${name}` }).click();
    await signedIn.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
    await expect(table.locator("tr", { hasText: name })).toHaveCount(0);
  }
  await expect(signedIn.getByText("No dealers yet")).toBeVisible();
});
