/**
 * A model's variants: edited in the model's dialog on the Armory page, and
 * shown on a listing as the version it is, or the versions it could be.
 * Which variant a listing matches is the server's business
 * (app/services/variants.py).
 */
import { test, expect } from "./fixtures.js";
import { searchFor, openArmoryModels } from "./armory-helpers.js";

async function openListingWith(page, changes) {
  await page.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), ...changes } });
  });
  await page.goto("/?availability=all");
  await page.locator(".item-card").first().click();
  await expect(page.locator(".detail__facts")).toBeVisible();
}

test("a listing names the variant it is, with its MSRP", async ({ signedIn }) => {
  await openListingWith(signedIn, {
    barrel_inches: 4,
    finish: "Stainless",
    variant: {
      id: 1,
      label: 'Tracker .44 Magnum 4" Stainless',
      msrp: 599.99,
      maker_url: "https://www.taurususa.com/tracker",
      upc: null,
    },
  });
  const note = signedIn.getByTestId("variant-note");
  await expect(note).toContainText('Variant: Tracker .44 Magnum 4" Stainless');
  await expect(note).toContainText("MSRP $599.99");
  await expect(note.getByRole("link", { name: "maker’s page" })).toHaveAttribute(
    "href",
    "https://www.taurususa.com/tracker",
  );
  await expect(signedIn.locator(".detail__facts")).toContainText('4"');
  await expect(signedIn.locator(".detail__facts")).toContainText("Stainless");
});

test("a vague listing shows the versions it could be", async ({ signedIn }) => {
  await openListingWith(signedIn, {
    variant: null,
    variant_candidates: [
      { id: 1, label: 'Tracker .44 4" Black', msrp: 549.99 },
      { id: 2, label: 'Tracker .44 4" Stainless', msrp: 599.99 },
      { id: 3, label: 'Tracker .44 6.5" Black', msrp: null },
    ],
  });
  const note = signedIn.getByTestId("variant-note");
  await expect(note).toContainText("Could be any of 3 versions");
  await expect(note).toContainText("MSRP $549.99–$599.99");
  await expect(note.locator("li")).toHaveCount(3);
});

test("a variant shows what it costs new, and how far under this listing is", async ({
  signedIn,
}) => {
  await openListingWith(signedIn, {
    current_price: 400,
    variant: {
      id: 1,
      label: 'Tracker .44 Magnum 4" Black',
      msrp: 549.99,
      maker_url: null,
      upc: "725327351238",
      new_price: 500,
      new_stores: 12,
      new_price_url: "https://gun.deals/search/apachesolr_search/725327351238",
    },
  });
  const line = signedIn.getByTestId("new-price");
  await expect(line).toContainText("New: from $500 at 12 stores");
  await expect(line).toContainText("20% under new");
  await expect(line.getByRole("link", { name: "gun.deals" })).toHaveAttribute(
    "href",
    "https://gun.deals/search/apachesolr_search/725327351238",
  );
});

test("versions it could be show their new prices as a range", async ({ signedIn }) => {
  await openListingWith(signedIn, {
    variant: null,
    variant_candidates: [
      { id: 1, label: 'Tracker .44 4" Black', msrp: 549.99, new_price: 462.23 },
      { id: 2, label: 'Tracker .44 4" Stainless', msrp: 599.99, new_price: 519.99 },
    ],
  });
  await expect(signedIn.getByTestId("variant-note")).toContainText(
    "new from $462.23–$519.99",
  );
});

test("variants are added, changed and removed in the model's dialog", async ({
  signedIn,
}) => {
  await openArmoryModels(signedIn);
  await signedIn.getByRole("button", { name: "Add model" }).click();
  const name = `Variant Test ${Date.now()}`;
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Modern production").check();
  await dialog.getByRole("button", { name: "Add, awaiting approval" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  await searchFor(signedIn, name);
  const row = signedIn.locator("tbody tr", { hasText: name });
  await row.getByRole("button", { name, exact: true }).click();
  dialog = signedIn.getByRole("dialog");
  const editor = dialog.getByTestId("variants-editor");
  await editor.getByLabel("Variant", { exact: true }).fill(`${name} 4" Black`);
  await editor.getByLabel("Barrel (inches)").fill("4");
  await editor.getByLabel("Finish").selectOption("Black");
  await editor.getByLabel("MSRP").fill("549.99");
  await editor.getByLabel("Finish").selectOption("Black");
  await editor.getByRole("button", { name: "Add variant" }).click();
  await expect(editor.locator("tbody tr")).toHaveCount(1);
  await expect(editor).toContainText("$549.99");
  // Added by hand it is approved; one from a maker's site would wait here.
  await expect(editor.getByRole("button", { name: /^Approve / })).toHaveCount(0);

  await editor.getByRole("button", { name: `Edit ${name} 4" Black` }).click();
  await editor.getByLabel("MSRP").fill("529.99");
  await editor.getByRole("button", { name: "Save variant" }).click();
  await expect(editor).toContainText("$529.99");

  await editor.getByRole("button", { name: `Delete ${name} 4" Black` }).click();
  await expect(editor.locator("tbody tr")).toHaveCount(0);

  await dialog
    .getByRole("button", { name: /^Cancel|^Close/ })
    .first()
    .click();
  await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(row).toHaveCount(0);
});
